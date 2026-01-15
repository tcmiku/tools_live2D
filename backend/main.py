from __future__ import annotations

import logging
import os
import sys
import time
import random
import ctypes
from datetime import date

from PySide6.QtCore import QTimer, Qt, QUrl, QPoint, QProcess
from PySide6.QtGui import QIcon, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QSystemTrayIcon,
    QMessageBox,
    QStyle,
    QDialog,
    QFormLayout,
    QSpinBox,
    QDoubleSpinBox,
    QDialogButtonBox,
    QCheckBox,
    QLineEdit,
    QTableWidget,
    QHeaderView,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QFileDialog,
    QLabel,
    QWidget,
    QGroupBox,
)
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from focus import FocusEngine, adjust_state_for_pomodoro
from stats import FocusStats
from ai_client import AIClient
from bridge import BackendBridge
from model_bindings import ModelBindingManager
from settings import AppSettings
from pomodoro import PomodoroEngine, reward_for_focus_minutes
from achievements import build_daily_summary, build_weekly_summary
from mood import compute_mood, mood_bucket, mood_interval_factor
from hotkey_hints import build_hotkey_hint
from hotkeys import HotkeyManager, HotkeyFilter, parse_hotkey
from reminders import ReminderEngine, ReminderStore, ReminderConfig
from login_rewards import apply_daily_login
from passive_chat import PassiveChatEngine, PassiveChatConfig


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEB_DIR = os.path.join(BASE_DIR, "web")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
LOG_DIR = os.path.join(BASE_DIR, "data")
LOG_PATH = os.path.join(LOG_DIR, "app.log")


