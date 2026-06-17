from __future__ import annotations

import contextlib
import json
import logging
import numpy as np
import sounddevice as sd
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator


logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_MAX_RECORDING_SECONDS = 30
_DEVICE_CACHE_FILE = Path.home() / ".cache" / "voice_task_board" / "audio_device.json"

_PREFERRED_HOST_APIS = ("Windows WASAPI", "Windows DirectSound", "MME", "Windows WDM-KS")
# MME is kept in the fallback chain as a last resort, but it's too fragile to
# honor as the "system default" short-circuit: 16 kHz int16 mono streams (and
# sometimes even native-rate streams) get rejected with paUnanticipatedHostError.
# WDM-KS is the deepest fallback: on some machines (mic-privacy locked, Intel
# Smart Sound holding the endpoint) every shared-mode backend fails with -9996 /
# paUnanticipatedHostError and only the raw WDM-KS device will open.
_HONOR_SYSTEM_DEFAULT_HOST_APIS = ("Windows WASAPI", "Windows DirectSound")


@contextlib.contextmanager
def _muted_system_output() -> Iterator[None]:
    """Mute the default render endpoint for the duration of recording.

    Uses pycaw (Core Audio). If anything goes wrong (no audio device, COM
    init failure on a headless box, pycaw missing), we log and continue
    without muting rather than blocking recording.
    """
    volume = None
    previously_muted = False
    logger.info("Attempting to mute system output for recording")
    try:
        import comtypes
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        try:
            comtypes.CoInitialize()
        except OSError:
            pass

        speakers = AudioUtilities.GetSpeakers()
        imm_device = getattr(speakers, "_dev", speakers)
        interface = imm_device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        # IMPORTANT: do NOT use ctypes.cast here. Activate returns an
        # IUnknown* with refcount=1; cast reinterprets the same pointer
        # without AddRef, so `interface` and the cast result would both call
        # Release on __del__ — a double-free that surfaces as
        # "access violation reading 0xFFFFFFFFFFFFFFFF" and can corrupt the
        # shared COM state used by WebView2. QueryInterface AddRefs the new
        # interface (refcount=2), so each pointer has its own ref and each
        # Release balances correctly.
        volume = interface.QueryInterface(IAudioEndpointVolume)
        previously_muted = bool(volume.GetMute())
        if not previously_muted:
            volume.SetMute(1, None)
        logger.info("System output muted")
    except Exception as e:
        logger.warning(f"Could not mute system output: {e!r}")
        volume = None

    try:
        yield
    finally:
        if volume is not None and not previously_muted:
            try:
                volume.SetMute(0, None)
                logger.info("System output unmuted")
            except Exception as e:
                logger.warning(f"Could not restore system output mute state: {e!r}")
        # Explicitly release before thread exit so the COM pointer is cleaned up
        # in the correct apartment.  Do NOT call CoUninitialize() here — letting
        # the thread exit naturally tears down its STA cleanly, whereas an explicit
        # CoUninitialize() races with Python's GC releasing comtypes pointers from
        # an arbitrary thread, which corrupts the shared COM state used by WebView2.
        volume = None


def _pick_input_device() -> int | None:
    """Pick the best input device on Windows. Prefer WASAPI > DirectSound > MME."""
    try:
        hostapis = sd.query_hostapis()
    except Exception:
        return None
    honor_default_set = set(_HONOR_SYSTEM_DEFAULT_HOST_APIS)

    # 1. Honor the system default input only if it's on a robust host API.
    try:
        default_input_idx = sd.default.device[0]
    except Exception:
        default_input_idx = -1
    if isinstance(default_input_idx, int) and default_input_idx >= 0:
        try:
            dev = sd.query_devices(default_input_idx)
            hostapi_name = hostapis[dev["hostapi"]]["name"]
        except Exception:
            hostapi_name = None
        if hostapi_name in honor_default_set:
            logger.info(
                f"Using system default input device index {default_input_idx} ({hostapi_name})"
            )
            return default_input_idx

    # 2. Fall back to the first preferred host API's default input device.
    by_name = {ha["name"]: i for i, ha in enumerate(hostapis)}
    for preferred in _PREFERRED_HOST_APIS:
        idx = by_name.get(preferred)
        if idx is None:
            continue
        default_input = hostapis[idx].get("default_input_device", -1)
        if default_input is not None and default_input >= 0:
            logger.info(f"Using {preferred} input device index {default_input}")
            return default_input
    return None


