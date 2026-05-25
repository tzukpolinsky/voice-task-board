from __future__ import annotations

import os
from pathlib import Path


def app_data_dir() -> Path:
    app_data = os.environ.get("APPDATA")
    if app_data is None:
        app_data = str(Path.home() / "AppData" / "Roaming")
    return Path(app_data) / "VoiceTaskBoard"


def archive_db_path() -> Path:
    app_data_dir().mkdir(parents=True, exist_ok=True)
    return app_data_dir() / "archive.db"