class Live2DPetWindow(QWebEngineView):
    def __init__(self, bridge: BackendBridge) -> None:
        super().__init__()
        self._drag_offset: QPoint | None = None
        self._drag_enabled = True
        self._locked = False

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.page().setBackgroundColor(Qt.transparent)
        self.page().settings().setAttribute(
            QWebEngineSettings.LocalContentCanAccessFileUrls, True
        )
        profile = self.page().profile()
        profile.setHttpCacheType(QWebEngineProfile.NoCache)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        profile.clearHttpCache()

        self.resize(300, 400)
        self._move_to_corner()

        self.channel = QWebChannel(self.page())
        self.channel.registerObject("backend", bridge)
        self.page().setWebChannel(self.channel)

        url = QUrl.fromLocalFile(os.path.join(WEB_DIR, "index.html"))
        self.load(url)

    def _move_to_corner(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        x = geo.right() - self.width() - 20
        y = geo.bottom() - self.height() - 40
        self.move(x, y)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._drag_enabled and not self._locked:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self.snap_to_edges()
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def snap_to_edges(self, margin: int = 20) -> None:
        if self._locked:
            return
        screen = self.screen() or QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        rect = self.frameGeometry()
        x = rect.x()
        y = rect.y()
        if abs(rect.left() - geo.left()) <= margin:
            x = geo.left()
        if abs(geo.right() - rect.right()) <= margin:
            x = geo.right() - rect.width() + 1
        if abs(rect.top() - geo.top()) <= margin:
            y = geo.top()
        if abs(geo.bottom() - rect.bottom()) <= margin:
            y = geo.bottom() - rect.height() + 1
        self.move(x, y)

    def set_drag_enabled(self, enabled: bool) -> None:
        self._drag_enabled = enabled

    def set_locked(self, locked: bool) -> None:
        self._locked = locked

    def toggle_lock(self) -> bool:
        self._locked = not self._locked
        return self._locked

    def is_locked(self) -> bool:
        return self._locked


class HotkeyHintWindow(QWidget):
    def __init__(self, parent_window: QWidget) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self._parent_window = parent_window
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        self.setWindowFlag(Qt.BypassWindowManagerHint, True)
        self.setWindowFlag(Qt.WindowTransparentForInput, True)

        self._label = QLabel()
        self._label.setText("")
        self._label.setStyleSheet(
            "QLabel {"
            " color: #e9edf2;"
            " background: rgba(20, 24, 32, 210);"
            " border: 1px solid rgba(255, 255, 255, 50);"
            " border-radius: 10px;"
            " padding: 10px 14px;"
            " font-size: 12px;"
            "}"
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self.setLayout(layout)

    def set_text(self, text: str) -> None:
        self._label.setText(text)
        self.adjustSize()

    def show_hint(self) -> None:
        parent_geo = self._parent_window.geometry()
        x = parent_geo.x() + 12
        y = max(12, parent_geo.y() - self.height() - 8)
        self.move(x, y)
        self.show()


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None, bridge=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._bridge = bridge
        self.setWindowTitle("个性化设置")
        self.setStyleSheet(
            "QDialog { background: #f7f7f5; }"
            "QLabel { color: #1f1f1f; font-size: 12px; }"
            "QSpinBox, QDoubleSpinBox {"
            "  background: #ffffff;"
            "  border: 1px solid #c9c9c9;"
            "  border-radius: 6px;"
            "  padding: 4px 6px;"
            "}"
            "QSpinBox::up-button, QSpinBox::down-button,"
            "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {"
            "  width: 12px;"
            "}"
            "QDialogButtonBox QPushButton {"
            "  background: #2f6fed;"
            "  color: white;"
            "  border: none;"
            "  border-radius: 6px;"
            "  padding: 6px 12px;"
            "}"
            "QDialogButtonBox QPushButton:default {"
            "  background: #2458c7;"
            "}"
            "QDialogButtonBox QPushButton:hover {"
            "  background: #1f4fb5;"
            "}"
        )

        form = QFormLayout(self)

        self.active_spin = QSpinBox()
        self.active_spin.setRange(1, 3600)
        self.active_spin.setSuffix(" 秒")

        self.sleep_spin = QSpinBox()
        self.sleep_spin.setRange(2, 7200)
        self.sleep_spin.setSuffix(" 秒")

        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setSuffix(" %")

        self.model_scale_spin = QDoubleSpinBox()
        self.model_scale_spin.setRange(0.1, 2.0)
        self.model_scale_spin.setSingleStep(0.05)

        self.ui_scale_spin = QDoubleSpinBox()
        self.ui_scale_spin.setRange(0.5, 2.0)
        self.ui_scale_spin.setSingleStep(0.05)

        self.anim_speed_spin = QDoubleSpinBox()
        self.anim_speed_spin.setRange(0.1, 2.0)
        self.anim_speed_spin.setSingleStep(0.1)

        self.hotkey_toggle = QLineEdit()
        self.hotkey_note = QLineEdit()
        self.hotkey_pomodoro = QLineEdit()
        self.hotkey_toggle.setPlaceholderText("Ctrl+Shift+L")
        self.hotkey_note.setPlaceholderText("Ctrl+Shift+P")
        self.hotkey_pomodoro.setPlaceholderText("Ctrl+Shift+T")

        self.model_edit_mode_btn = QPushButton("开启模型编辑模式")
        self.model_edit_mode_btn.setCheckable(True)
        self.model_edit_mode_btn.setStyleSheet(
            "QPushButton { background: #5cb85c; color: white; border: none; border-radius: 6px; padding: 6px 12px; }"
            "QPushButton:checked { background: #d9534f; }"
            "QPushButton:hover { background: #4cae4c; }"
            "QPushButton:checked:hover { background: #c9302c; }"
        )
        self.model_edit_mode_btn.toggled.connect(self._on_edit_mode_toggled)

        form.addRow("活跃判定阈值", self.active_spin)
        form.addRow("睡眠判定阈值", self.sleep_spin)
        form.addRow("窗口透明度", self.opacity_spin)
        form.addRow("模型缩放", self.model_scale_spin)
        form.addRow("界面缩放", self.ui_scale_spin)
        form.addRow("动画速度", self.anim_speed_spin)
        form.addRow("热键：显示/隐藏", self.hotkey_toggle)
        form.addRow("热键：快速便签", self.hotkey_note)
        form.addRow("热键：番茄钟", self.hotkey_pomodoro)
        form.addRow(self.model_edit_mode_btn)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)

        self.load_settings()

    def load_settings(self) -> None:
        data = self._settings.get_settings()
        self.active_spin.setValue(int(data["focus_active_ms"] / 1000))
        self.sleep_spin.setValue(int(data["focus_sleep_ms"] / 1000))
        self.opacity_spin.setValue(int(data["window_opacity"]))
        self.model_scale_spin.setValue(float(data["model_scale"]))
        self.ui_scale_spin.setValue(float(data["ui_scale"]))
        self.anim_speed_spin.setValue(float(data["animation_speed"]))
        self.hotkey_toggle.setText(str(data.get("hotkey_toggle_pet", "Ctrl+Shift+L")))
        self.hotkey_note.setText(str(data.get("hotkey_note", "Ctrl+Shift+P")))
        self.hotkey_pomodoro.setText(str(data.get("hotkey_pomodoro", "Ctrl+Shift+T")))
        edit_mode = bool(data.get("model_edit_mode", False))
        self.model_edit_mode_btn.setChecked(edit_mode)
        self.model_edit_mode_btn.setText("关闭模型编辑模式" if edit_mode else "开启模型编辑模式")

    def _on_edit_mode_toggled(self, checked: bool) -> None:
        self.model_edit_mode_btn.setText("关闭模型编辑模式" if checked else "开启模型编辑模式")
        if self._bridge and hasattr(self._bridge, 'setModelEditMode'):
            self._bridge.setModelEditMode(checked)

    def get_values(self) -> dict:
        return {
            "focus_active_ms": int(self.active_spin.value() * 1000),
            "focus_sleep_ms": int(self.sleep_spin.value() * 1000),
            "window_opacity": int(self.opacity_spin.value()),
            "model_scale": float(self.model_scale_spin.value()),
            "ui_scale": float(self.ui_scale_spin.value()),
            "animation_speed": float(self.anim_speed_spin.value()),
            "hotkey_toggle_pet": self.hotkey_toggle.text().strip(),
            "hotkey_note": self.hotkey_note.text().strip(),
            "hotkey_pomodoro": self.hotkey_pomodoro.text().strip(),
            "model_edit_mode": bool(self.model_edit_mode_btn.isChecked()),
        }


class AIProviderDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("AI 详细配置")
        self.setStyleSheet(
            "QDialog { background: #f7f7f5; }"
            "QLabel { color: #1f1f1f; font-size: 12px; }"
            "QLineEdit {"
            "  background: #ffffff;"
            "  border: 1px solid #c9c9c9;"
            "  border-radius: 6px;"
            "  padding: 4px 6px;"
            "}"
            "QTableWidget { background: #ffffff; border: 1px solid #c9c9c9; }"
            "QHeaderView::section { background: #ededed; padding: 4px; border: none; }"
            "QPushButton {"
            "  background: #2f6fed;"
            "  color: white;"
            "  border: none;"
            "  border-radius: 6px;"
            "  padding: 6px 12px;"
            "}"
            "QPushButton:hover { background: #1f4fb5; }"
        )

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["名称", "Base URL", "模型", "API Key", "启用"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        add_btn = QPushButton("新增")
        remove_btn = QPushButton("删除")
        add_btn.clicked.connect(self.add_row)
        remove_btn.clicked.connect(self.remove_selected)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(btn_layout)
        layout.addWidget(buttons)

        self.load_data()

    def add_row(self, data: dict | None = None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QLineEdit(str((data or {}).get("name", "OpenAI兼容")))
        base_url = QLineEdit(str((data or {}).get("base_url", "https://api.openai.com/v1")))
        model = QLineEdit(str((data or {}).get("model", "gpt-4o-mini")))
        api_key = QLineEdit(str((data or {}).get("api_key", "")))
        api_key.setEchoMode(QLineEdit.Password)
        enabled = QCheckBox()
        enabled.setChecked(bool((data or {}).get("enabled", True)))
        self.table.setCellWidget(row, 0, name)
        self.table.setCellWidget(row, 1, base_url)
        self.table.setCellWidget(row, 2, model)
        self.table.setCellWidget(row, 3, api_key)
        self.table.setCellWidget(row, 4, enabled)

    def remove_selected(self) -> None:
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def load_data(self) -> None:
        settings = self._settings.get_settings()
        providers = settings.get("ai_providers", [])
        if isinstance(providers, list) and providers:
            for item in providers:
                if isinstance(item, dict):
                    self.add_row(item)
        else:
            self.add_row({})

    def get_providers(self) -> list[dict]:
        providers = []
        for row in range(self.table.rowCount()):
            name = self.table.cellWidget(row, 0).text().strip()
            base_url = self.table.cellWidget(row, 1).text().strip()
            model = self.table.cellWidget(row, 2).text().strip()
            api_key = self.table.cellWidget(row, 3).text().strip()
            enabled = self.table.cellWidget(row, 4).isChecked()
            providers.append(
                {
                    "name": name or "OpenAI兼容",
                    "base_url": base_url or "https://api.openai.com/v1",
                    "model": model or "gpt-4o-mini",
                    "api_key": api_key,
                    "enabled": enabled,
                }
            )
        return providers


def main() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info("app start")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    stats = FocusStats()
    engine = FocusEngine(stats=stats)
    settings = AppSettings()
    ai_client = AIClient(settings)
    pomodoro = PomodoroEngine(os.path.join(BASE_DIR, "data", "pomodoro.json"))
    reminders = ReminderEngine(ReminderConfig.from_settings(settings.get_settings()))
    settings_data = settings.get_settings()
    passive_base_config = PassiveChatConfig(
        enabled=settings_data.get("passive_enabled", True),
        interval_min=settings_data.get("passive_interval_min", 30),
        random_enabled=settings_data.get("passive_random_enabled", True),
        blessing_enabled=settings_data.get("passive_blessing_enabled", True),
        focus_enabled=settings_data.get("passive_focus_enabled", True),
        focus_interval_min=settings_data.get("passive_focus_interval_min", 60),
    )
    passive_chat = PassiveChatEngine(passive_base_config)
    reminder_store = ReminderStore(os.path.join(BASE_DIR, "data", "reminders.json"))
    bindings_path = settings.get_settings().get("bindings_path", "data/model_bindings.json")
    if not os.path.isabs(bindings_path):
        bindings_path = os.path.join(BASE_DIR, bindings_path)
    binding_manager = ModelBindingManager(bindings_path)
    bridge = BackendBridge(
        ai_client,
        settings=settings,
        pomodoro=pomodoro,
        reminders=reminders,
        reminder_store=reminder_store,
        binding_manager=binding_manager,
    )

    tray_icon_path = os.path.join(ASSETS_DIR, "tray_icon.png")
    if os.path.exists(tray_icon_path):
        tray_icon = QIcon(tray_icon_path)
    else:
        tray_icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    tray = QSystemTrayIcon(tray_icon)
    tray.setToolTip("桌面桌宠")
    menu = QMenu()

    pause_action = menu.addAction("暂停统计")

    def toggle_pause() -> None:
        engine.set_paused(not engine.paused)
        pause_action.setText("继续统计" if engine.paused else "暂停统计")
        logging.info("tracking toggled paused=%s", engine.paused)

    pause_action.triggered.connect(toggle_pause)

    show_stats_action = menu.addAction("查看今日专注时间")

    def show_stats() -> None:
        try:
            focus_text = stats.format_today_focus()
            logging.info("show stats dialog: %s", focus_text)
            msg = QMessageBox(window)
            msg.setIcon(QMessageBox.Information)
            msg.setWindowTitle("今日专注")
            msg.setText(focus_text)
            msg.setStandardButtons(QMessageBox.Ok)
            msg.setStyleSheet(
                "QMessageBox { background-color: #1f1f1f; }"
                "QLabel { color: #f2f2f2; font-size: 13px; }"
                "QPushButton { min-width: 72px; padding: 4px 10px; }"
            )
            result = msg.exec()
            logging.info("show stats dialog closed: %s", result)
        except Exception as exc:
            logging.exception("show stats failed: %s", exc)

    show_stats_action.triggered.connect(show_stats)

    settings_action = menu.addAction("个性化设置")

    def open_settings() -> None:
        dialog = SettingsDialog(settings, parent=window, bridge=bridge)
        if dialog.exec() == QDialog.Accepted:
            values = dialog.get_values()
            bridge.setSettings(values)

    settings_action.triggered.connect(open_settings)

    backup_action = menu.addAction("数据备份")

    def backup_data() -> None:
        path, _ = QFileDialog.getSaveFileName(window, "导出备份文件", BASE_DIR, "ZIP 文件 (*.zip)")
        if path:
            bridge.createBackup(path)

    backup_action.triggered.connect(backup_data)

    restore_action = menu.addAction("数据恢复")

    def restore_data() -> None:
        path, _ = QFileDialog.getOpenFileName(window, "选择备份文件", BASE_DIR, "ZIP 文件 (*.zip)")
        if path:
            bridge.restoreBackup(path)

    restore_action.triggered.connect(restore_data)

    ai_detail_action = menu.addAction("AI 详细配置")

    def open_ai_detail() -> None:
        dialog = AIProviderDialog(settings, parent=window)
        if dialog.exec() == QDialog.Accepted:
            providers = dialog.get_providers()
            bridge.setAISettings({"ai_providers": providers})

    ai_detail_action.triggered.connect(open_ai_detail)

    position_menu = QMenu("窗口位置")

    def move_window(position: str) -> None:
        screen = window.screen() or app.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        margin = 20
        w = window.width()
        h = window.height()
        if position == "top_left":
            x = geo.left() + margin
            y = geo.top() + margin
        elif position == "top_right":
            x = geo.right() - w - margin
            y = geo.top() + margin
        elif position == "bottom_left":
            x = geo.left() + margin
            y = geo.bottom() - h - margin
        elif position == "bottom_right":
            x = geo.right() - w - margin
            y = geo.bottom() - h - margin
        else:
            x = geo.left() + (geo.width() - w) // 2
            y = geo.top() + (geo.height() - h) // 2
        window.move(x, y)
        logging.info("window moved: %s", position)

    position_menu.addAction("左上", lambda: move_window("top_left"))
    position_menu.addAction("右上", lambda: move_window("top_right"))
    position_menu.addAction("左下", lambda: move_window("bottom_left"))
    position_menu.addAction("右下", lambda: move_window("bottom_right"))
    position_menu.addAction("居中", lambda: move_window("center"))
    menu.addMenu(position_menu)

    toggle_window_action = menu.addAction("隐藏宠物窗口")

    def toggle_window_visible() -> None:
        if window.isVisible():
            window.hide()
            toggle_window_action.setText("显示宠物窗口")
        else:
            window.show()
            toggle_window_action.setText("隐藏宠物窗口")

    toggle_window_action.triggered.connect(toggle_window_visible)

    lock_action = menu.addAction("锁定位置")

    def toggle_lock() -> None:
        locked = window.toggle_lock()
        lock_action.setText("解锁位置" if locked else "锁定位置")
        logging.info("window locked: %s", locked)

    lock_action.triggered.connect(toggle_lock)

    exit_action = menu.addAction("关闭程序")
    exit_action.triggered.connect(lambda: (logging.info("exit requested"), tray.hide(), app.quit()))

    restart_action = menu.addAction("重启程序")
    def restart_app() -> None:
        logging.info("restart requested")
        QProcess.startDetached(sys.executable, sys.argv)
        tray.hide()
        app.quit()
    restart_action.triggered.connect(restart_app)

    tray.setContextMenu(menu)
    tray.show()

    window = Live2DPetWindow(bridge)
    window.show()
    bridge.set_window(window)
    bridge.set_open_ai_dialog(open_ai_detail)
    logging.info("window shown")
    hint_window = HotkeyHintWindow(window)
    hint_window.set_text(build_hotkey_hint(settings.get_settings()))
    hint_window.hide()

    def handle_backup_result(path: str) -> None:
        if path:
            tray.showMessage("数据备份", f"已生成：{path}", QSystemTrayIcon.Information, 3000)
            logging.info("backup created: %s", path)
        else:
            tray.showMessage("数据备份", "备份失败，请查看日志。", QSystemTrayIcon.Warning, 3000)

    def handle_restore_result(path: str) -> None:
        if path:
            tray.showMessage("数据恢复", "已恢复备份，正在重启应用。", QSystemTrayIcon.Information, 4000)
            logging.info("restore completed: %s", path)
            QTimer.singleShot(1200, lambda: (QProcess.startDetached(sys.executable, sys.argv), app.quit()))
        else:
            tray.showMessage("数据恢复", "恢复失败，请查看日志。", QSystemTrayIcon.Warning, 3000)

    bridge.backupCompleted.connect(handle_backup_result)
    bridge.restoreCompleted.connect(handle_restore_result)

    def open_backup_dialog() -> None:
        path, _ = QFileDialog.getSaveFileName(window, "导出备份文件", BASE_DIR, "ZIP 文件 (*.zip)")
        if path:
            bridge.createBackup(path)

    bridge.requestBackupDialog.connect(open_backup_dialog)

    reward, streak, is_new_day = apply_daily_login(settings)
    if reward > 0:
        bridge.addFavor(float(reward))
        bridge.push_passive_message(f"欢迎回来！连续登录第 {streak} 天，获得好感 +{reward}")
    bridge.push_passive_message("欢迎回来～今天也一起加油吧！")

    hotkey_manager = HotkeyManager()
    if sys.platform.startswith("win"):
        def toggle_pet() -> None:
            if window.isVisible():
                window.hide()
            else:
                window.show()

        def open_note() -> None:
            bridge.requestOpenPanel("note-panel")

        def toggle_pomodoro() -> None:
            pomodoro.toggle()

        handlers = {
            1: toggle_pet,
            2: open_note,
            3: toggle_pomodoro,
        }
        hotkey_filter = HotkeyFilter(handlers)
        app.installNativeEventFilter(hotkey_filter)

        def register_hotkeys(data: dict) -> None:
            hotkey_manager.unregister_all()
            mapping = [
                (1, data.get("hotkey_toggle_pet", "Ctrl+Shift+L")),
                (2, data.get("hotkey_note", "Ctrl+Shift+P")),
                (3, data.get("hotkey_pomodoro", "Ctrl+Shift+T")),
            ]
            for hotkey_id, text in mapping:
                parsed = parse_hotkey(str(text))
                if not parsed:
                    logging.warning("hotkey parse failed: %s", text)
                    continue
                modifiers, key = parsed
                if not hotkey_manager.register(hotkey_id, modifiers, key):
                    logging.warning("hotkey register failed: %s", text)

    register_hotkeys(settings.get_settings())
    bridge.settingsUpdated.connect(register_hotkeys)
    app.aboutToQuit.connect(hotkey_manager.unregister_all)

    def apply_passive_config_for_mood(mood_value: int) -> None:
        interval = max(5, int(passive_base_config.interval_min * mood_interval_factor(mood_value)))
        config = PassiveChatConfig(
            enabled=passive_base_config.enabled,
            interval_min=interval,
            random_enabled=passive_base_config.random_enabled,
            blessing_enabled=passive_base_config.blessing_enabled,
            focus_enabled=passive_base_config.focus_enabled,
            focus_interval_min=passive_base_config.focus_interval_min,
        )
        passive_chat.set_config(config)

    def apply_settings(data: dict) -> None:
        try:
            engine.set_thresholds(int(data["focus_active_ms"]), int(data["focus_sleep_ms"]))
            window.setWindowOpacity(float(data["window_opacity"]) / 100.0)
            pomodoro.set_durations(int(data["pomodoro_focus_min"]), int(data["pomodoro_break_min"]))
            reminders.set_config(ReminderConfig.from_settings(data))
            hint_window.set_text(build_hotkey_hint(data))
            passive_base_config.enabled = bool(data.get("passive_enabled", True))
            passive_base_config.interval_min = int(data.get("passive_interval_min", 30))
            passive_base_config.random_enabled = bool(data.get("passive_random_enabled", True))
            passive_base_config.blessing_enabled = bool(data.get("passive_blessing_enabled", True))
            passive_base_config.focus_enabled = bool(data.get("passive_focus_enabled", True))
            passive_base_config.focus_interval_min = int(data.get("passive_focus_interval_min", 60))
            apply_passive_config_for_mood(int(data.get("mood", 60)))
        except Exception as exc:
            logging.exception("apply settings failed: %s", exc)

    apply_settings(settings.get_settings())
    bridge.settingsUpdated.connect(apply_settings)
    bridge.settingsUpdated.emit(settings.get_settings())
    bridge.userMessage.connect(lambda _text: record_interaction())

    last_status = None
    last_mood_label = None
    last_pomodoro_mode = "idle"
    summary_sent_date = ""
    last_pomodoro_count = pomodoro.get_count_today()
    hint_ready = True
    interaction_count = 0
    last_interaction_count_ts = 0.0
    mood_day = date.today().isoformat()
    current_mood = int(settings.get_settings().get("mood", 60))
    mood_label, mood_emoji = mood_bucket(current_mood)
    last_mood_update = 0.0

    def record_interaction() -> None:
        nonlocal interaction_count, last_interaction_count_ts
        now = time.time()
        if now - last_interaction_count_ts < 30:
            return
        interaction_count += 1
        last_interaction_count_ts = now

    def ctrl_shift_pressed() -> bool:
        return (
            ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000
            and ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000
        )

    def poll_hotkey_hint() -> None:
        nonlocal hint_ready
        if not ctrl_shift_pressed():
            hint_ready = True
            return
        if not hint_ready:
            return
        hint_ready = False
        hint_window.show_hint()
        QTimer.singleShot(2000, hint_window.hide)

    def update_mood(state, now: float) -> None:
        nonlocal current_mood, mood_label, mood_emoji, last_mood_update, mood_day, interaction_count
        if now - last_mood_update < 60:
            return
        last_mood_update = now
        today = date.today().isoformat()
        if today != mood_day:
            mood_day = today
            interaction_count = 0
        if state.input_type in ("keyboard", "mouse"):
            record_interaction()
        data = settings.get_settings()
        favor = int(data.get("favor", 50))
        new_mood = compute_mood(
            stats.get_today_focus_seconds(),
            favor,
            interaction_count,
            state.idle_ms,
        )
        if new_mood != current_mood:
            current_mood = new_mood
            mood_label, mood_emoji = mood_bucket(current_mood)
            settings.set_settings({"mood": current_mood})
            apply_passive_config_for_mood(current_mood)
            logging.info("mood updated: %s %s", current_mood, mood_label)

    def push_summary(reason: str) -> None:
        nonlocal summary_sent_date
        today = date.today().isoformat()
        if summary_sent_date == today:
            return
        focus_today = stats.get_today_focus_seconds()
        pomodoro_today = pomodoro.get_count_today()
        week_focus = stats.get_week_focus_seconds()
        bridge.push_passive_message(build_daily_summary(focus_today, pomodoro_today))
        bridge.push_passive_message(build_weekly_summary(week_focus))
        summary_sent_date = today
        logging.info("summary pushed: %s", reason)

    def trigger_binding_action(category: str, key: str) -> None:
        model_path = settings.get_settings().get("model_path", "")
        if not model_path:
            return
        binding = binding_manager.get_binding(model_path, category, key)
        if not binding.motion and not binding.expression:
            return
        bridge.bindingPreview.emit(binding.motion or "", binding.expression or "")

    def classify_ai_text(text: str) -> str | None:
        lowered = text.lower()
        if any(word in lowered for word in ["欢迎", "你好", "hello", "hi"]):
            return "greeting"
        if any(word in lowered for word in ["加油", "cheer", "棒"]):
            return "cheer"
        if any(word in lowered for word in ["提醒", "休息", "喝水"]):
            return "reminder"
        if any(word in lowered for word in ["再见", "拜拜", "goodbye"]):
            return "farewell"
        return None

    def handle_ai_binding(text: str) -> None:
        kind = classify_ai_text(text)
        if kind:
            trigger_binding_action("ai", kind)

    bridge.aiReply.connect(handle_ai_binding)
    bridge.passiveMessage.connect(handle_ai_binding)

    def tick() -> None:
        state = engine.update()
        state = adjust_state_for_pomodoro(state, pomodoro.mode)
        if state.input_type in ("keyboard", "mouse"):
            record_interaction()
        update_mood(state, time.time())
        bridge.push_state(
            state,
            {
                "mood": current_mood,
                "mood_label": mood_label,
                "mood_emoji": mood_emoji,
            },
        )
        status_label = "paused" if engine.paused else state.status
        status_map = {
            "active": "活跃",
            "idle": "空闲",
            "sleep": "睡眠",
            "paused": "暂停",
        }
        nonlocal last_status
        nonlocal last_mood_label
        nonlocal last_pomodoro_mode
        if status_label != last_status:
            logging.info("status changed: %s", status_map.get(status_label, status_label))
            last_status = status_label
            trigger_binding_action("status", status_label)
        if mood_label != last_mood_label:
            last_mood_label = mood_label
            trigger_binding_action("mood", mood_label)
        if pomodoro.mode != last_pomodoro_mode:
            last_pomodoro_mode = pomodoro.mode
            if pomodoro.mode in ("focus", "break"):
                trigger_binding_action("pomodoro", pomodoro.mode)
        tooltip = f"状态：{status_map.get(status_label, status_label)}\n今日专注：{stats.format_today_focus()}"
        tray.setToolTip(tooltip)

        now = time.time()
        if stats.get_today_focus_seconds() >= 2 * 60 * 60:
            push_summary("focus_2h")
        reminder_events = reminders.update_focus(state, now)
        reminder_events += reminders.update_timers(now)
        for event in reminder_events:
            if event == "rest":
                tray.showMessage("休息提醒", "你已经连续专注一段时间，起来活动一下吧。", QSystemTrayIcon.Information, 3000)
            elif event == "water":
                tray.showMessage("喝水提醒", "记得喝点水，保持状态。", QSystemTrayIcon.Information, 3000)
            elif event == "eye":
                tray.showMessage("护眼提醒", "休息一下眼睛，看看远处。", QSystemTrayIcon.Information, 3000)
            logging.info("reminder fired: %s", event)

        due_items = reminder_store.due_items(now)
        if due_items:
            for item in due_items:
                title = item.get("title", "待办事项")
                tray.showMessage("任务提醒", title, QSystemTrayIcon.Information, 4000)
                reminder_store.mark_triggered(int(item.get("id", 0)))
            bridge.todosUpdated.emit(reminder_store.list_todos())

        for message in passive_chat.tick(state, now=now):
            bridge.push_passive_message(message)

        interaction_map = {
            "typing": [
                "加油！",
                "键盘敲得很有节奏～",
                "专注模式已开启！",
            ],
            "idle": [
                "我有点困了，要不要休息一下？",
                "休息片刻再继续吧。",
                "记得活动下肩膀～",
            ],
            "switch": [
                "专心一点哦。",
                "任务切换太快会分神～",
                "先把这一件做完？",
            ],
            "browser": [
                "需要我帮你查找资料吗？",
                "记得把要点记下来～",
                "浏览结束记得回到任务哦。",
            ],
        }
        for event in engine.get_interaction_events(state):
            choices = interaction_map.get(event)
            if choices:
                bridge.push_passive_message(random.choice(choices))

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(1000)

    last_clipboard = ""

    def poll_clipboard() -> None:
        nonlocal last_clipboard
        text = QGuiApplication.clipboard().text()
        if text and text != last_clipboard:
            last_clipboard = text
            bridge.poll_clipboard(text)

    clipboard_timer = QTimer()
    clipboard_timer.timeout.connect(poll_clipboard)
    clipboard_timer.start(1000)

    def poll_system_info() -> None:
        bridge.poll_system_info()

    sys_timer = QTimer()
    sys_timer.timeout.connect(poll_system_info)
    sys_timer.start(1000)

    hotkey_hint_timer = QTimer()
    hotkey_hint_timer.timeout.connect(poll_hotkey_hint)
    hotkey_hint_timer.start(120)

    def hourly_summary_check() -> None:
        hour = time.localtime().tm_hour
        if hour >= 17:
            push_summary("daily_17")

    summary_timer = QTimer()
    summary_timer.timeout.connect(hourly_summary_check)
    summary_timer.start(60 * 60 * 1000)
    hourly_summary_check()

    def poll_pomodoro() -> None:
        nonlocal last_pomodoro_mode, last_pomodoro_count
        state = bridge.poll_pomodoro()
        if not state:
            return
        mode = state.get("mode", "idle")
        count_today = int(state.get("count_today", 0))
        if count_today > last_pomodoro_count:
            last_pomodoro_count = count_today
            trigger_binding_action("pomodoro", "completed")
            push_summary("pomodoro_complete")
        if mode != last_pomodoro_mode:
            if mode == "break":
                tray.showMessage("番茄钟提醒", "专注结束，开始休息。", QSystemTrayIcon.Information, 3000)
                logging.info("pomodoro switch: focus -> break")
                reward = reward_for_focus_minutes(int(state.get("focus_min", 25)))
                bridge.addFavor(float(reward))
                bridge.push_passive_message(f"完成番茄专注，获得好感 +{reward}")
            elif mode == "focus":
                tray.showMessage("番茄钟提醒", "休息结束，开始专注。", QSystemTrayIcon.Information, 3000)
                logging.info("pomodoro switch: break -> focus")
            last_pomodoro_mode = mode

    pomodoro_timer = QTimer()
    pomodoro_timer.timeout.connect(poll_pomodoro)
    pomodoro_timer.start(1000)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
