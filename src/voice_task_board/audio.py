from __future__ import annotations

import contextlib
import logging
import numpy as np
import sounddevice as sd
import threading
import time
from typing import Any, Callable, Iterator


logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_MAX_RECORDING_SECONDS = 30

_PREFERRED_HOST_APIS = ("Windows WASAPI", "Windows DirectSound", "MME")
# MME is kept in the fallback chain as a last resort, but it's too fragile to
# honor as the "system default" short-circuit: 16 kHz int16 mono streams (and
# sometimes even native-rate streams) get rejected with paUnanticipatedHostError.
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


def _open_input_stream(callback: Callable[..., None]) -> tuple[sd.InputStream, int, int]:
    """Open an InputStream at the device's native rate and channel count.

    Returns (stream, sample_rate, channels). Caller is responsible for
    downmixing to mono and resampling to 16 kHz after capture.

    Rationale: WASAPI shared mode rejects any format that doesn't match the
    endpoint's mix format, MME is fragile with odd rates, and WDM-KS does no
    negotiation at all. Asking each backend for its native rate/channels and
    float32 dtype is the one combination every Windows host API accepts.
    """
    device = _pick_input_device()
    info = _device_info(device)
    native_rate = int(info["default_samplerate"])
    native_channels = int(info.get("max_input_channels", 1)) or 1

    stream = sd.InputStream(
        samplerate=native_rate,
        channels=native_channels,
        dtype="float32",
        device=device,
        callback=callback,
    )
    logger.info(
        f"Opened InputStream at {native_rate} Hz, {native_channels} ch, float32 "
        f"(will downmix + resample to {_SAMPLE_RATE} Hz mono int16)"
    )
    return stream, native_rate, native_channels


def _downmix_to_mono(pcm: np.ndarray) -> np.ndarray:
    """Average across channels. Accepts shape (N,) or (N, C)."""
    if pcm.ndim == 1:
        return pcm
    return pcm.mean(axis=1)


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

    mono = _downmix_to_mono(captured)
    resampled = _resample_float32(mono, actual_rate, _SAMPLE_RATE)
    pcm_int16 = _float32_to_int16(resampled)
    pcm_data = pcm_int16.tobytes()
    logger.info(
        f"Push-to-talk recording stopped. Captured {captured.shape[0]} samples @ "
        f"{actual_rate} Hz {actual_channels}ch, output {pcm_int16.size} samples @ "
        f"{_SAMPLE_RATE} Hz mono, bytes: {len(pcm_data)}"
    )
    return pcm_data