def _device_info(device: int | None) -> dict[str, Any]:
    if device is None:
        return sd.query_devices(kind="input")
    return sd.query_devices(device, kind="input")


def _get_cached_device() -> int | None:
    """Load the last-known-working device from disk cache."""
    try:
        if _DEVICE_CACHE_FILE.exists():
            data = json.loads(_DEVICE_CACHE_FILE.read_text())
            return data.get("device_index")
    except Exception:
        pass
    return None


def _save_working_device(device: int) -> None:
    """Persist the working device index to disk."""
    try:
        _DEVICE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DEVICE_CACHE_FILE.write_text(json.dumps({"device_index": device}))
        logger.debug(f"Cached working device: {device}")
    except Exception as e:
        logger.debug(f"Could not cache audio device: {e}")


def _candidate_input_devices() -> list[int]:
    """Ordered list of input device indices to try, best first.

    Tries in order: cached device (fastest), system preferred, then all others
    grouped by host-API preference (WASAPI > DirectSound > MME > WDM-KS).
    De-duplicated, order-preserving. This is what makes recording resilient when
    the "best" backend is blocked: we fall through to one that actually opens.
    """
    ordered: list[int] = []

    def add(idx: int | None) -> None:
        if isinstance(idx, int) and idx >= 0 and idx not in ordered:
            ordered.append(idx)

    # 1. Try the cached device first (no probing delay if it still works).
    add(_get_cached_device())

    # 2. The preferred pick (system default / first preferred host API).
    add(_pick_input_device())

    # 2. Every input device, grouped by host-API preference order.
    try:
        hostapis = sd.query_hostapis()
        devices = sd.query_devices()
    except Exception:
        return ordered

    name_by_index = {i: ha["name"] for i, ha in enumerate(hostapis)}

    # Some capture-side devices are NOT real microphones — loopbacks and mixers
    # ("PC Speaker", "Stereo Mix", "What U Hear") and generic aggregates
    # ("Sound Mapper", "Primary Sound Capture Driver") still report input
    # channels and will happily open, but capture silence or the wrong source.
    # Rank those last so we prefer an actual mic that opens.
    def is_deprioritized(name: str) -> bool:
        lowered = name.lower()
        return any(
            kw in lowered
            for kw in ("pc speaker", "stereo mix", "what u hear", "wave out",
                       "sound mapper", "primary sound capture", "loopback")
        )

    for preferred in _PREFERRED_HOST_APIS:
        # Real mics first, then the deprioritized capture devices, per host API.
        for deprioritized in (False, True):
            for i, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) <= 0:
                    continue
                if name_by_index.get(dev.get("hostapi", -1)) != preferred:
                    continue
                if is_deprioritized(dev.get("name", "")) == deprioritized:
                    add(i)
    return ordered


def _device_formats(info: dict[str, Any]) -> list[tuple[int, int]]:
    """Formats to try for a device, best-first: native, native-mono, 16 kHz mono."""
    native_rate = int(info["default_samplerate"])
    native_channels = int(info.get("max_input_channels", 1)) or 1
    formats: list[tuple[int, int]] = []
    for fmt in [(native_rate, native_channels), (native_rate, 1), (_SAMPLE_RATE, 1)]:
        if fmt not in formats:
            formats.append(fmt)
    return formats


def _probe_has_signal(device: int | None, rate: int, channels: int,
                      seconds: float = 0.18) -> bool | None:
    """Briefly open the device and check whether it delivers non-silent audio.

    Returns True if a signal above the noise floor is seen, False if it opens but
    is pure digital silence (a dead/phantom endpoint), or None if it won't open.
    Some Windows capture endpoints ("Microphone (Realtek HD Audio Mic input)")
    enumerate and OPEN fine but only ever return zeros — probing weeds those out.
    """
    frames: list[np.ndarray] = []
    lock = threading.Lock()

    def cb(indata: np.ndarray, n: int, t: Any, status: Any) -> None:
        with lock:
            frames.append(indata.copy())

    try:
        stream = sd.InputStream(samplerate=rate, channels=channels,
                                dtype="float32", device=device, callback=cb)
    except Exception:
        return None
    try:
        with stream:
            time.sleep(seconds)
    except Exception:
        return None
    with lock:
        if not frames:
            return False
        data = np.concatenate(frames)
    # Pure-silence phantom endpoints return exactly 0.0; real mics show a tiny
    # noise floor even in a quiet room. Threshold well below speech level.
    return bool(data.size and float(np.max(np.abs(data))) > 1e-5)


