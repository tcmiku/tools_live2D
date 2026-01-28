from __future__ import annotations


def build_hotkey_hint(settings: dict) -> str:
    toggle = str(settings.get("hotkey_toggle_pet", "Ctrl+Shift+L"))
    note = str(settings.get("hotkey_note", "Ctrl+Shift+P"))
    pomodoro = str(settings.get("hotkey_pomodoro", "Ctrl+Shift+T"))
    edit = str(settings.get("hotkey_model_edit", "Ctrl+Shift+M"))
    launcher = str(settings.get("hotkey_launcher_panel", "Ctrl+Shift+Space"))
    chat_toggle = str(settings.get("hotkey_chat_toggle", "Ctrl+H"))
    rows = [
        (toggle, "显示/隐藏宠物"),
        (note, "快速便签"),
        (pomodoro, "番茄钟开关"),
        (edit, "模型编辑模式"),
        (launcher, "快速启动面板"),
        (chat_toggle, "显示/隐藏聊天框"),
    ]
    max_key = max(len(item[0]) for item in rows)
    lines = [f"{key.ljust(max_key)}    {label}" for key, label in rows]
    return "\n".join(lines)
