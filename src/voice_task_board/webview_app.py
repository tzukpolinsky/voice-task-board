from __future__ import annotations

import httpx
import logging
import queue
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import webview

from voice_task_board.db import get_db, Task
from voice_task_board.config import get_config
from voice_task_board.gemini import GeminiBackend
from voice_task_board import remote_sync, archive as archive_mod


logger = logging.getLogger(__name__)


def _task_to_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "title": t.title,
        "description": t.description,
        "category_id": t.category_id,
        "category_name": t.category_name,
        "status": t.status,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
        "due_at_utc": t.due_at_utc,
        "due_tz": t.due_tz,
        "is_full_day": t.is_full_day,
        "lead_time_minutes": t.lead_time_minutes,
        "recurrence_rule": t.recurrence_rule,
        "mirror_to_remote": t.mirror_to_remote,
        "external_provider": t.external_provider,
        "external_id": t.external_id,
        "mirror_pending": t.mirror_pending,
        "has_drift": t.external_updated_at == "!drift",
        "reminder_fired": t.reminder_fired,
    }


class Api:
    def get_tasks(self, include_done: bool = False) -> list[dict]:
        db = get_db()
        tasks = db.list_tasks(include_done=include_done)
        return [_task_to_dict(t) for t in tasks]

    def get_categories(self) -> list[dict[str, int | str]]:
        db = get_db()
        return db.list_categories()

    def add_category(self, name: str) -> int:
        db = get_db()
        return db.add_category(name)

    def delete_category(self, category_id: int) -> None:
        db = get_db()
        if category_id == 1:
            raise ValueError("Cannot delete the default category")
        db.delete_category(category_id)

    def move_task(self, task_id: int, category_id: int) -> None:
        db = get_db()
        db.move_task(task_id, category_id)

    def delete_task(self, task_id: int) -> None:
        db = get_db()
        task = db.get_task(task_id)
        if task and task.external_id:
            remote_sync.mirror_delete(task_id)
        db.delete_task(task_id)

    def complete_task(self, task_id: int) -> None:
        db = get_db()
        task = db.get_task(task_id)
        if task and task.external_id:
            remote_sync.mirror_complete(task_id)
        db.complete_task(task_id)

    def create_task(
        self,
        title: str,
        category_id: int,
        description: str = "",
        due_at_utc: str | None = None,
        due_tz: str | None = None,
        is_full_day: bool = False,
        lead_time_minutes: int = 30,
        recurrence_rule: str | None = None,
        mirror_to_remote: bool = False,
    ) -> int:
        db = get_db()
        task_id = db.create_task(
            title, category_id, description,
            due_at_utc=due_at_utc, due_tz=due_tz,
            is_full_day=is_full_day, lead_time_minutes=lead_time_minutes,
            recurrence_rule=recurrence_rule, mirror_to_remote=mirror_to_remote,
        )
        if mirror_to_remote:
            remote_sync.mirror_create(task_id)
        return task_id

    def update_task(self, task_id: int, title: str | None = None, description: str | None = None) -> bool:
        db = get_db()
        updated = db.update_task(task_id, title=title, description=description)
        if updated:
            task = db.get_task(task_id)
            if task and task.external_id:
                remote_sync.mirror_update(task_id)
        return updated

    def update_task_due(
        self,
        task_id: int,
        due_at_utc: str | None,
        due_tz: str | None,
        is_full_day: bool,
        lead_time_minutes: int,
        recurrence_rule: str | None = None,
    ) -> None:
        db = get_db()
        db.update_task_due(task_id, due_at_utc, due_tz, is_full_day, lead_time_minutes, recurrence_rule)
        task = db.get_task(task_id)
        if task and task.external_id:
            remote_sync.mirror_update(task_id)

    def set_mirror(self, task_id: int, mirror: bool) -> None:
        """Toggle mirroring for an existing task."""
        db = get_db()
        task = db.get_task(task_id)
        if not task:
            return
        if mirror and not task.external_id:
            db.set_mirror_toggle(task_id, True)
            remote_sync.mirror_create(task_id)
        elif not mirror and task.external_id:
            remote_sync.mirror_delete(task_id)
            db.set_mirror_toggle(task_id, False)

    def get_pending_mirror_count(self) -> int:
        return remote_sync.pending_count()

    def get_archived_tasks(self, category_name: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        return archive_mod.list_archived(category_name=category_name, limit=limit, offset=offset)

    def get_config(self) -> dict[str, Any]:
        config = get_config()
        return {
            "gemini_api_key": config.gemini_api_key,
            "hotkey": config.hotkey,
            "remote_provider": config.remote_provider,
            "connect_banner_dismissed": config.connect_banner_dismissed,
        }

    def save_config(self, gemini_api_key: str | None = None, hotkey: str | None = None) -> None:
        config = get_config()
        if gemini_api_key is not None:
            config.gemini_api_key = gemini_api_key
        if hotkey is not None:
            config.hotkey = hotkey
        config._save()

        if hotkey is not None and _hotkey_listener:
            _hotkey_listener.rebind(hotkey)

        logger.info("Config saved")

    def dismiss_connect_banner(self) -> None:
        config = get_config()
        config.connect_banner_dismissed = True
        config._save()

    def connect_remote_provider(self, provider: str) -> dict[str, Any]:
        """Start Google OAuth flow. Blocks until complete or fails."""
        from voice_task_board import oauth
        try:
            tokens = oauth.start_google_oauth()
            config = get_config()
            config.remote_provider = "google"
            config.remote_tokens = tokens
            config.connect_banner_dismissed = True
            config._save()
            remote_sync.retry_pending()
            remote_sync.check_drift_on_startup()
            return {"ok": True}
        except Exception as e:
            logger.error(f"Google OAuth failed: {e}")
            return {"ok": False, "error": str(e)}

    def disconnect_remote_provider(self) -> None:
        config = get_config()
        config.remote_provider = None
        config.remote_tokens = {}
        config._save()

    def submit_confirmation(self, action: str) -> None:
        """Called from JS when user responds to the task confirmation overlay."""
        global _confirmation_result, _confirmation_event
        _confirmation_result = action
        if _confirmation_event:
            _confirmation_event.set()

    def test_gemini_key(self, api_key: str) -> bool:
        try:
            response = httpx.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": api_key},
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            model_ids = [m.get("name", "").split("/")[-1] for m in models]
            
            if GeminiBackend._model is None:
                GeminiBackend._model = GeminiBackend._pick_best_model(model_ids)
                if not GeminiBackend._model:
                    GeminiBackend._model = "gemini-2.0-flash"
                GeminiBackend._endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{GeminiBackend._model}:generateContent"
            
            return True
        except Exception as e:
            logger.info(f"API key test failed: {e}")
            return False
    
    def open_url(self, url: str) -> None:
        """Open a URL in the user's default browser."""
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.error(f"Failed to open URL {url}: {e}")


_window: webview.Window | None = None
_hotkey_listener: Any = None
_confirmation_event: Any = None   # threading.Event, set by submit_confirmation
_confirmation_result: str = "accept"  # 'accept' | 'edit' | 'cancel'


# --- UI dispatcher --------------------------------------------------------
# Concurrent calls into pywebview from multiple background threads (recording
# thread, tray thread, scheduler thread) have surfaced as native access
# violations in the pythonnet/WebView2 marshalling layer — see the comment at
# the top of __main__.py. Routing every cross-thread WebView interaction
# (_window.evaluate_js, _window.show/hide, ctypes window calls) through a
# single worker thread serializes those calls and removes the multi-thread
# concurrency that triggers the race. The worker itself is still not the
# WebView2 UI thread (pywebview owns that), but pywebview marshals correctly
# from one consistent foreign thread; what it cannot tolerate is N foreign
# threads racing simultaneously.

_ui_queue: "queue.Queue[Callable[[], None] | None]" = queue.Queue()
_ui_worker_thread: threading.Thread | None = None
_ui_worker_lock = threading.Lock()


def _ui_worker_loop() -> None:
    while True:
        fn = _ui_queue.get()
        if fn is None:
            return
        try:
            fn()
        except Exception:
            logger.exception("UI worker task raised")


def _ensure_ui_worker() -> None:
    global _ui_worker_thread
    with _ui_worker_lock:
        if _ui_worker_thread is not None and _ui_worker_thread.is_alive():
            return
        _ui_worker_thread = threading.Thread(
            target=_ui_worker_loop, name="vtb-ui-worker", daemon=True
        )
        _ui_worker_thread.start()


def _post_to_ui(fn: Callable[[], None]) -> None:
    """Fire-and-forget: run fn on the UI worker thread."""
    _ensure_ui_worker()
    _ui_queue.put(fn)


def _run_on_ui_sync(fn: Callable[[], Any], timeout: float = 10.0) -> Any:
    """Run fn on the UI worker thread and wait for it to finish (or timeout).

    Returns the function's return value, or None on timeout / exception.
    """
    _ensure_ui_worker()
    done = threading.Event()
    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["result"] = fn()
        except Exception as e:
            box["error"] = e
        finally:
            done.set()

    _ui_queue.put(runner)
    if not done.wait(timeout=timeout):
        logger.warning("UI sync call timed out")
        return None
    if "error" in box:
        logger.warning(f"UI sync call raised: {box['error']!r}")
        return None
    return box.get("result")
# --- end UI dispatcher ----------------------------------------------------


def set_hotkey_listener(listener: Any) -> None:
    global _hotkey_listener
    _hotkey_listener = listener


def show_confirmation(title: str, due: str | None, category: str, mirror: bool, timeout: int = 10) -> str:
    """Show a confirmation overlay in the board window. Returns 'accept', 'edit', or 'cancel'.

    The wait for the user's response stays on the caller's thread; only the
    show + evaluate_js dispatch runs on the UI worker.
    """
    import json as _json

    global _confirmation_event, _confirmation_result
    _confirmation_event = threading.Event()
    _confirmation_result = "accept"

    if _window:
        payload = _json.dumps({
            "title": title,
            "due": due,
            "category": category,
            "mirror": mirror,
            "timeout": timeout,
        })

        def _dispatch() -> None:
            show_window()
            try:
                _window.evaluate_js(f"window.__vtbShowConfirmation({payload})")
            except Exception as e:
                logger.warning(f"Could not inject confirmation overlay: {e}")

        _post_to_ui(_dispatch)

    triggered = _confirmation_event.wait(timeout=timeout + 1)
    _confirmation_event = None
    if not triggered:
        return "accept"
    return _confirmation_result


def _resolve_frontend_path() -> str:
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parents[2]
    
    html_path = base_path / "frontend" / "dist" / "index.html"
    if not html_path.exists():
        logger.error(f"Frontend not found at {html_path}")
        raise FileNotFoundError(f"Frontend not found at {html_path}")
    
    return f"file:///{html_path}".replace("\\", "/")


def create_window() -> webview.Window:
    global _window
    
    try:
        frontend_url = _resolve_frontend_path()
        _window = webview.create_window(
            "Voice Task Board",
            frontend_url,
            js_api=Api(),
            width=1000,
            height=600,
            background_color="#f5f5f5",
            hidden=True,
        )
        
        def on_window_closing() -> bool:
            """Cancel destruction and hide instead, so the tray stays alive."""
            if _window:
                _window.hide()
            return False

        _window.events.closing += on_window_closing
        logger.info("Webview window created")
        return _window
    except Exception as e:
        logger.exception(f"Failed to create webview window: {e}")
        raise


def get_window() -> webview.Window | None:
    return _window


def notify_data_changed() -> None:
    """Signal the frontend to reload its data. Routed via the UI worker."""
    if _window is None:
        return

    def _dispatch() -> None:
        try:
            _window.evaluate_js("window.__vtbDataChanged && window.__vtbDataChanged()")
        except Exception as e:
            logger.debug(f"Could not notify frontend of data change: {e}")

    _post_to_ui(_dispatch)


def hide_window() -> None:
    if _window is None:
        return

    def _dispatch() -> None:
        try:
            _window.hide()
        except Exception as e:
            logger.debug(f"Failed to hide window: {e}")

    _post_to_ui(_dispatch)


def show_window() -> None:
    """Show the board window and bring it to the foreground.

    Internal callers already on the UI worker (e.g. show_confirmation's
    dispatch closure) call this directly; external callers from background
    threads (tray click handler, etc.) route through _post_to_ui so the
    actual _window.show() / ctypes calls always run on the UI worker.
    """
    if _window is None:
        return

    if threading.current_thread() is _ui_worker_thread:
        _show_window_impl()
    else:
        _post_to_ui(_show_window_impl)


def _show_window_impl() -> None:
    try:
        _window.show()
        _apply_window_icon()
        _bring_to_front()
    except Exception as e:
        logger.error(f"Failed to show window (may be destroyed): {e}")


def _apply_window_icon() -> None:
    """Set the same icon used in the tray for the webview window (title bar + taskbar)."""
    try:
        import ctypes
        from voice_task_board.icon import get_icon_ico_path

        title = _window.title if _window else "Voice Task Board"
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if not hwnd:
            return

        ico_path = str(get_icon_ico_path())
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        LR_DEFAULTSIZE = 0x00000040
        WM_SETICON = 0x80
        ICON_SMALL = 0
        ICON_BIG = 1

        for size, slot in ((16, ICON_SMALL), (32, ICON_BIG)):
            hicon = ctypes.windll.user32.LoadImageW(
                0, ico_path, IMAGE_ICON, size, size, LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            if hicon:
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, slot, hicon)
    except Exception as e:
        logger.debug(f"Could not apply window icon: {e}")


def _bring_to_front() -> None:
    """Make the window the foreground window after show()."""
    try:
        import ctypes

        title = _window.title if _window else "Voice Task Board"
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if not hwnd:
            return
        SW_RESTORE = 9
        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception as e:
        logger.debug(f"Could not bring window to front: {e}")


def start() -> None:
    global _window
    if _window is None:
        _window = create_window()
    if _window:
        webview.start()
