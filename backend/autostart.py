from __future__ import annotations

import os
import sys
from typing import Tuple


def _build_command(base_dir: str) -> str:
    if getattr(sys, "frozen", False):
        return f"\"{sys.executable}\""
    script_path = os.path.abspath(sys.argv[0])
    if script_path.lower().endswith(".py"):
        return f"\"{sys.executable}\" \"{script_path}\""
    fallback = os.path.join(base_dir, "backend", "main.py")
    return f"\"{sys.executable}\" \"{fallback}\""


def set_autostart(enabled: bool, app_name: str, base_dir: str) -> Tuple[bool, str]:
    if not sys.platform.startswith("win"):
        return False, "当前平台不支持开机自启"
    try:
        import winreg
    except Exception:
        return False, "无法加载 Windows 注册表模块"

    command = _build_command(base_dir)
    key_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
        return True, ""
    except Exception as exc:
        return False, f"设置开机自启失败: {exc}"
