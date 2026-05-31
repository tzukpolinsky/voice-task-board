from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from voice_task_board.db import Task


logger = logging.getLogger(__name__)

_AUMID = "VoiceTaskBoard"
_APP_NAME = "Voice Task Board"


def _ensure_aumid_shortcut() -> None:
    """Create a Start-Menu shortcut tagged with our AUMID so Windows will
    actually deliver InteractableWindowsToaster toasts.

    Without a shortcut whose System.AppUserModel.ID matches our AUMID, Windows
    silently drops toasts (no exception). The installer creates this shortcut,
    but when running from source/dev we have to register one ourselves.
    Idempotent: skipped if shortcut already exists with the correct AUMID.
    """
    try:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return
        start_menu = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        start_menu.mkdir(parents=True, exist_ok=True)
        shortcut_path = start_menu / f"{_APP_NAME}.lnk"

        import pythoncom  # type: ignore
        from win32com.client import Dispatch  # type: ignore
        from win32com.propsys import propsys, pscon  # type: ignore

        if not shortcut_path.exists():
            shell = Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(str(shortcut_path))
            shortcut.TargetPath = sys.executable
            shortcut.WorkingDirectory = str(Path(sys.executable).parent)
            shortcut.IconLocation = sys.executable
            shortcut.Save()
            logger.info(f"Created Start-Menu shortcut at {shortcut_path}")

        # GPS_READWRITE = 2. Provide a PyPROPVARIANT object with VT_LPWSTR.
        store = propsys.SHGetPropertyStoreFromParsingName(
            str(shortcut_path), None, 2, propsys.IID_IPropertyStore
        )
        pv = propsys.PROPVARIANTType(_AUMID, pythoncom.VT_LPWSTR)
        store.SetValue(pscon.PKEY_AppUserModel_ID, pv)
        store.Commit()
        logger.info(f"Tagged shortcut with AUMID={_AUMID}")
    except Exception as e:
        logger.warning(f"Could not register AUMID shortcut (toasts may not appear): {e}")

_snooze_callback: Callable[[int], None] | None = None

# The toaster and any in-flight toasts must outlive show_toast() — WinRT
# delivers toasts asynchronously and will silently drop them if the Python
# objects are garbage-collected before the OS picks them up.
_toaster: Any = None
_toaster_init_failed: bool = False
_live_toasts: list[Any] = []
_live_toasts_lock = threading.Lock()


def set_snooze_callback(fn: Callable[[int], None]) -> None:
    global _snooze_callback
    _snooze_callback = fn


def _get_toaster() -> Any:
    global _toaster, _toaster_init_failed
    if _toaster is not None or _toaster_init_failed:
        return _toaster
    try:
        _ensure_aumid_shortcut()
        from windows_toasts import InteractableWindowsToaster
        _toaster = InteractableWindowsToaster(applicationText=_APP_NAME, notifierAUMID=_AUMID)
    except Exception as e:
        logger.warning(f"windows-toasts unavailable: {e}")
        _toaster_init_failed = True
    return _toaster


def _retain_toast(toast: Any) -> None:
    with _live_toasts_lock:
        _live_toasts.append(toast)


def _release_toast(toast: Any) -> None:
    with _live_toasts_lock:
        try:
            _live_toasts.remove(toast)
        except ValueError:
            pass


def _format_due_label(task: Task) -> str:
    if not task.due_at_utc:
        return ""
    if task.is_full_day:
        return f" — due {task.due_at_utc[:10]}"
    try:
        from datetime import datetime, timezone
        utc_str = task.due_at_utc if task.due_at_utc.endswith("Z") else task.due_at_utc + "Z"
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        tz: Any = None
        if task.due_tz:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(task.due_tz)
            except Exception as e:
                logger.debug(f"ZoneInfo({task.due_tz}) failed: {e}; falling back to system local")
        local_dt = dt.astimezone(tz) if tz else dt.astimezone()
        return f" — due at {local_dt.strftime('%H:%M')}"
    except Exception:
        logger.exception("Failed to format due label")
        return ""


def show_reminder(task: Task) -> None:
    """Show a Windows toast notification for a due task. Non-blocking."""
    threading.Thread(target=_show_reminder, args=(task,), daemon=True).start()