def _open_input_stream(callback: Callable[..., None]) -> tuple[sd.InputStream, int, int]:
    """Open an InputStream, trying candidate devices/formats until one works.

    Returns (stream, sample_rate, channels). Caller downmixes to mono and
    resamples to 16 kHz after capture.

    Strategy:
      1. Try the preferred device first at its native format — the fast common
         path, no probing.
      2. If that fails, fall through every other candidate. For fallback devices
         we PROBE for actual signal, because some endpoints open but return pure
         silence (e.g. a phantom "Realtek Mic input"); we want a mic that really
         captures audio, not just one that opens.
      3. If nothing shows signal but something opened, use the first that opened
         (a real mic may be momentarily silent) rather than failing.
    """
    last_error: Exception | None = None
    candidates = _candidate_input_devices()
    if not candidates:
        candidates = [None]  # let PortAudio pick the default as a last resort

    def _open(device: int | None, rate: int, channels: int) -> sd.InputStream:
        return sd.InputStream(samplerate=rate, channels=channels,
                              dtype="float32", device=device, callback=callback)

    def _hostapi_name(info: dict[str, Any]) -> str:
        try:
            return sd.query_hostapis()[info["hostapi"]]["name"]
        except Exception:
            return "?"

    # --- 1. Fast path: preferred device, native format, no probe. ---
    preferred = candidates[0]
    try:
        info = _device_info(preferred)
        rate, channels = _device_formats(info)[0]
        stream = _open(preferred, rate, channels)
        logger.info(
            f"Opened InputStream on device={preferred} [{_hostapi_name(info)}] "
            f"at {rate} Hz, {channels} ch, float32 (preferred)"
        )
        return stream, rate, channels
    except Exception as e:
        last_error = e
        logger.info(f"Preferred input device={preferred} failed ({e}); probing fallbacks")

    # --- 2. Fallback: probe each remaining candidate for real signal. ---
    first_openable: tuple[int | None, int, int, dict] | None = None
    for device in candidates[1:]:
        try:
            info = _device_info(device)
        except Exception as e:
            last_error = e
            continue
        for rate, channels in _device_formats(info):
            sig = _probe_has_signal(device, rate, channels)
            if sig is None:
                continue  # didn't open at this format
            if first_openable is None:
                first_openable = (device, rate, channels, info)
            if sig:
                stream = _open(device, rate, channels)
                _save_working_device(device)
                logger.info(
                    f"Opened InputStream on device={device} [{_hostapi_name(info)}] "
                    f"at {rate} Hz, {channels} ch, float32 (probed: signal present)"
                )
                return stream, rate, channels
            logger.debug(f"device={device} rate={rate} ch={channels} opened but silent; skipping")
            break  # this device opens but is silent; move to next device

    # --- 3. Nothing showed signal: use the first that merely opened. ---
    if first_openable is not None:
        device, rate, channels, info = first_openable
        stream = _open(device, rate, channels)
        _save_working_device(device)
        logger.warning(
            f"No input device showed a live signal; using device={device} "
            f"[{_hostapi_name(info)}] at {rate} Hz, {channels} ch. If recordings "
            "are silent, check Windows mic privacy and that the mic isn't muted."
        )
        return stream, rate, channels

    logger.error(
        f"Could not open any microphone input stream. Tried devices {candidates}. "
        f"Last error: {last_error!r}. Check Windows Settings -> Privacy & security "
        "-> Microphone -> 'Let desktop apps access your microphone'."
    )
    if last_error is not None:
        raise last_error
    raise RuntimeError("No input devices available")


def _downmix_to_mono(pcm: np.ndarray) -> np.ndarray:
    """Average across channels. Accepts shape (N,) or (N, C)."""
    if pcm.ndim == 1:
        return pcm
    return pcm.mean(axis=1)


