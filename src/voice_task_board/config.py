from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from voice_task_board.paths import app_data_dir


logger = logging.getLogger(__name__)

_ENC_PREFIX = "dpapi:"

# App-specific entropy mixed into DPAPI. DPAPI keys are scoped to the Windows
# user, so without entropy ANY process running as the same user can call
# CryptUnprotectData and recover our secrets. Binding this fixed, app-specific
# salt means another app (or malware) in the same user session can't decrypt
# our blobs unless it also knows this value — it raises the bar from "any
# same-user code" to "code that targeted this app specifically".
_DPAPI_ENTROPY = b"voice-task-board/dpapi/v1"

# Set by _decrypt when it had to fall back to decrypting a pre-entropy blob, so
# _load knows to re-encrypt those secrets with entropy on this run.
_saw_legacy_blob = False


class EncryptionUnavailableError(Exception):
    """Raised when Windows DPAPI cannot encrypt a secret.

    We refuse to fall back to plaintext: the Gemini API key and the long-lived
    Google refresh token must never be written to disk unencrypted. The caller
    skips persisting the secret and surfaces this to the user instead.
    """


def _encrypt(plaintext: str) -> str:
    """Encrypt a string with Windows DPAPI, return 'dpapi:<base64>'.

    Raises EncryptionUnavailableError if DPAPI is unavailable — we fail closed
    rather than silently storing the secret in cleartext.
    """
    if not plaintext:
        return plaintext
    try:
        import win32crypt  # type: ignore[import-untyped]
        # 3rd positional arg is OptionalEntropy: bind our app-specific salt.
        blob = win32crypt.CryptProtectData(
            plaintext.encode("utf-8"), None, _DPAPI_ENTROPY, None, None, 0
        )
        return _ENC_PREFIX + base64.b64encode(blob).decode("ascii")
    except Exception as e:
        logger.error(f"DPAPI encrypt failed; refusing to store secret in plaintext: {e}")
        raise EncryptionUnavailableError(str(e)) from e


def _decrypt(value: str) -> str:
    """Decrypt a 'dpapi:<base64>' string. Pass plaintext through unchanged."""
    if not value or not value.startswith(_ENC_PREFIX):
        return value
    try:
        import win32crypt  # type: ignore[import-untyped]
        blob = base64.b64decode(value[len(_ENC_PREFIX):])
        # 2nd positional arg is OptionalEntropy. Try our app-specific salt
        # first; fall back to None for blobs written before entropy was added,
        # so existing users don't lose their saved key/token on upgrade. The
        # next _save() re-encrypts them with entropy.
        try:
            _desc, plain = win32crypt.CryptUnprotectData(blob, _DPAPI_ENTROPY, None, None, 0)
        except Exception:
            global _saw_legacy_blob
            _desc, plain = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
            _saw_legacy_blob = True
            logger.info("Decrypted a legacy no-entropy DPAPI blob; will re-encrypt with entropy on next save")
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
        # Set True when DPAPI was unavailable and we had to skip persisting a
        # secret rather than write it in plaintext. Surfaced to the UI so the
        # user knows their key/token did not save and why.
        self.encryption_unavailable: bool = False
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

                # Rewrite on disk if we found any legacy plaintext secrets, or
                # any DPAPI blob written before entropy was added, so everything
                # gets (re-)encrypted with entropy going forward.
                needs_rewrite = (
                    (raw_key and not raw_key.startswith(_ENC_PREFIX))
                    or isinstance(raw_tokens, dict)
                    or _saw_legacy_blob
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
        # Encrypt secrets first. If DPAPI is unavailable we DROP the secret from
        # what we write (never plaintext) and flag it, but still persist the
        # non-secret config below so settings like the hotkey aren't lost.
        self.encryption_unavailable = False

        try:
            gemini_blob = _encrypt(self.gemini_api_key) if self.gemini_api_key else None
        except EncryptionUnavailableError:
            gemini_blob = None
            self.encryption_unavailable = True

        tokens_blob = ""
        if self.remote_tokens:
            try:
                tokens_blob = _encrypt(json.dumps(self.remote_tokens))
            except EncryptionUnavailableError:
                tokens_blob = ""
                self.encryption_unavailable = True

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "gemini_api_key": gemini_blob,
                    "hotkey": self.hotkey,
                    "remote_provider": self.remote_provider,
                    "remote_tokens": tokens_blob,
                    "connect_banner_dismissed": self.connect_banner_dismissed,
                }, f, indent=2)
                logger.info("Config saved")
        except Exception as e:
            logger.warning(f"Failed to save config: {e}")

        if self.encryption_unavailable:
            logger.error(
                "DPAPI unavailable: secrets were NOT persisted (refused to write "
                "plaintext). The API key / remote tokens must be re-entered each run."
            )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
