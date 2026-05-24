from __future__ import annotations

import collections
import logging
import numpy as np
import sounddevice as sd
import threading
import time
from typing import Any, Callable

from voice_task_board.vad import SileroVAD


logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_FRAME_SIZE = 512
_SILENCE_THRESHOLD_FRAMES = 32
_MAX_FRAMES = 938
_PREROLL_FRAMES = 16

_vad: SileroVAD | None = None
_vad_lock = threading.Lock()

_PREFERRED_HOST_APIS = ("WASAPI", "Windows WDM-KS", "Windows DirectSound", "MME")


def _pick_input_device() -> int | None:
    """Pick the best input device on Windows. Prefer WASAPI > DirectSound > MME.

    MME often rejects 16 kHz int16 mono with PaErrorCode -9999 / MME error 11
    because it cannot resample; WASAPI handles rate conversion in shared mode.
    """
    try:
        hostapis = sd.query_hostapis()
    except Exception:
        return None
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


def _open_input_stream(callback: Callable[..., None]) -> tuple[sd.InputStream, int]:
    """Open an InputStream, falling back to the device's native sample rate.

    Returns (stream, actual_sample_rate). Caller is responsible for resampling
    to 16 kHz if actual_sample_rate != _SAMPLE_RATE.
    """
    device = _pick_input_device()
    try:
        stream = sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=_FRAME_SIZE,
            device=device,
            callback=callback,
        )
        return stream, _SAMPLE_RATE
    except sd.PortAudioError as e:
        logger.warning(f"Opening 16 kHz stream failed ({e}); falling back to device native rate")

    info = sd.query_devices(device, kind="input") if device is not None else sd.query_devices(kind="input")
    native_rate = int(info["default_samplerate"])
    stream = sd.InputStream(
        samplerate=native_rate,
        channels=1,
        dtype="int16",
        device=device,
        callback=callback,
    )
    logger.info(f"Opened InputStream at native rate {native_rate} Hz (will resample to {_SAMPLE_RATE})")
    return stream, native_rate


def _resample_int16(pcm: np.ndarray, src_rate: int, dst_rate: int = _SAMPLE_RATE) -> np.ndarray:
    if src_rate == dst_rate or pcm.size == 0:
        return pcm.astype(np.int16, copy=False)
    n_out = int(round(pcm.size * dst_rate / src_rate))
    if n_out <= 0:
        return np.zeros(0, dtype=np.int16)
    x_old = np.linspace(0.0, 1.0, pcm.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(x_new, x_old, pcm.astype(np.float32)).astype(np.int16)


def _get_vad() -> SileroVAD:
    """Get or create the singleton VAD instance."""
    global _vad
    if _vad is None:
        with _vad_lock:
            if _vad is None:
                _vad = SileroVAD()
    return _vad


def record_until_silence() -> bytes:
    vad = _get_vad()
    vad.reset()
    pcm_frames: collections.deque[np.ndarray] = collections.deque()
    preroll_buffer: collections.deque[np.ndarray] = collections.deque(maxlen=_PREROLL_FRAMES)
    frame_event = threading.Event()
    stop_event = threading.Event()
    speech_detected = False
    silence_frames = 0
    total_frames = 0
    no_speech_frames = 0

    def audio_callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        nonlocal speech_detected, silence_frames, total_frames, no_speech_frames

        if status:
            logger.warning(f"Audio callback status: {status}")

        frame = indata[:, 0].astype(np.int16).copy()
        is_speech = vad.is_speech(frame)

        if not speech_detected:
            preroll_buffer.append(frame)
            no_speech_frames += 1
            if is_speech:
                speech_detected = True
                no_speech_frames = 0
                logger.info("Speech detected, starting recording")
                pcm_frames.extend(preroll_buffer)
                total_frames = len(preroll_buffer)
            elif no_speech_frames >= 94:
                logger.info("No speech detected within 3 seconds, stopping")
                stop_event.set()
                return
        else:
            pcm_frames.append(frame)
            total_frames += 1
            if is_speech:
                silence_frames = 0
            else:
                silence_frames += 1

        if total_frames >= _MAX_FRAMES or silence_frames >= _SILENCE_THRESHOLD_FRAMES:
            stop_event.set()

        frame_event.set()

    logger.info("Starting audio recording")
    stream, actual_rate = _open_input_stream(audio_callback)
    if actual_rate != _SAMPLE_RATE:
        stream.close()
        raise sd.PortAudioError(
            f"VAD requires {_SAMPLE_RATE} Hz but device only supports {actual_rate} Hz"
        )
    with stream:
        stop_event.wait()

    pcm_data = b"".join(frame.astype(np.int16).tobytes() for frame in pcm_frames)
    logger.info(f"Recording stopped. Total frames: {total_frames}, silence frames: {silence_frames}, bytes: {len(pcm_data)}")
    return pcm_data


def record_while_held(is_held: Callable[[], bool], poll_interval: float = 0.03) -> bytes:
    """Record audio while is_held() returns True. Stops as soon as it returns False."""
    pcm_frames: list[np.ndarray] = []
    lock = threading.Lock()

    def audio_callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            logger.warning(f"Audio callback status: {status}")
        frame = indata[:, 0].astype(np.int16).copy()
        with lock:
            pcm_frames.append(frame)

    logger.info("Starting push-to-talk recording")
    stream, actual_rate = _open_input_stream(audio_callback)
    with stream:
        max_seconds = _MAX_FRAMES * _FRAME_SIZE / _SAMPLE_RATE
        start = time.monotonic()
        while is_held():
            if time.monotonic() - start >= max_seconds:
                logger.info("Hit max recording length, stopping")
                break
            time.sleep(poll_interval)

    with lock:
        captured = np.concatenate(pcm_frames) if pcm_frames else np.zeros(0, dtype=np.int16)
    resampled = _resample_int16(captured, actual_rate, _SAMPLE_RATE)
    pcm_data = resampled.tobytes()
    logger.info(
        f"Push-to-talk recording stopped. Captured {captured.size} samples @ {actual_rate} Hz, "
        f"output {resampled.size} samples @ {_SAMPLE_RATE} Hz, bytes: {len(pcm_data)}"
    )
    return pcm_data
