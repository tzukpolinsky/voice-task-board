from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path


logger = logging.getLogger(__name__)

# Marker file: presence means we've already applied the restrictive ACL, so we
# skip the (slowish) icacls calls on every launch.
_ACL_MARKER = ".acl_locked"


def _lock_down_dir(d: Path) -> None:
    """Restrict the data dir to the current user only (best-effort, Windows).

    The dir holds the task DB and archive in cleartext (only the API key /
    refresh token are DPAPI-encrypted). %APPDATA% is already user-private by
    default, but we don't want to rely on inherited ACLs: disable inheritance
    and grant only SYSTEM, Administrators, and the current user. Never fatal —
    a failure here just leaves the OS-default ACL in place.
    """
    if os.name != "nt":
        return
    marker = d / _ACL_MARKER
    if marker.exists():
        return
    try:
        user = os.environ.get("USERNAME")
        target = str(d)
        # /inheritance:r removes inherited ACEs; /grant:r replaces grants for
        # the named principals. SID *S-1-5-18 = SYSTEM, *S-1-5-32-544 = Admins.
        cmds = [
            ["icacls", target, "/inheritance:r"],
            ["icacls", target, "/grant:r", "*S-1-5-18:(OI)(CI)F"],
            ["icacls", target, "/grant:r", "*S-1-5-32-544:(OI)(CI)F"],
        ]
        if user:
            cmds.append(["icacls", target, "/grant:r", f"{user}:(OI)(CI)F"])
        for cmd in cmds:
            subprocess.run(
                cmd, check=True, capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        marker.write_text("", encoding="utf-8")
        logger.info("Applied restrictive ACL to data directory")
    except Exception as e:
        # Don't block startup; we just fall back to the OS-default ACL.
        logger.warning(f"Could not lock down data directory ACL: {e}")


def app_data_dir() -> Path:
    app_data = os.environ.get("APPDATA")
    if app_data is None:
        app_data = str(Path.home() / "AppData" / "Roaming")
    d = Path(app_data) / "VoiceTaskBoard"
    d.mkdir(parents=True, exist_ok=True)
    _lock_down_dir(d)
    return d


def archive_db_path() -> Path:
    return app_data_dir() / "archive.db"