def _show_reminder(task: Task) -> None:
    from windows_toasts import Toast, ToastButton, ToastDuration

    due_label = _format_due_label(task)
    body = f"{task.title}{due_label}"
    if task.category_name and task.category_name.lower() != "default":
        body += f"\n[{task.category_name}]"

    toaster = _get_toaster()
    if toaster is None:
        return

    toast = Toast(text_fields=["Reminder", body])
    toast.duration = ToastDuration.Long
    # Body-click activation on Win32 requires a registered NotificationActivator
    # COM CLSID on the AUMID shortcut, which we don't ship. Buttons route
    # through the in-process Activated event regardless, so "Open" is a button.
    toast.AddAction(ToastButton(content="Open", arguments="open"))
    toast.AddAction(ToastButton(content="Snooze 10m", arguments="snooze"))

    dismissEvent = threading.Event()

    def _on_activated(event: Any) -> None:
        args = (getattr(event, "arguments", "") or "")
        try:
            if args == "snooze" and _snooze_callback:
                _snooze_callback(task.id)
            elif args == "open":
                from voice_task_board import webview_app
                webview_app.show_window()
        except Exception as e:
            logger.warning(f"Toast activation handler failed: {e}")
        finally:
            _release_toast(toast)
            dismissEvent.set()

    def _on_dismissed(_: Any) -> None:
        _release_toast(toast)
        dismissEvent.set()

    def _on_failed(_e: Any) -> None:
        _release_toast(toast)
        dismissEvent.set()

    toast.on_activated = _on_activated
    toast.on_dismissed = _on_dismissed
    toast.on_failed = _on_failed

    _retain_toast(toast)
    try:
        toaster.show_toast(toast)
        logger.info(f"Showed reminder toast for task {task.id}: {task.title}")
        dismissEvent.wait()  # Keep thread alive until the toast is dismissed or activated
    except Exception as e:
        _release_toast(toast)
        logger.warning(f"Could not show reminder toast: {e}")


def show_status(message: str) -> None:
    """Show a brief status toast (e.g. "✓ Added: ...") with an Open button
    that brings the dashboard to the foreground. Non-blocking.

    Replaces pystray's notify() so the user can jump from the notification
    into the app. Falls back to the tray balloon if windows-toasts is
    unavailable.
    """
    threading.Thread(target=_show_status, args=(message,), daemon=True).start()


def _show_status(message: str) -> None:
    from windows_toasts import Toast, ToastButton, ToastDuration

    toaster = _get_toaster()
    if toaster is None:
        return

    toast = Toast(text_fields=[_APP_NAME, message])
    toast.duration = ToastDuration.Short
    toast.AddAction(ToastButton(content="Open", arguments="open"))

    dismissEvent = threading.Event()

    def _on_activated(event: Any) -> None:
        args = (getattr(event, "arguments", "") or "")
        try:
            if args == "open":
                from voice_task_board import webview_app
                webview_app.show_window()
        except Exception as e:
            logger.warning(f"Status toast activation handler failed: {e}")
        finally:
            _release_toast(toast)
            dismissEvent.set()

    def _on_dismissed(_: Any) -> None:
        _release_toast(toast)
        dismissEvent.set()

    def _on_failed(_e: Any) -> None:
        _release_toast(toast)
        dismissEvent.set()

    toast.on_activated = _on_activated
    toast.on_dismissed = _on_dismissed
    toast.on_failed = _on_failed

    _retain_toast(toast)
    try:
        toaster.show_toast(toast)
        dismissEvent.wait()
    except Exception as e:
        _release_toast(toast)
        logger.warning(f"Could not show status toast: {e}")


def show_confirmation_toast(
    title: str,
    due: str | None,
    category: str,
    timeout: int = 15,
) -> str:
    """Show approve/edit/cancel toast for a new mirrored task. Blocks until click or timeout.

    Returns one of 'accept', 'edit', 'cancel', 'timeout'.
    """
    from windows_toasts import Toast, ToastButton, ToastDuration

    toaster = _get_toaster()
    if toaster is None:
        return "accept"

    body_parts = [title]
    if due:
        body_parts.append(f"Due {due}")
    if category and category.lower() != "default":
        body_parts.append(f"[{category}]")
    body = " · ".join(body_parts)

    event = threading.Event()
    result: dict[str, str] = {"action": "timeout"}

    toast = Toast(text_fields=["New task — will sync to your remote list", body])
    toast.duration = ToastDuration.Long
    toast.AddAction(ToastButton(content="Approve", arguments="accept"))
    toast.AddAction(ToastButton(content="Edit", arguments="edit"))
    toast.AddAction(ToastButton(content="Cancel", arguments="cancel"))

    def _on_activated(e: Any) -> None:
        result["action"] = (getattr(e, "arguments", "") or "accept")
        event.set()

    def _on_dismissed(_: Any) -> None:
        if not event.is_set():
            # Dismissed without explicit click — match prior behavior: apply task
            result["action"] = "accept"
            event.set()

    toast.on_activated = _on_activated
    toast.on_dismissed = _on_dismissed

    try:
        toaster.show_toast(toast)
    except Exception as e:
        logger.warning(f"Could not show confirmation toast: {e}")
        return "accept"

    triggered = event.wait(timeout=timeout)
    if not triggered:
        return "timeout"
    return result["action"]
