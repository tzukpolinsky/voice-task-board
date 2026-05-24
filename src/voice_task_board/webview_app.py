from __future__ import annotations

import httpx
import logging
import sys
from pathlib import Path
from typing import Any

import webview

from voice_task_board.db import get_db, Task
from voice_task_board.config import get_config
from voice_task_board.gemini import GeminiBackend


logger = logging.getLogger(__name__)


class Api:
    def get_tasks(self) -> list[dict]:
        db = get_db()
        tasks = db.list_tasks()
        return [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "category_id": t.category_id,
                "category_name": t.category_name,
                "status": t.status,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
            }
            for t in tasks
        ]

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
        db.delete_task(task_id)

    def create_task(self, title: str, category_id: int, description: str = "") -> int:
        db = get_db()
        return db.create_task(title, category_id, description)

    def update_task(self, task_id: int, title: str | None = None, description: str | None = None) -> bool:
        db = get_db()
        return db.update_task(task_id, title=title, description=description)

    def get_config(self) -> dict[str, Any]:
        config = get_config()
        return {
            "gemini_api_key": config.gemini_api_key,
            "hotkey": config.hotkey,
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


def set_hotkey_listener(listener: Any) -> None:
    global _hotkey_listener
    _hotkey_listener = listener


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
        
        def on_window_close() -> None:
            """Hide window instead of destroying it, so user can reopen from tray."""
            if _window:
                _window.hide()
        
        _window.events.closed += on_window_close
        logger.info("Webview window created")
        return _window
    except Exception as e:
        logger.exception(f"Failed to create webview window: {e}")
        raise


def get_window() -> webview.Window | None:
    return _window


def show_window() -> None:
    global _window
    if _window is None:
        return
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
