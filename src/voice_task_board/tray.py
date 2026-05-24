from __future__ import annotations

import logging

import pystray

from voice_task_board.icon import get_icon_image


logger = logging.getLogger(__name__)


def create_tray_icon() -> pystray.Icon:
    icon = pystray.Icon("voice_task_board", get_icon_image(), "Voice Task Board")

    def on_open(_: pystray.Icon, __: pystray.MenuItem) -> None:
        from voice_task_board import webview_app
        try:
            webview_app.show_window()
        except Exception as e:
            logger.error(f"Failed to open window: {e}")

    def on_quit(selected_icon: pystray.Icon, __: pystray.MenuItem) -> None:
        from voice_task_board import webview_app
        window = webview_app.get_window()
        if window:
            window.destroy()
        selected_icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem("Open", on_open, default=True),
        pystray.MenuItem("Quit", on_quit),
    )
    return icon
