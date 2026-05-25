from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from voice_task_board.paths import app_data_dir


logger = logging.getLogger(__name__)

_ENC_PREFIX = "dpapi:"


def _encrypt(plaintext: str) -> str:
    """Encrypt a string with Windows DPAPI, return 'dpapi:<base64>'."""
    if not plaintext:
        return plaintext
    try:
        import win32crypt  # type: ignore[import-untyped]
        blob = win32crypt.CryptProtectData(plaintext.encode("utf-8"), None, None, None, None, 0)
        return _ENC_PREFIX + base64.b64encode(blob).decode("ascii")
    except Exception as e:
        logger.warning(f"DPAPI encrypt failed, storing plaintext: {e}")
        return plaintext


def _decrypt(value: str) -> str:
    """Decrypt a 'dpapi:<base64>' string. Pass plaintext through unchanged."""
    if not value or not value.startswith(_ENC_PREFIX):
        return value
    try:
        import win32crypt  # type: ignore[import-untyped]
        blob = base64.b64decode(value[len(_ENC_PREFIX):])
        _desc, plain = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        return plain.decode("utf-8")
    except Exception as e:
        logger.warning(f"DPAPI decrypt failed: {e}")
        return ""


class Config:
    def __init__(self) -> None:
        self.config_path = app_data_dir() / "config.json"
        self.gemini_api_key: str | None = None
        self.hotkey: str = "ctrl+shift+space"
        # Remote provider: 'google' | 'microsoft' | None
        self.remote_provider: str | None = None
        # OAuth tokens stored as opaque dicts (provider-specific)
        self.remote_tokens: dict[str, Any] = {}
        # Whether the user permanently dismissed the "connect a calendar" banner
        self.connect_banner_dismissed: bool = False
        self._load()

    def _load(self) -> None:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    raw_key = data.get("gemini_api_key")
                    self.gemini_api_key = _decrypt(raw_key) if raw_key else None
                    self.hotkey = data.get("hotkey", "ctrl+shift+space")
                    self.remote_provider = data.get("remote_provider")
                    raw_tokens = data.get("remote_tokens", "")
                    if isinstance(raw_tokens, str) and raw_tokens:
                        try:
                            self.remote_tokens = json.loads(_decrypt(raw_tokens))
                        except Exception:
                            self.remote_tokens = {}
                    elif isinstance(raw_tokens, dict):
                        # Legacy plaintext dict — load as-is; will be encrypted on next save.
                        self.remote_tokens = raw_tokens
                    else:
                        self.remote_tokens = {}
                    self.connect_banner_dismissed = data.get("connect_banner_dismissed", False)
                    logger.info("Config loaded")

                # Rewrite on disk if we found any legacy plaintext secrets,
                # so they get encrypted going forward.
                needs_rewrite = (
                    (raw_key and not raw_key.startswith(_ENC_PREFIX))
                    or isinstance(raw_tokens, dict)
                )
                if needs_rewrite:
                    self._save()
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")
        else:
            self.gemini_api_key = os.environ.get("GEMINI_API_KEY")
            if self.gemini_api_key:
                logger.info("API key loaded from GEMINI_API_KEY environment variable")
            self._save()

    def _save(self) -> None:
        try:
            tokens_blob = ""
            if self.remote_tokens:
                tokens_blob = _encrypt(json.dumps(self.remote_tokens))

            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "gemini_api_key": _encrypt(self.gemini_api_key) if self.gemini_api_key else None,
                    "hotkey": self.hotkey,
                    "remote_provider": self.remote_provider,
                    "remote_tokens": tokens_blob,
                    "connect_banner_dismissed": self.connect_banner_dismissed,
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
