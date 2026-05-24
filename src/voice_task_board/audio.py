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
    with sd.InputStream(
        samplerate=_SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=_FRAME_SIZE,
        callback=audio_callback,
    ):
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
    with sd.InputStream(
        samplerate=_SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=_FRAME_SIZE,
        callback=audio_callback,
    ):
        max_seconds = _MAX_FRAMES * _FRAME_SIZE / _SAMPLE_RATE
        start = time.monotonic()
        while is_held():
            if time.monotonic() - start >= max_seconds:
                logger.info("Hit max recording length, stopping")
                break
            time.sleep(poll_interval)

    with lock:
        pcm_data = b"".join(f.tobytes() for f in pcm_frames)
    logger.info(f"Push-to-talk recording stopped. Frames: {len(pcm_frames)}, bytes: {len(pcm_data)}")
    return pcm_data
