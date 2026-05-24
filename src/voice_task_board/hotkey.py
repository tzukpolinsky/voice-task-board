from __future__ import annotations

import logging
import threading
from typing import Callable, Final

import win32api
import win32con
import win32gui


logger = logging.getLogger(__name__)
HOTKEY_ID: Final[int] = 1
_CLASS_NAME: Final[str] = "VoiceTaskBoardHotkeyWindow"
_COMBO_MESSAGE: Final[int] = win32con.WM_APP + 1

_MOD_MAP = {"ctrl": win32con.MOD_CONTROL, "shift": win32con.MOD_SHIFT, "alt": win32con.MOD_ALT, "win": win32con.MOD_WIN}
_KEY_MAP = {
    "space": 0x20,
    "enter": win32con.VK_RETURN,
    "tab": win32con.VK_TAB,
    "escape": win32con.VK_ESCAPE,
}
for i in range(10):
    _KEY_MAP[str(i)] = 0x30 + i
for i in range(26):
    _KEY_MAP[chr(ord("a") + i)] = 0x41 + i
for i in range(1, 13):
    _KEY_MAP[f"f{i}"] = 0x70 + i - 1


def _parse_combo(combo_str: str) -> tuple[int, int]:
    parts = combo_str.lower().split("+")
    mods = 0
    vk = 0
    for part in parts:
        part = part.strip()
        if part in _MOD_MAP:
            mods |= _MOD_MAP[part]
        elif part in _KEY_MAP:
            vk = _KEY_MAP[part]
        else:
            raise ValueError(f"Unknown hotkey component: {part}")
    if vk == 0:
        raise ValueError("Hotkey must have a key")
    return mods, vk


class HotkeyListener:
    def __init__(self, combo: str, callback: Callable[[], None]) -> None:
        self._combo = combo
        self._callback = callback
        self._mods, self._vk = _parse_combo(combo)
        self._thread = threading.Thread(target=self._run, name="hotkey-listener", daemon=True)
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._hwnd: int | None = None
        self._thread_id: int | None = None

    def start(self) -> None:
        self._thread.start()
        self._ready.wait()

    @property
    def vk(self) -> int:
        return self._vk

    def is_key_held(self) -> bool:
        """Return True if the hotkey's main key is currently physically pressed."""
        return bool(win32api.GetAsyncKeyState(self._vk) & 0x8000)

    def rebind(self, new_combo: str) -> None:
        logger.info(f"Rebinding hotkey from {self._combo} to {new_combo}")
        self._combo = new_combo
        try:
            mods, vk = _parse_combo(new_combo)
        except ValueError as e:
            logger.error(f"Invalid hotkey combo: {e}")
            return
        if self._thread_id is not None:
            win32api.PostThreadMessage(self._thread_id, _COMBO_MESSAGE, mods, vk)

    def stop(self) -> None:
        self._stop_requested.set()
        if self._thread_id is not None:
            win32api.PostThreadMessage(self._thread_id, win32con.WM_QUIT, 0, 0)
        self._thread.join()

    def _run(self) -> None:
        self._thread_id = win32api.GetCurrentThreadId()
        class_atom = self._register_window_class()
        self._hwnd = win32gui.CreateWindow(
            class_atom,
            _CLASS_NAME,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            None,
        )
        win32gui.RegisterHotKey(self._hwnd, HOTKEY_ID, self._mods, self._vk)
        self._ready.set()
        try:
            win32gui.PumpMessages()
        finally:
            if self._hwnd is not None:
                try:
                    win32gui.UnregisterHotKey(self._hwnd, HOTKEY_ID)
                except win32gui.error:
                    pass
                try:
                    win32gui.DestroyWindow(self._hwnd)
                except win32gui.error:
                    pass

    def _register_window_class(self) -> int:
        wndclass = win32gui.WNDCLASS()
        wndclass.lpszClassName = _CLASS_NAME
        wndclass.lpfnWndProc = {
            win32con.WM_HOTKEY: self._on_hotkey,
            _COMBO_MESSAGE: self._on_rebind_message,
        }
        try:
            return int(win32gui.RegisterClass(wndclass))
        except win32gui.error as error:
            if error.winerror != win32con.ERROR_CLASS_ALREADY_EXISTS:
                raise
            class_info = win32gui.GetClassInfo(0, _CLASS_NAME)
            return int(class_info[0])

    def _on_hotkey(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if not self._stop_requested.is_set() and wparam == HOTKEY_ID:
            self._callback()
        return 0

    def _on_rebind_message(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        try:
            win32gui.UnregisterHotKey(self._hwnd, HOTKEY_ID)
            win32gui.RegisterHotKey(self._hwnd, HOTKEY_ID, wparam, lparam)
            self._mods = wparam
            self._vk = lparam
            logger.info("Hotkey rebound successfully")
        except Exception as e:
            logger.exception(f"Failed to rebind hotkey: {e}")
        return 0