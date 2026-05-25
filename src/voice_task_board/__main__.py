from __future__ import annotations

import logging
import sys
import threading
from typing import Any

from voice_task_board.hotkey import HotkeyListener
from voice_task_board.tray import create_tray_icon
from voice_task_board.logging_setup import configure_logging
from voice_task_board.audio import record_while_held
from voice_task_board.config import get_config
from voice_task_board.gemini import GeminiBackend
from voice_task_board.apply_intent import apply, ApplyResult
from voice_task_board.db import get_db
from voice_task_board import webview_app
from voice_task_board import scheduler as sched
from voice_task_board import notifications as notif
from voice_task_board import remote_sync
from voice_task_board.archive import run_archive_sweep


logger = logging.getLogger(__name__)

_hotkey_listener: HotkeyListener | None = None
_tray_icon: Any = None
_gemini_backend: GeminiBackend | None = None
_recording_lock = threading.Lock()
_recording_active = False


def _get_hotkey_listener() -> HotkeyListener | None:
    return _hotkey_listener


def _format_due(intent_due: str | None, is_full_day: bool) -> str | None:
    if not intent_due:
        return None
    if is_full_day:
        return intent_due[:10]
    return intent_due[:16].replace("T", " ")


def main() -> int:
    global _hotkey_listener, _tray_icon, _gemini_backend

    configure_logging()
    logger.info("Starting Voice Task Board")

    db = get_db()
    config = get_config()

    tasks = db.list_tasks()
    logger.info(f"Loaded {len(tasks)} existing tasks")

    if config.gemini_api_key:
        try:
            _gemini_backend = GeminiBackend(config.gemini_api_key)
            logger.info("Gemini backend initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Gemini backend: {e}")

    # Wire reminder callback
    def _on_reminder(task: Any) -> None:
        notif.show_reminder(task)

    notif.set_snooze_callback(sched.snooze)
    sched.set_notify_callback(_on_reminder)
    sched.start()

    # Run archive sweep and drift check in background on startup
    run_archive_sweep()
    if config.remote_provider and config.remote_tokens:
        remote_sync.check_drift_on_startup()
        remote_sync.retry_pending()

    def on_hotkey_pressed() -> None:
        global _recording_active
        with _recording_lock:
            if _recording_active:
                return
            _recording_active = True

        def record_in_background() -> None:
            global _recording_active
            try:
                logger.debug("record_in_background started")
                if not config.gemini_api_key:
                    logger.error("Gemini API key not set")
                    if _tray_icon:
                        _tray_icon.notify("Set your Gemini API key in Settings")
                    return

                logger.info("Recording started")
                listener = _hotkey_listener
                if listener is None:
                    raise RuntimeError("Hotkey listener not initialized")
                pcm_bytes = record_while_held(listener.is_key_held)
                logger.debug(f"record_while_held returned {len(pcm_bytes)} bytes")

                if not pcm_bytes:
                    logger.info("No speech detected")
                    return

                duration_seconds = len(pcm_bytes) / (16000 * 2)
                logger.info(f"Recording complete: {duration_seconds:.1f}s")

                logger.info("Extracting intent from Gemini")
                if not _gemini_backend:
                    raise RuntimeError("Gemini backend not initialized")
                category_names = db.get_category_names()
                intent = _gemini_backend.extract_intent(pcm_bytes, category_names)
                logger.info(f"Intent: {intent}")

                if intent.action == "add" and intent.mirror_to_remote and config.remote_provider:
                    # Only confirm when the task will be mirrored to a remote list —
                    # local-only tasks add silently to avoid disrupting the user.
                    due_label = _format_due(intent.due_at, intent.is_full_day)
                    action = notif.show_confirmation_toast(
                        title=intent.title,
                        due=due_label,
                        category=intent.category,
                    )

                    if action == "cancel":
                        if _tray_icon:
                            _tray_icon.notify("Task discarded")
                        return

                    if action == "edit":
                        # Hand off to the in-window editor; this opens the board.
                        edit_action = webview_app.show_confirmation(
                            title=intent.title,
                            due=due_label,
                            category=intent.category,
                            mirror=intent.mirror_to_remote,
                        )
                        if edit_action == "cancel":
                            if _tray_icon:
                                _tray_icon.notify("Task discarded")
                            return

                logger.info("Applying intent to database")
                result, task_id = apply(intent, _gemini_backend)
                logger.info(f"Apply result: {result}")

                if result == ApplyResult.CREATED and task_id:
                    # Fire mirror if flagged
                    if intent.mirror_to_remote and config.remote_provider:
                        remote_sync.mirror_create(task_id)
                    msg = f"✓ Added: {intent.title}"
                    if intent.due_at:
                        msg += f" ({_format_due(intent.due_at, intent.is_full_day)})"
                elif result == ApplyResult.DELETED:
                    msg = "✓ Deleted task"
                elif result == ApplyResult.EDITED:
                    msg = "✓ Edited task"
                elif result == ApplyResult.NO_MATCH:
                    msg = "✗ No matching task"
                else:
                    msg = "? Could not understand"

                if _tray_icon:
                    _tray_icon.notify(msg)

            except ValueError as e:
                logger.info(f"Input error: {e}")
            except Exception as e:
                logger.exception(f"Recording/intent/apply failed: {e}")
                if _tray_icon:
                    _tray_icon.notify(f"Error: {str(e)[:50]}")
            finally:
                with _recording_lock:
                    _recording_active = False

        thread = threading.Thread(target=record_in_background, daemon=True)
        thread.start()

    _hotkey_listener = HotkeyListener(config.hotkey, on_hotkey_pressed)
    webview_app.set_hotkey_listener(_hotkey_listener)
    _hotkey_listener.start()

    def run_tray() -> None:
        global _tray_icon
        try:
            _tray_icon = create_tray_icon()
            _tray_icon.run()
        except Exception as e:
            logger.exception(f"Tray error: {e}")

    tray_thread = threading.Thread(target=run_tray, name="tray", daemon=False)
    tray_thread.start()

    try:
        window = webview_app.create_window()
        webview_app.start()
    except Exception as e:
        logger.exception(f"WebView error: {e}")
    finally:
        sched.stop()
        if _hotkey_listener:
            _hotkey_listener.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
