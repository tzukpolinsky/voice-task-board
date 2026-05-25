from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

import httpx

from voice_task_board.config import get_config
from voice_task_board.db import get_db, Task
from voice_task_board.oauth import refresh_google_token, OAuthError


logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()

# How many tasks are in the pending-mirror retry queue (exposed for UI)
_pending_count: int = 0


def pending_count() -> int:
    return _pending_count


# ── token management ────────────────────────────────────────────────────────

def _access_token() -> str:
    config = get_config()
    if not config.remote_provider or not config.remote_tokens:
        raise OAuthError("No remote provider configured")
    try:
        config.remote_tokens = refresh_google_token(config.remote_tokens)
        config._save()
        return config.remote_tokens["access_token"]
    except Exception as e:
        raise OAuthError(f"Token refresh failed: {e}") from e


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"}


# ── Google Tasks ─────────────────────────────────────────────────────────────

GOOGLE_TASKLIST = "@default"
GOOGLE_BASE = "https://www.googleapis.com/tasks/v1"


def _google_create(task: Task) -> str:
    body: dict[str, Any] = {"title": task.title, "notes": task.description or ""}
    if task.due_at_utc:
        if task.is_full_day:
            body["due"] = f"{task.due_at_utc[:10]}T00:00:00.000Z"
        else:
            body["due"] = _to_rfc3339(task.due_at_utc)
    resp = httpx.post(
        f"{GOOGLE_BASE}/lists/{GOOGLE_TASKLIST}/tasks",
        headers=_headers(), json=body, timeout=15,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data["id"]


def _google_update(task: Task) -> None:
    if not task.external_id:
        return
    body: dict[str, Any] = {"title": task.title, "notes": task.description or ""}
    if task.due_at_utc:
        body["due"] = _to_rfc3339(task.due_at_utc) if not task.is_full_day else f"{task.due_at_utc[:10]}T00:00:00.000Z"
    resp = httpx.patch(
        f"{GOOGLE_BASE}/lists/{GOOGLE_TASKLIST}/tasks/{task.external_id}",
        headers=_headers(), json=body, timeout=15,
    )
    resp.raise_for_status()


def _google_complete(task: Task) -> None:
    if not task.external_id:
        return
    body = {"status": "completed"}
    httpx.patch(
        f"{GOOGLE_BASE}/lists/{GOOGLE_TASKLIST}/tasks/{task.external_id}",
        headers=_headers(), json=body, timeout=15,
    ).raise_for_status()


def _google_delete(task: Task) -> None:
    if not task.external_id:
        return
    httpx.delete(
        f"{GOOGLE_BASE}/lists/{GOOGLE_TASKLIST}/tasks/{task.external_id}",
        headers=_headers(), timeout=15,
    ).raise_for_status()


def _google_get_updated(external_id: str) -> str | None:
    resp = httpx.get(
        f"{GOOGLE_BASE}/lists/{GOOGLE_TASKLIST}/tasks/{external_id}",
        headers=_headers(), timeout=15,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data.get("updated")



# ── Dispatch helpers ─────────────────────────────────────────────────────────

def _remote_create(task: Task) -> str:
    return _google_create(task)

def _remote_update(task: Task) -> None:
    _google_update(task)

def _remote_complete(task: Task) -> None:
    _google_complete(task)

def _remote_delete(task: Task) -> None:
    _google_delete(task)

def _remote_get_updated(task: Task) -> str | None:
    return _google_get_updated(task.external_id or "")


# ── Public API ───────────────────────────────────────────────────────────────

def mirror_create(task_id: int) -> None:
    """Push a new task to the remote provider. Background thread."""
    threading.Thread(target=_do_create, args=(task_id,), daemon=True).start()


def mirror_update(task_id: int) -> None:
    threading.Thread(target=_do_update, args=(task_id,), daemon=True).start()


def mirror_complete(task_id: int) -> None:
    threading.Thread(target=_do_complete, args=(task_id,), daemon=True).start()


def mirror_delete(task_id: int) -> None:
    threading.Thread(target=_do_delete, args=(task_id,), daemon=True).start()


def check_drift_on_startup() -> None:
    """Compare remote updated timestamps for all open mirrored tasks."""
    threading.Thread(target=_do_drift_check, daemon=True).start()


def retry_pending() -> None:
    """Drain the mirror_pending queue. Call periodically or after reconnect."""
    threading.Thread(target=_do_retry_pending, daemon=True).start()


def _do_create(task_id: int) -> None:
    global _pending_count
    with _sync_lock:
        db = get_db()
        task = db.get_task(task_id)
        if not task:
            return
        try:
            ext_id = _remote_create(task)
            db.set_external(task_id, "google", ext_id, None, mirror_pending=False)
            _pending_count = max(0, _pending_count - 1)
            logger.info(f"Mirrored task {task_id} → google id={ext_id}")
        except Exception as e:
            logger.warning(f"Mirror create failed for task {task_id}: {e}")
            db.set_mirror_pending(task_id, True)
            _pending_count += 1


def _do_update(task_id: int) -> None:
    with _sync_lock:
        db = get_db()
        task = db.get_task(task_id)
        if not task or not task.external_id:
            return
        try:
            _remote_update(task)
            logger.info(f"Updated remote task for local {task_id}")
        except Exception as e:
            logger.warning(f"Mirror update failed for task {task_id}: {e}")
            db.set_mirror_pending(task_id, True)


def _do_complete(task_id: int) -> None:
    with _sync_lock:
        db = get_db()
        task = db.get_task(task_id)
        if not task or not task.external_id:
            return
        try:
            _remote_complete(task)
            logger.info(f"Completed remote task for local {task_id}")
        except Exception as e:
            logger.warning(f"Mirror complete failed for task {task_id}: {e}")


def _do_delete(task_id: int) -> None:
    with _sync_lock:
        db = get_db()
        task = db.get_task(task_id)
        if not task or not task.external_id:
            return
        try:
            _remote_delete(task)
            logger.info(f"Deleted remote task for local {task_id}")
        except Exception as e:
            logger.warning(f"Mirror delete failed for task {task_id}: {e}")


def _do_drift_check() -> None:
    with _sync_lock:
        try:
            db = get_db()
            tasks = db.list_mirrored_open_tasks()
            for task in tasks:
                if not task.external_id:
                    continue
                try:
                    remote_updated = _remote_get_updated(task)
                    if remote_updated is None:
                        # Remote task was deleted — mark drift
                        db.set_mirror_drift(task.id, True)
                    elif task.external_updated_at and task.external_updated_at != "!drift":
                        has_drift = remote_updated != task.external_updated_at
                        db.set_mirror_drift(task.id, has_drift)
                    else:
                        # Store the remote updated timestamp baseline
                        db.set_external(
                            task.id, task.external_provider, task.external_id,
                            remote_updated, mirror_pending=False
                        )
                except Exception as e:
                    logger.debug(f"Drift check failed for task {task.id}: {e}")
        except Exception:
            logger.exception("Drift check sweep failed")


def _do_retry_pending() -> None:
    global _pending_count
    with _sync_lock:
        db = get_db()
        pending = db.list_pending_mirror_tasks()
        for task in pending:
            try:
                if task.external_id:
                    _remote_update(task)
                else:
                    ext_id = _remote_create(task)
                    db.set_external(task.id, "google", ext_id, None, mirror_pending=False)
                db.set_mirror_pending(task.id, False)
                _pending_count = max(0, _pending_count - 1)
                logger.info(f"Retried mirror for task {task.id}")
            except Exception as e:
                logger.warning(f"Retry failed for task {task.id}: {e}")
        _pending_count = db.list_pending_mirror_tasks().__len__()


def _to_rfc3339(dt_str: str) -> str:
    """Convert 'YYYY-MM-DDTHH:MM:SS' or 'YYYY-MM-DD' to RFC3339 UTC string."""
    if "T" not in dt_str:
        dt_str = dt_str + "T00:00:00"
    if not dt_str.endswith("Z") and "+" not in dt_str:
        dt_str += "Z"
    return dt_str
