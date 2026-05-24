from __future__ import annotations

import logging
import numpy as np
import onnxruntime as rt
import sys
from pathlib import Path

from voice_task_board.paths import models_dir


logger = logging.getLogger(__name__)


def _resource_path(filename: str) -> Path:
    """Get path to bundled resource file."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "resources" / filename
    else:
        return Path(__file__).parent / "resources" / filename


class SileroVAD:
    def __init__(self) -> None:
        model_path = _resource_path("silero_vad.onnx")
        if not model_path.exists():
            raise FileNotFoundError(
                f"Silero VAD model not found at {model_path}. "
                "Please bundle the model with the application."
            )
        self._session = rt.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr = np.array(16000, dtype=np.int64)

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def is_speech(self, frame_int16: np.ndarray) -> bool:
        audio = (frame_int16.astype(np.float32) / 32768.0).reshape(1, 512)
        outputs = self._session.run(None, {
            "input": audio,
            "state": self._state,
            "sr": self._sr,
        })
        prob = float(outputs[0].item())
        self._state = outputs[1]
        return prob > 0.5
