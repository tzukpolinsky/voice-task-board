"""Security regression tests for the 0.6.0 hardening:

  - DPAPI secret encryption now mixes in app-specific entropy, so same-user
    code that doesn't know the salt can't decrypt the stored Gemini key /
    Google refresh token (config.py).
  - The %APPDATA%\\VoiceTaskBoard data directory gets an explicit restrictive
    ACL (inheritance disabled; only SYSTEM, Administrators, current user)
    instead of relying on inherited ACLs (paths.py).

These are Windows-only behaviors and are skipped elsewhere.
"""
from __future__ import annotations

import base64
import os
import subprocess

import pytest

from voice_task_board import config, paths


# win32crypt is Windows-only (pywin32). Skip the whole module off-Windows.
win32crypt = pytest.importorskip("win32crypt")

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows-only security behavior")


SECRET = "AIzaSy-test-key-1234567890"


# ── DPAPI entropy ────────────────────────────────────────────────────────────

def test_encrypt_decrypt_round_trip() -> None:
    """A secret encrypted with entropy decrypts back to the original."""
    enc = config._encrypt(SECRET)
    assert enc.startswith(config._ENC_PREFIX)
    assert SECRET not in enc  # ciphertext, not plaintext
    assert config._decrypt(enc) == SECRET


def test_empty_string_passes_through() -> None:
    """Empty secrets are a no-op in both directions (no DPAPI call)."""
    assert config._encrypt("") == ""
    assert config._decrypt("") == ""


def test_plaintext_value_passes_through_decrypt() -> None:
    """A value without the dpapi: prefix is returned unchanged (legacy plaintext)."""
    assert config._decrypt("plain-key") == "plain-key"


def test_entropy_is_effective() -> None:
    """The core of the fix: a blob encrypted with our salt must NOT be
    decryptable by same-user code that calls DPAPI without the entropy."""
    enc = config._encrypt(SECRET)
    raw = base64.b64decode(enc[len(config._ENC_PREFIX):])
    with pytest.raises(Exception):
        win32crypt.CryptUnprotectData(raw, None, None, None, 0)


def test_legacy_no_entropy_blob_still_decrypts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blobs written before entropy existed (encrypted with None) must still
    decrypt on upgrade, and get flagged for re-encryption."""
    monkeypatch.setattr(config, "_saw_legacy_blob", False)

    legacy_raw = win32crypt.CryptProtectData(SECRET.encode(), None, None, None, None, 0)
    legacy_val = config._ENC_PREFIX + base64.b64encode(legacy_raw).decode("ascii")

    assert config._decrypt(legacy_val) == SECRET
    assert config._saw_legacy_blob is True


# ── Data-directory ACL ───────────────────────────────────────────────────────

def test_data_dir_acl_locked_down(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """app_data_dir() disables inheritance and grants only SYSTEM,
    Administrators, and the current user."""
    monkeypatch.setenv("APPDATA", str(tmp_path))

    d = paths.app_data_dir()
    assert d.exists()
    assert (d / paths._ACL_MARKER).exists()  # marker written => icacls succeeded

    out = subprocess.run(
        ["icacls", str(d)], check=True, capture_output=True, text=True
    ).stdout

    # Inheritance disabled: no "(I)" inherited ACEs should remain.
    assert "(I)" not in out, f"inherited ACEs still present:\n{out}"

    # SYSTEM and Administrators are always granted; the current user too.
    assert "NT AUTHORITY\\SYSTEM" in out
    assert "BUILTIN\\Administrators" in out
    user = os.environ.get("USERNAME")
    if user:
        assert user in out


def test_data_dir_acl_is_idempotent(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Once the marker exists, a second call is a no-op and returns the same dir."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    first = paths.app_data_dir()
    second = paths.app_data_dir()
    assert first == second
