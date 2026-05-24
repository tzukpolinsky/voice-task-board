from __future__ import annotations

import os
from pathlib import Path


def app_data_dir() -> Path:
    app_data = os.environ.get("APPDATA")
    if app_data is None:
        app_data = str(Path.home() / "AppData" / "Roaming")
    return Path(app_data) / "VoiceTaskBoard"


def recordings_dir() -> Path:
    path = app_data_dir() / "recordings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = app_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path
