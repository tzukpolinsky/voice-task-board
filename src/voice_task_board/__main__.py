from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any

# Workaround for a WebView2 GPU/compositor race that surfaces as a native
# AccessViolationException through the pywebview/pythonnet marshalling layer
# and hard-crashes the process (taking the tray, hotkey listener, and scheduler
# with it). See MicrosoftEdge/WebView2Feedback#5479. Re-test on WebView2 updates.
# Override by setting WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS in the environment.
os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-gpu")

from voice_task_board.hotkey import HotkeyListener
from voice_task_board.tray import create_tray_icon
from voice_task_board.logging_setup import configure_logging
from voice_task_board.audio import record_while_held, validate_audio_device
from voice_task_board.config import get_config
from voice_task_board.gemini import GeminiBackend, BillingError
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

    # Validate cached audio device; clear if it's disconnected
    validate_audio_device()

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
                    notif.show_status("Set your Gemini API key in Settings")
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
                        notif.show_status("Task discarded")
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
                            notif.show_status("Task discarded")
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
                    if task_id and config.remote_provider:
                        task = db.get_task(task_id)
                        if task and task.mirror_to_remote:
                            if task.external_id:
                                remote_sync.mirror_update(task_id)
                            else:
                                remote_sync.mirror_create(task_id)
                elif result == ApplyResult.NO_MATCH:
                    msg = "✗ No matching task"
                else:
                    msg = "? Could not understand"

                if result in (ApplyResult.CREATED, ApplyResult.DELETED, ApplyResult.EDITED):
                    webview_app.notify_data_changed()

                notif.show_status(msg)

            except ValueError as e:
                logger.info(f"Input error: {e}")
            except BillingError as e:
                logger.error(f"Gemini billing/quota error: {e}")
                notif.show_billing_error(e.user_message, e.url)
            except Exception as e:
                logger.exception(f"Recording/intent/apply failed: {e}")
                # Check if it's a device error during recording
                if "input device" in str(e).lower() or "portaudio" in str(e).lower():
                    notif.show_status("Microphone disconnected — please reconnect and try again")
                else:
                    notif.show_status(f"Error: {str(e)[:50]}")
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

    # Daemon so that once main() returns, the process exits even if the tray
    # icon's blocking run() loop is still running. Previously this was
    # daemon=False, which combined with webview.start()'s blocking native loop
    # made the process unkillable from Python — sched.stop() / hotkey.stop()
    # in the finally block could never actually terminate.
    tray_thread = threading.Thread(target=run_tray, name="tray", daemon=True)
    tray_thread.start()

    _install_ctrl_c_handler()

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


# Keep refs so the OS-held callback objects aren't GC'd, which would dangle a
# pointer inside SetConsoleCtrlHandler and crash on Ctrl+C.
_ctrl_handler_ref: Any = None
_shutdown_in_progress = threading.Lock()


def force_shutdown(reason: str = "shutdown") -> None:
    """Single forceful shutdown path used by tray Quit and Ctrl+C.

    Best-effort clean teardown of the scheduler, hotkey listener, and webview
    window, followed by an unconditional os._exit(0). We cannot rely on the
    main thread ever returning from webview.start() — window.destroy() is
    known to hang under load on WebView2, and Python's default SIGINT handler
    can't deliver to a main thread stuck in a native call. os._exit terminates
    the process at the OS level, which:

      - tears down WebView2 / pythonnet / pycaw COM state via process exit,
      - kills the audio device handle even mid-recording,
      - lets the OS reclaim file handles, sockets, and the SQLite WAL safely.

    Safe to call from any thread, including the Win32 Ctrl handler thread or
    the pystray tray thread. Idempotent — the first caller wins.
    """
    if not _shutdown_in_progress.acquire(blocking=False):
        # Another caller is already tearing the process down; just block here
        # until they call os._exit.
        import time as _time
        _time.sleep(5)
        os._exit(0)
        return

    logger.info(f"Force shutdown: {reason}")
    try:
        sched.stop()
    except Exception:
        pass
    try:
        if _hotkey_listener is not None:
            _hotkey_listener.stop()
    except Exception:
        pass
    try:
        if _tray_icon is not None:
            _tray_icon.stop()
    except Exception:
        pass
    try:
        window = webview_app.get_window()
        if window is not None:
            window.destroy()
    except Exception:
        pass
    # Give the above a brief moment for any in-flight work to finish, then nuke.
    try:
        import time as _time
        _time.sleep(0.2)
    except Exception:
        pass
    os._exit(0)


def _install_ctrl_c_handler() -> None:
    """Install a native Win32 console Ctrl+C handler.

    Python's signal.SIGINT handler only fires between bytecode instructions on
    the main thread. Since the main thread blocks inside webview.start()'s
    native message loop, SIGINT is queued forever and Ctrl+C in the terminal
    does nothing. Win32 console control handlers run on a separate OS-managed
    thread, so they fire regardless of what the main thread is doing.

    In a frozen --noconsole build there is no console attached, so
    SetConsoleCtrlHandler returns 0 (we log at debug) and the handler is
    simply never invoked — no leak, no extra cost. We still keep the function
    pointer alive in `_ctrl_handler_ref` because the OS may hold a reference
    to it for the process lifetime; that's a constant-size module global, not
    a leak.
    """
    global _ctrl_handler_ref
    try:
        import ctypes
        from ctypes import wintypes

        HANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        CTRL_C_EVENT = 0
        CTRL_BREAK_EVENT = 1
        CTRL_CLOSE_EVENT = 2

        def _handler(ctrl_type: int) -> bool:
            if ctrl_type not in (CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT):
                return False
            force_shutdown(reason=f"ctrl event {ctrl_type}")
            return True  # unreachable, but keeps type checker happy

        _ctrl_handler_ref = HANDLER_ROUTINE(_handler)
        ok = ctypes.windll.kernel32.SetConsoleCtrlHandler(_ctrl_handler_ref, True)
        if not ok:
            logger.debug("SetConsoleCtrlHandler returned 0 (no console attached?)")
    except Exception as e:
        logger.debug(f"Could not install Ctrl+C handler: {e!r}")


if __name__ == "__main__":
    raise SystemExit(main())