def _trim_silence(pcm: np.ndarray, rate: int, threshold_dbfs: float = -40.0,
                  pad_ms: int = 100) -> np.ndarray:
    """Trim leading/trailing silence from mono float32 audio.

    Gemini bills audio by DURATION (~25-32 tokens/sec), independent of sample
    rate or bytes, so trimming the dead air at the start/end of a push-to-talk
    recording directly cuts API cost. Conservative by design: it only cuts the
    outer silence, never interior pauses, and keeps a small pad before/after the
    speech so onsets/tails aren't clipped (clipping speech would hurt accuracy).
    Returns the input unchanged if it's empty or entirely below threshold.
    """
    if pcm.size == 0:
        return pcm
    # Frame-energy gate. Compare each ~20ms frame's peak to a threshold relative
    # to the clip's own peak (so it adapts to quiet vs loud recordings).
    peak = float(np.max(np.abs(pcm)))
    if peak <= 0.0:
        return pcm
    thresh = peak * (10 ** (threshold_dbfs / 20))
    frame = max(1, int(rate * 0.02))
    n_frames = pcm.size // frame
    if n_frames == 0:
        return pcm
    framed = pcm[: n_frames * frame].reshape(n_frames, frame)
    loud = np.max(np.abs(framed), axis=1) > thresh
    if not loud.any():
        return pcm  # nothing above threshold — leave it alone
    first = int(np.argmax(loud))
    last = n_frames - 1 - int(np.argmax(loud[::-1]))
    pad = int(rate * pad_ms / 1000)
    start = max(0, first * frame - pad)
    end = min(pcm.size, (last + 1) * frame + pad)
    return pcm[start:end]


def _resample_float32(pcm: np.ndarray, src_rate: int, dst_rate: int = _SAMPLE_RATE) -> np.ndarray:
    if src_rate == dst_rate or pcm.size == 0:
        return pcm.astype(np.float32, copy=False)
    n_out = int(round(pcm.size * dst_rate / src_rate))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, pcm.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(x_new, x_old, pcm).astype(np.float32)


def _float32_to_int16(pcm: np.ndarray) -> np.ndarray:
    clipped = np.clip(pcm, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16)


def validate_audio_device() -> bool:
    """Test the cached audio device at app startup. Returns True if valid, False otherwise.

    If the cached device no longer works (e.g., hardware was disconnected), clear the
    cache so the next recording will probe for a working device.
    """
    cached = _get_cached_device()
    if cached is None:
        return True  # No cache yet, will probe on first recording

    try:
        info = _device_info(cached)
        for rate, channels in _device_formats(info):
            if _probe_has_signal(cached, rate, channels):
                logger.debug(f"Audio device {cached} validated at startup")
                return True
    except Exception as e:
        logger.debug(f"Cached device {cached} validation failed: {e}")

    # Cached device is dead, clear it so we probe on next recording
    _DEVICE_CACHE_FILE.unlink(missing_ok=True)
    logger.info(f"Cleared invalid cached device {cached}")
    return False


def record_while_held(is_held: Callable[[], bool], poll_interval: float = 0.03) -> bytes:
    """Record audio while is_held() returns True. Stops as soon as it returns False.

    Captures at the device's native rate/channels in float32, then downmixes to
    mono and resamples to 16 kHz int16 PCM after the user releases the key.
    """
    pcm_frames: list[np.ndarray] = []
    lock = threading.Lock()

    def audio_callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            logger.warning(f"Audio callback status: {status}")
        with lock:
            pcm_frames.append(indata.copy())

    logger.info("Starting push-to-talk recording")
    with _muted_system_output():
        stream, actual_rate, actual_channels = _open_input_stream(audio_callback)
        with stream:
            start = time.monotonic()
            while is_held():
                if time.monotonic() - start >= _MAX_RECORDING_SECONDS:
                    logger.info("Hit max recording length, stopping")
                    break
                time.sleep(poll_interval)

    with lock:
        if pcm_frames:
            captured = np.concatenate(pcm_frames, axis=0)
        else:
            captured = np.zeros((0, actual_channels), dtype=np.float32)

    # No DSP enhancement: modern ASR transcribes raw audio best (Google/Deepgram
    # both advise against pre-send gain/denoise). We only downmix + resample to
    # 16 kHz, then trim leading/trailing silence — the one transform that cuts
    # cost, since Gemini bills audio by duration.
    mono = _downmix_to_mono(captured)
    resampled = _resample_float32(mono, actual_rate, _SAMPLE_RATE)
    trimmed = _trim_silence(resampled, _SAMPLE_RATE)
    pcm_int16 = _float32_to_int16(trimmed)
    pcm_data = pcm_int16.tobytes()
    logger.info(
        f"Push-to-talk recording stopped. Captured {captured.shape[0]} samples @ "
        f"{actual_rate} Hz {actual_channels}ch, output {pcm_int16.size} samples @ "
        f"{_SAMPLE_RATE} Hz mono, bytes: {len(pcm_data)}"
    )
    return pcm_data
