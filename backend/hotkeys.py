from __future__ import annotations

import ctypes
import logging
import re
from typing import Tuple

from PySide6.QtCore import QAbstractNativeEventFilter


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008


def parse_hotkey(text: str) -> Tuple[int, int] | None:
    if not text:
        return None
    parts = [p.strip() for p in re.split(r"\s*\+\s*", text) if p.strip()]
    if not parts:
        return None

    modifiers = 0
    key = None
    for part in parts:
        upper = part.upper()
        if upper in ("CTRL", "CONTROL"):
            modifiers |= MOD_CONTROL
        elif upper == "SHIFT":
            modifiers |= MOD_SHIFT
        elif upper == "ALT":
            modifiers |= MOD_ALT
        elif upper in ("WIN", "META"):
            modifiers |= MOD_WIN
        else:
            if len(upper) == 1 and "A" <= upper <= "Z":
                key = ord(upper)
            elif len(upper) == 1 and "0" <= upper <= "9":
                key = ord(upper)
            elif upper.startswith("F") and upper[1:].isdigit():
                num = int(upper[1:])
                if 1 <= num <= 12:
                    key = 0x70 + (num - 1)
            else:
                logging.warning("unsupported hotkey token: %s", part)
                return None
    if key is None or modifiers == 0:
        return None
    return modifiers, key


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, handlers: dict[int, callable]) -> None:
        super().__init__()
        self._handlers = handlers

    def nativeEventFilter(self, event_type, message):
        if event_type != "windows_generic_MSG":
            return False, 0
        msg = ctypes.wintypes.MSG.from_address(int(message))
        if msg.message == 0x0312:  # WM_HOTKEY
            handler = self._handlers.get(int(msg.wParam))
            if handler:
                handler()
                return True, 0
        return False, 0


class HotkeyManager:
    def __init__(self) -> None:
        self._registered: list[int] = []

    def register(self, hotkey_id: int, modifiers: int, key: int) -> bool:
        if ctypes.windll.user32.RegisterHotKey(None, hotkey_id, modifiers, key):
            self._registered.append(hotkey_id)
            return True
        return False

    def unregister_all(self) -> None:
        for hotkey_id in self._registered:
            ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)
        self._registered.clear()
