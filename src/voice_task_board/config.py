from __future__ import annotations

import json
import logging
import os

from voice_task_board.paths import app_data_dir


logger = logging.getLogger(__name__)


class Config:
    def __init__(self) -> None:
        self.config_path = app_data_dir() / "config.json"
        self.gemini_api_key: str | None = None
        self.hotkey: str = "ctrl+shift+space"
        self._load()

    def _load(self) -> None:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.gemini_api_key = data.get("gemini_api_key")
                    self.hotkey = data.get("hotkey", "ctrl+shift+space")
                    logger.info("Config loaded")
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")
        else:
            self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
            if self.gemini_api_key:
                logger.info("API key loaded from GEMINI_API_KEY environment variable")
            self._save()

    def _save(self) -> None:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "gemini_api_key": self.gemini_api_key,
                    "hotkey": self.hotkey,
                }, f, indent=2)
                logger.info("Config saved")
        except Exception as e:
            logger.warning(f"Failed to save config: {e}")


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
