from __future__ import annotations

import logging
import threading
import os
import time
import zipfile
from typing import Dict, Optional

from PySide6.QtCore import QObject, Signal, Slot, QPoint

from focus import FocusState
from ai_client import AIClient
from settings import AppSettings
from clipboard import ClipboardHistory
from notes import NoteStore
from sysinfo import SystemInfo
from pomodoro import PomodoroEngine
from reminders import ReminderStore, ReminderEngine, ReminderConfig


class BackendBridge(QObject):
    stateUpdated = Signal(dict)
    aiReply = Signal(str)
    settingsUpdated = Signal(dict)
    clipboardUpdated = Signal(list)
    systemInfoUpdated = Signal(dict)
    noteUpdated = Signal(str)
    pomodoroUpdated = Signal(dict)
    remindersUpdated = Signal(dict)
    todosUpdated = Signal(list)
    passiveMessage = Signal(str)
    userMessage = Signal(str)
    aiTestResult = Signal(dict)
    favorUpdated = Signal(int)
    openPanel = Signal(str)
    backupCompleted = Signal(str)
    restoreCompleted = Signal(str)
    requestBackupDialog = Signal()

    def __init__(
        self,
        ai_client: AIClient,
        settings: AppSettings | None = None,
        pomodoro: PomodoroEngine | None = None,
        reminders: ReminderEngine | None = None,
        reminder_store: ReminderStore | None = None,
    ) -> None:
        super().__init__()
        self._ai_client = ai_client
        self._window = None
        self._settings = settings or AppSettings()
        self._drag_last: QPoint | None = None
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self._clipboard = ClipboardHistory(os.path.join(base_dir, "data", "clipboard.json"))
        self._notes = NoteStore(os.path.join(base_dir, "data", "note.txt"))
        self._sysinfo = SystemInfo()
        self._pomodoro = pomodoro
        self._reminders = reminders
        self._reminder_store = reminder_store
        self._open_ai_dialog = None
        self._last_state: Dict[str, object] = {
            "status": "idle",
            "idle_ms": 0,
            "focus_seconds_today": 0,
        }

    def push_state(self, state: FocusState, extra: dict | None = None) -> None:
        payload = {
            "status": state.status,
            "idle_ms": state.idle_ms,
            "focus_seconds_today": state.focus_seconds_today,
        }
        if extra:
            payload.update(extra)
        self._last_state = payload
        self.stateUpdated.emit(payload)

    def push_passive_message(self, text: str) -> None:
        if text:
            self.passiveMessage.emit(text)

    @Slot(result=dict)
    def getInitialState(self) -> dict:
        return self._last_state

    @Slot(str)
    def sendUserMessage(self, text: str) -> None:
        message = text.strip()
        if not message:
            return
        self.userMessage.emit(message)

        def _worker() -> None:
            try:
                reply = self._ai_client.call(message, int(self._last_state.get("focus_seconds_today", 0)))
                self.aiReply.emit(reply)
            except Exception as exc:
                logging.exception("ai worker failed: %s", exc)
                self.aiReply.emit("抱歉，处理消息时出现问题。")

        threading.Thread(target=_worker, daemon=True).start()

    def set_window(self, window) -> None:
        self._window = window

    def set_open_ai_dialog(self, handler) -> None:
        self._open_ai_dialog = handler

    @Slot(bool)
    def setWindowDragEnabled(self, enabled: bool) -> None:
        if self._window:
            self._window.set_drag_enabled(enabled)

    @Slot(float, float)
    def startWindowDrag(self, x: float, y: float) -> None:
        if not self._window or self._window.is_locked():
            return
        self._drag_last = QPoint(int(x), int(y))

    @Slot(float, float)
    def moveWindowDrag(self, x: float, y: float) -> None:
        if not self._window or self._drag_last is None or self._window.is_locked():
            return
        current = QPoint(int(x), int(y))
        delta = current - self._drag_last
        if delta.manhattanLength() == 0:
            return
        self._drag_last = current
        pos = self._window.pos() + delta
        self._window.move(pos)

    @Slot()
    def endWindowDrag(self) -> None:
        self._drag_last = None

    @Slot(result=dict)
    def getModelConfig(self) -> dict:
        return self._settings.get_model_config()

    @Slot(dict)
    def setModelConfig(self, config: dict) -> None:
        self._settings.set_model_config(config)
        logging.info("model config updated: %s", config)
        self.settingsUpdated.emit(self._settings.get_settings())

    @Slot(result=dict)
    def getSettings(self) -> dict:
        settings = self._settings.get_settings()
        logging.info("bridge getSettings: model_scale=%s", settings.get("model_scale"))
        return settings

    @Slot(dict)
    def setSettings(self, values: dict) -> None:
        self._settings.set_settings(values)
        current = self._settings.get_settings()
        logging.info("settings updated: %s", current)
        self.settingsUpdated.emit(current)
        if self._reminders:
            self._reminders.set_config(ReminderConfig.from_settings(current))

    @Slot(result=list)
    def getClipboardHistory(self) -> list:
        return self._clipboard.get_items()

    @Slot(str)
    def setClipboardText(self, text: str) -> None:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(text)

    @Slot()
    def clearClipboard(self) -> None:
        self._clipboard.clear()
        self.clipboardUpdated.emit(self._clipboard.get_items())

    @Slot(result=str)
    def getNote(self) -> str:
        return self._notes.load()

    @Slot(str)
    def setNote(self, text: str) -> None:
        self._notes.save(text)
        self.noteUpdated.emit(text)

    def poll_clipboard(self, text: str) -> None:
        if self._clipboard.add_text(text):
            self.clipboardUpdated.emit(self._clipboard.get_items())

    def poll_system_info(self) -> None:
        self.systemInfoUpdated.emit(self._sysinfo.snapshot())

    def poll_pomodoro(self) -> dict | None:
        if not self._pomodoro:
            return None
        state = self._pomodoro.update()
        payload = {
            "mode": state.mode,
            "remaining_sec": state.remaining_sec,
            "focus_min": state.focus_min,
            "break_min": state.break_min,
            "count_today": state.count_today,
        }
        self.pomodoroUpdated.emit(payload)
        return payload

    @Slot()
    def startPomodoro(self) -> None:
        if self._pomodoro:
            self._pomodoro.start()

    @Slot()
    def pausePomodoro(self) -> None:
        if self._pomodoro:
            self._pomodoro.pause()

    @Slot()
    def stopPomodoro(self) -> None:
        if self._pomodoro:
            self._pomodoro.stop()

    @Slot(int, int)
    def setPomodoroDurations(self, focus_min: int, break_min: int) -> None:
        if not self._pomodoro:
            return
        self._pomodoro.set_durations(focus_min, break_min)
        current = self._settings.get_settings()
        current["pomodoro_focus_min"] = int(focus_min)
        current["pomodoro_break_min"] = int(break_min)
        self._settings.set_settings(current)
        self.settingsUpdated.emit(self._settings.get_settings())

    @Slot(result=dict)
    def getReminderSettings(self) -> dict:
        return self._settings.get_settings()

    @Slot(dict)
    def setReminderSettings(self, values: dict) -> None:
        self._settings.set_settings(values)
        current = self._settings.get_settings()
        if self._reminders:
            self._reminders.set_config(ReminderConfig.from_settings(current))
        self.remindersUpdated.emit(current)

    @Slot(result=dict)
    def getAISettings(self) -> dict:
        data = self._settings.get_settings()
        providers = data.get("ai_providers", [])
        if isinstance(providers, list) and providers:
            first = providers[0]
            return {
                "ai_provider": first.get("name", "OpenAI兼容"),
                "ai_base_url": first.get("base_url", "https://api.openai.com/v1"),
                "ai_model": first.get("model", "gpt-4o-mini"),
                "ai_api_key": first.get("api_key", ""),
            }
        return {
            "ai_provider": data.get("ai_provider", "OpenAI兼容"),
            "ai_base_url": data.get("ai_base_url", "https://api.openai.com/v1"),
            "ai_model": data.get("ai_model", "gpt-4o-mini"),
            "ai_api_key": data.get("ai_api_key", ""),
        }

    @Slot(result=int)
    def getFavor(self) -> int:
        data = self._settings.get_settings()
        return int(data.get("favor", 50))

    @Slot(float)
    def addFavor(self, delta: float) -> None:
        data = self._settings.get_settings()
        current = int(data.get("favor", 50))
        try:
            new_value = current + int(round(float(delta)))
        except (TypeError, ValueError):
            new_value = current
        new_value = max(0, min(100, new_value))
        self._settings.set_settings({"favor": new_value})
        self.favorUpdated.emit(new_value)

    @Slot(dict)
    def setAISettings(self, values: dict) -> None:
        if "ai_providers" in values:
            self._settings.set_settings(values)
        else:
            current = self._settings.get_settings()
            providers = current.get("ai_providers", [])
            first = {
                "name": values.get("ai_provider", "OpenAI兼容"),
                "base_url": values.get("ai_base_url", "https://api.openai.com/v1"),
                "model": values.get("ai_model", "gpt-4o-mini"),
                "api_key": values.get("ai_api_key", ""),
                "enabled": True,
            }
            if isinstance(providers, list) and providers:
                providers[0] = first
            else:
                providers = [first]
            values["ai_providers"] = providers
            self._settings.set_settings(values)
        current = self._settings.get_settings()
        self.settingsUpdated.emit(current)
        logging.info("ai settings updated: provider=%s model=%s", current.get("ai_provider"), current.get("ai_model"))

    @Slot()
    def openAIDetailDialog(self) -> None:
        if self._open_ai_dialog:
            self._open_ai_dialog()

    @Slot()
    def togglePetWindow(self) -> None:
        if not self._window:
            return
        if self._window.isVisible():
            self._window.hide()
        else:
            self._window.show()

    @Slot(str)
    def createBackup(self, target_path: str = "") -> None:
        if not self._window:
            return
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        data_dir = os.path.join(base_dir, "data")
        try:
            os.makedirs(data_dir, exist_ok=True)
            if target_path:
                path = target_path
            else:
                timestamp = time.strftime("%Y%m%d")
                name = f"backup_{timestamp}.zip"
                path = os.path.join(data_dir, name)
            files = ["settings.json", "stats.json", "pomodoro.json", "clipboard.json", "note.txt"]
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for filename in files:
                    full = os.path.join(data_dir, filename)
                    if os.path.exists(full):
                        zf.write(full, filename)
            self.backupCompleted.emit(path)
        except Exception as exc:
            logging.exception("backup failed: %s", exc)
            self.backupCompleted.emit("")

    @Slot(str)
    def restoreBackup(self, path: str) -> None:
        if not path:
            return
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        data_dir = os.path.join(base_dir, "data")
        try:
            os.makedirs(data_dir, exist_ok=True)
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(data_dir)
            self.restoreCompleted.emit(path)
        except Exception as exc:
            logging.exception("restore failed: %s", exc)
            self.restoreCompleted.emit("")

    @Slot()
    def openBackupDialog(self) -> None:
        self.requestBackupDialog.emit()

    def requestOpenPanel(self, name: str) -> None:
        if name:
            self.openPanel.emit(name)

    @Slot()
    def testAIConnection(self) -> None:
        def _worker() -> None:
            try:
                ok, message = self._ai_client.test_connection()
                self.aiTestResult.emit({"ok": ok, "message": message})
            except Exception as exc:
                logging.exception("ai test worker failed: %s", exc)
                self.aiTestResult.emit({"ok": False, "message": "测试失败，请稍后再试。"})

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(result=list)
    def getTodos(self) -> list:
        if not self._reminder_store:
            return []
        return self._reminder_store.list_todos()

    @Slot(str, float)
    def addTodo(self, title: str, due_ts: float) -> None:
        if not self._reminder_store:
            return
        item = self._reminder_store.add_todo(title, due_ts)
        self.todosUpdated.emit(self._reminder_store.list_todos())
        logging.info("todo added: %s", item)

    @Slot(int)
    def removeTodo(self, todo_id: int) -> None:
        if not self._reminder_store:
            return
        self._reminder_store.remove_todo(todo_id)
        self.todosUpdated.emit(self._reminder_store.list_todos())
