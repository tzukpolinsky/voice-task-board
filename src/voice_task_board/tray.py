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
        # Route through the shared forceful-shutdown path so prod users
        # (clicking tray Quit) get the same os._exit(0) termination as
        # Ctrl+C in dev. window.destroy() + icon.stop() alone would leave
        # the process alive if WebView2 hangs on destroy — which has
        # happened — and would leak the audio device, pycaw COM pointers,
        # and the WebView2 background process.
        from voice_task_board.__main__ import force_shutdown
        force_shutdown(reason="tray quit")

    icon.menu = pystray.Menu(
        pystray.MenuItem("Open", on_open, default=True),
        pystray.MenuItem("Quit", on_quit),
    )
    return icon
