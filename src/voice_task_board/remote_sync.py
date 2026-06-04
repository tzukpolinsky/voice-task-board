from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any
import time

import httpx

from voice_task_board.config import get_config
from voice_task_board.db import get_db, Task
from voice_task_board.oauth import refresh_google_token, OAuthError


logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()
_throttle_lock = threading.Lock()
_last_call_time = 0.0  # Module-level throttle for Google API calls
_throttle_min_interval = 0.5  # Minimum 0.5s between calls (2/sec)

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


def _throttle_before_api_call() -> None:
    """Ensure at least 0.5s between any two Google API calls, with exponential backoff on 429."""
    global _last_call_time
    with _throttle_lock:
        now = time.time()
        elapsed = now - _last_call_time
        if elapsed < _throttle_min_interval:
            sleep_time = _throttle_min_interval - elapsed
            time.sleep(sleep_time)
        _last_call_time = time.time()


def _make_api_call_with_backoff(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Make an HTTP call with exponential backoff on 429 errors."""
    backoff_times = [0.5, 1.0, 2.0, 4.0]
    
    for attempt, backoff in enumerate(backoff_times):
        _throttle_before_api_call()
        
        try:
            if method == "GET":
                resp = httpx.get(url, **kwargs)
            elif method == "POST":
                resp = httpx.post(url, **kwargs)
            elif method == "PATCH":
                resp = httpx.patch(url, **kwargs)
            elif method == "DELETE":
                resp = httpx.delete(url, **kwargs)
            else:
                raise ValueError(f"Unknown method {method}")
            
            if resp.status_code == 429:
                if attempt < len(backoff_times) - 1:
                    logger.warning(f"Rate limited (429), backing off {backoff}s")
                    time.sleep(backoff)
                    continue
            
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < len(backoff_times) - 1:
                logger.warning(f"Rate limited (429), backing off {backoff}s")
                time.sleep(backoff)
                continue
            raise
    
    # If we get here, we've exhausted retries
    resp.raise_for_status()
    return resp


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


# ── Occurrence-level mirroring ─────────────────────────────────────────────

def _google_create_occurrence(task: Task, occurrence_due: str) -> str:
    """Create a Google Task for an occurrence."""
    body: dict[str, Any] = {"title": task.title, "notes": task.description or ""}
    # Use the occurrence's due date
    if occurrence_due:
        if task.is_full_day:
            body["due"] = f"{occurrence_due[:10]}T00:00:00.000Z"
        else:
            body["due"] = _to_rfc3339(occurrence_due)
    resp = _make_api_call_with_backoff(
        "POST",
        f"{GOOGLE_BASE}/lists/{GOOGLE_TASKLIST}/tasks",
        headers=_headers(), json=body, timeout=15,
    )
    data: dict[str, Any] = resp.json()
    return data["id"]


def _google_delete_occurrence(external_id: str) -> None:
    """Delete a Google Task for an occurrence by its external_id."""
    try:
        _make_api_call_with_backoff(
            "DELETE",
            f"{GOOGLE_BASE}/lists/{GOOGLE_TASKLIST}/tasks/{external_id}",
            headers=_headers(), timeout=15,
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            # Already deleted on Google, that's fine
            logger.debug(f"Google occurrence {external_id} already deleted (404)")
        else:
            raise


def push_occurrence(occ_id: int) -> None:
    """Push a single occurrence to Google Tasks. Background thread, called from materialize."""
    threading.Thread(target=_do_push_occurrence, args=(occ_id,), daemon=True).start()


def _do_push_occurrence(occ_id: int) -> None:
    """Internal: actually push the occurrence to Google."""
    with _sync_lock:
        db = get_db()
        # Load the occurrence directly - we need a method to get it by ID
        # For now, load all and find it
        cursor = db._conn.cursor()
        cursor.execute(
            """SELECT id, task_id, due_at_utc, fired, is_done, external_id, mirror_pending, created_at
               FROM occurrences WHERE id = ?""",
            (occ_id,),
        )
        row = cursor.fetchone()
        if not row:
            return
        
        from voice_task_board.db import Occurrence
        occ = Occurrence(
            id=row[0], task_id=row[1], due_at_utc=row[2], fired=row[3],
            is_done=row[4], external_id=row[5], mirror_pending=row[6], created_at=row[7]
        )
        
        task = db.get_task(occ.task_id)
        if not task or not task.mirror_to_remote:
            return
        
        try:
            ext_id = _google_create_occurrence(task, occ.due_at_utc)
            db.set_occurrence_external(occ.id, ext_id, mirror_pending=0)
            logger.info(f"Pushed occurrence {occ.id} → google id={ext_id}")
        except Exception as e:
            logger.warning(f"Failed to push occurrence {occ.id}: {e}")
            db.set_occurrence_external(occ.id, None, mirror_pending=1)


def delete_occurrence_external(external_id: str) -> None:
    """Delete a Google Task for an occurrence. Throttled delete."""
    threading.Thread(target=_do_delete_occurrence_external, args=(external_id,), daemon=True).start()


def _do_delete_occurrence_external(external_id: str) -> None:
    """Internal: delete the Google occurrence."""
    try:
        _google_delete_occurrence(external_id)
        logger.info(f"Deleted google occurrence {external_id}")
    except Exception as e:
        logger.warning(f"Failed to delete google occurrence {external_id}: {e}")


def push_occurrences_for_task(task_id: int, done_callback: callable | None = None) -> None:
    """Push all unpushed occurrences for a task. Background thread."""
    threading.Thread(target=_do_push_occurrences_for_task, args=(task_id, done_callback), daemon=True).start()


def _do_push_occurrences_for_task(task_id: int, done_callback: callable | None = None) -> None:
    """Internal: push all unpushed occurrences for a task."""
    with _sync_lock:
        db = get_db()
        task = db.get_task(task_id)
        if not task or not task.mirror_to_remote:
            if done_callback:
                done_callback()
            return
        
        unpushed = db.list_unpushed_occurrences(task_id)
        count = 0
        
        for occ in unpushed:
            try:
                ext_id = _google_create_occurrence(task, occ.due_at_utc)
                db.set_occurrence_external(occ.id, ext_id, mirror_pending=0)
                count += 1
                logger.info(f"Pushed occurrence {occ.id} → google id={ext_id}")
            except Exception as e:
                logger.warning(f"Failed to push occurrence {occ.id}: {e}")
                db.set_occurrence_external(occ.id, None, mirror_pending=1)
    
    if done_callback:
        done_callback()


def _to_rfc3339(dt_str: str) -> str:
    """Convert 'YYYY-MM-DDTHH:MM:SS' or 'YYYY-MM-DD' to RFC3339 UTC string."""
    if "T" not in dt_str:
        dt_str = dt_str + "T00:00:00"
    if not dt_str.endswith("Z") and "+" not in dt_str:
        dt_str += "Z"
    return dt_str
