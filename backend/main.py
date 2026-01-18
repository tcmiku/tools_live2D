from __future__ import annotations

import logging
import json
import os
import sys
import time
import random
import ctypes
from datetime import date

from PySide6.QtCore import QTimer, Qt, QUrl, QPoint, QProcess, QAbstractTableModel, QModelIndex, QDateTime
from PySide6.QtGui import QIcon, QGuiApplication, QDesktopServices
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
    QTableView,
    QHeaderView,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QFileDialog,
    QLabel,
    QWidget,
    QTabWidget,
    QComboBox,
    QListWidget,
    QPlainTextEdit,
    QDateTimeEdit,
    QTableWidgetItem,
    QAbstractItemView,
    QGroupBox,
)
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

try:
    from .focus import FocusEngine, adjust_state_for_pomodoro
    from .stats import FocusStats
    from .ai_client import AIClient
    from .bridge import BackendBridge
    from .model_bindings import ModelBindingManager, MotionBinding
    from .settings import AppSettings
    from .pomodoro import PomodoroEngine, reward_for_focus_minutes
    from .achievements import build_daily_summary, build_weekly_summary
    from .mood import compute_mood, mood_bucket, mood_interval_factor
    from .hotkey_hints import build_hotkey_hint
    from .hotkeys import HotkeyManager, HotkeyFilter, parse_hotkey
    from .reminders import ReminderEngine, ReminderStore, ReminderConfig
    from .login_rewards import apply_daily_login
    from .passive_chat import PassiveChatEngine, PassiveChatConfig
    from .texts import TextCatalog
    from .binding_utils import extract_motions_expressions
    from .launchers import LauncherManager
    from .plugins import PluginManager
except ImportError:
    from focus import FocusEngine, adjust_state_for_pomodoro
    from stats import FocusStats
    from ai_client import AIClient
    from bridge import BackendBridge
    from model_bindings import ModelBindingManager, MotionBinding
    from settings import AppSettings
    from pomodoro import PomodoroEngine, reward_for_focus_minutes
    from achievements import build_daily_summary, build_weekly_summary
    from mood import compute_mood, mood_bucket, mood_interval_factor
    from hotkey_hints import build_hotkey_hint
    from hotkeys import HotkeyManager, HotkeyFilter, parse_hotkey
    from reminders import ReminderEngine, ReminderStore, ReminderConfig
    from login_rewards import apply_daily_login
    from passive_chat import PassiveChatEngine, PassiveChatConfig
    from texts import TextCatalog
    from plugins import PluginManager
from binding_utils import extract_motions_expressions, list_model_paths
from launchers import LauncherManager


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
        self.hotkey_model_edit = QLineEdit()
        self.hotkey_launcher = QLineEdit()
        self.hotkey_chat_toggle = QLineEdit()
        self.hotkey_toggle.setPlaceholderText("Ctrl+Shift+L")
        self.hotkey_note.setPlaceholderText("Ctrl+Shift+P")
        self.hotkey_pomodoro.setPlaceholderText("Ctrl+Shift+T")
        self.hotkey_model_edit.setPlaceholderText("Ctrl+Shift+M")
        self.hotkey_launcher.setPlaceholderText("Ctrl+Shift+Space")
        self.hotkey_chat_toggle.setPlaceholderText("Ctrl+H")

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
        form.addRow("热键：模型编辑", self.hotkey_model_edit)
        form.addRow("热键：启动面板", self.hotkey_launcher)
        form.addRow("热键：聊天框", self.hotkey_chat_toggle)
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
        self.hotkey_model_edit.setText(str(data.get("hotkey_model_edit", "Ctrl+Shift+M")))
        self.hotkey_launcher.setText(str(data.get("hotkey_launcher_panel", "Ctrl+Shift+Space")))
        self.hotkey_chat_toggle.setText(str(data.get("hotkey_chat_toggle", "Ctrl+H")))
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
            "hotkey_model_edit": self.hotkey_model_edit.text().strip(),
            "hotkey_launcher_panel": self.hotkey_launcher.text().strip(),
            "hotkey_chat_toggle": self.hotkey_chat_toggle.text().strip(),
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


class BindingDialog(QDialog):
    def __init__(
        self,
        settings: AppSettings,
        binding_manager: ModelBindingManager,
        preview_handler=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("动作绑定")
        self.resize(640, 520)
        self.setStyleSheet(
            "QDialog { background: #f7f7f5; }"
            "QLabel { color: #1f1f1f; font-size: 12px; }"
            "QComboBox {"
            "  background: #ffffff;"
            "  border: 1px solid #c9c9c9;"
            "  border-radius: 6px;"
            "  padding: 3px 6px;"
            "}"
            "QTabWidget::pane { border: 1px solid #d5d5d5; background: #ffffff; }"
            "QTabBar::tab {"
            "  background: #e8e8e8;"
            "  padding: 6px 10px;"
            "  border-top-left-radius: 6px;"
            "  border-top-right-radius: 6px;"
            "  margin-right: 4px;"
            "}"
            "QTabBar::tab:selected { background: #ffffff; border: 1px solid #d5d5d5; }"
            "QTableWidget { background: #ffffff; border: 1px solid #d5d5d5; }"
            "QHeaderView::section { background: #ededed; padding: 4px; border: none; }"
            "QComboBox QAbstractItemView { background: #ffffff; selection-background-color: #2f6fed; }"
            "QPushButton {"
            "  background: #2f6fed;"
            "  color: white;"
            "  border: none;"
            "  border-radius: 6px;"
            "  padding: 4px 10px;"
            "}"
            "QPushButton:hover { background: #2558c9; }"
        )
        self._settings = settings
        self._binding_manager = binding_manager
        self._preview_handler = preview_handler
        self._model_path = ""
        self._motions: list[str] = []
        self._expressions: list[str] = []
        self._tables: dict[str, QTableWidget] = {}
        self._category_defs = {
            "心情": [("开心", "开心"), ("愉快", "愉快"), ("平静", "平静"), ("低落", "低落"), ("孤独", "孤独")],
            "状态": [("active", "活跃"), ("idle", "空闲"), ("sleep", "睡眠"), ("paused", "暂停")],
            "番茄钟": [("focus", "专注"), ("break", "休息"), ("completed", "完成")],
            "AI": [("greeting", "问候"), ("cheer", "鼓励"), ("reminder", "提醒"), ("farewell", "告别")],
            "互动": [("click", "点击"), ("petting", "抚摸"), ("drag", "拖拽")],
        }

        self.model_combo = QComboBox()
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        refresh_btn = QPushButton("刷新动作列表")
        refresh_btn.clicked.connect(self._refresh_model_lists)
        preview_btn = QPushButton("预览当前行")
        preview_btn.clicked.connect(self._preview_current_binding)

        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("当前模型"))
        top_layout.addWidget(self.model_combo, 1)
        top_layout.addWidget(refresh_btn)
        top_layout.addWidget(preview_btn)

        self.tabs = QTabWidget()
        for title in self._category_defs.keys():
            table = QTableWidget()
            table.setColumnCount(3)
            table.setHorizontalHeaderLabels(["类型", "动作", "表情"])
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.tabs.addTab(table, title)
            self._tables[title] = table

        reset_btn = QPushButton("重置本模型绑定")
        reset_btn.clicked.connect(self._reset_model_bindings)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(reset_btn)
        bottom_layout.addWidget(close_btn)

        main_layout = QVBoxLayout()
        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.tabs, 1)
        main_layout.addLayout(bottom_layout)
        self.setLayout(main_layout)

        self._reload_models()

    def _reload_models(self) -> None:
        current = self._settings.get_settings().get("model_path", "")
        model_paths = list_model_paths(BASE_DIR)
        for path in self._binding_manager.get_all_models().keys():
            if path not in model_paths:
                model_paths.append(path)
        if current and current not in model_paths:
            model_paths.insert(0, current)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for path in model_paths:
            name = self._binding_manager.get_model(path).get("name", path)
            self.model_combo.addItem(name, path)
        self.model_combo.blockSignals(False)
        if model_paths:
            if current:
                index = self.model_combo.findData(current)
                if index >= 0:
                    self.model_combo.setCurrentIndex(index)
            else:
                self.model_combo.setCurrentIndex(0)
        else:
            self._model_path = ""
            self._refresh_tables()

    def _on_model_changed(self) -> None:
        self._model_path = self.model_combo.currentData() or ""
        self._refresh_model_lists()

    def _refresh_model_lists(self) -> None:
        self._motions, self._expressions = extract_motions_expressions(BASE_DIR, self._model_path)
        self._refresh_tables()

    def _refresh_tables(self) -> None:
        for title, keys in self._category_defs.items():
            table = self._tables[title]
            table.setRowCount(len(keys))
            for row, (key, label) in enumerate(keys):
                item = QTableWidgetItem(label)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                item.setData(Qt.UserRole, key)
                table.setItem(row, 0, item)

                binding = self._binding_manager.get_binding(self._model_path, self._category_key(title), key)
                motion_combo = self._create_combo(self._motions, binding.motion or "", title, key, "motion")
                expr_combo = self._create_combo(self._expressions, binding.expression or "", title, key, "expression")
                table.setCellWidget(row, 1, motion_combo)
                table.setCellWidget(row, 2, expr_combo)

    def _category_key(self, title: str) -> str:
        mapping = {
            "心情": "mood",
            "状态": "status",
            "番茄钟": "pomodoro",
            "AI": "ai",
            "互动": "interaction",
        }
        return mapping.get(title, title)

    def _create_combo(self, items: list[str], current: str, category: str, key: str, field: str) -> QComboBox:
        combo = QComboBox()
        options = [""] + list(items)
        if current and current not in options:
            options.insert(1, current)
        for option in options:
            combo.addItem(option)
        index = combo.findText(current) if current else 0
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentTextChanged.connect(
            lambda text, cat=category, k=key, f=field: self._update_binding(cat, k, f, text)
        )
        return combo

    def _update_binding(self, title: str, key: str, field: str, value: str) -> None:
        if not self._model_path:
            return
        category = self._category_key(title)
        current = self._binding_manager.get_binding(self._model_path, category, key)
        motion = current.motion
        expression = current.expression
        if field == "motion":
            motion = value or None
        else:
            expression = value or None
        self._binding_manager.set_binding(self._model_path, category, key, MotionBinding(motion, expression))

    def _reset_model_bindings(self) -> None:
        if not self._model_path:
            return
        self._binding_manager.reset_model(self._model_path)
        self._refresh_tables()

    def _preview_current_binding(self) -> None:
        if not self._preview_handler:
            return
        current_tab = self.tabs.currentWidget()
        if not isinstance(current_tab, QTableWidget):
            return
        row = current_tab.currentRow()
        if row < 0:
            return
        item = current_tab.item(row, 0)
        if not item:
            return
        key = item.data(Qt.UserRole)
        if not key:
            return
        title = self.tabs.tabText(self.tabs.currentIndex())
        category = self._category_key(title)
        binding = self._binding_manager.get_binding(self._model_path, category, key)
        self._preview_handler(binding.motion or "", binding.expression or "")


class LauncherEditorDialog(QDialog):
    def __init__(self, manager: LauncherManager, parent=None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._current_id: int | None = None

        self.setWindowTitle("启动器编辑")
        self.setMinimumSize(760, 480)
        self.setStyleSheet(
            "QDialog { background: #f7f7f5; }"
            "QLabel { color: #1f1f1f; font-size: 12px; }"
            "QLineEdit, QPlainTextEdit, QComboBox {"
            " background: #ffffff; color: #1f1f1f; border: 1px solid #d5d5d5; border-radius: 6px; padding: 4px;"
            "}"
            "QListWidget { background: #ffffff; border: 1px solid #d5d5d5; }"
            "QPushButton { background: #2f6fed; color: white; border: none; border-radius: 6px; padding: 6px 12px; }"
            "QPushButton:disabled { background: #b8b8b8; }"
        )

        layout = QHBoxLayout(self)
        self.list = QListWidget()
        self.list.setMinimumWidth(220)
        layout.addWidget(self.list)

        form_wrap = QVBoxLayout()
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.type_combo = QComboBox()
        self.type_combo.addItems(["web", "app", "group"])
        self.url_edit = QLineEdit()
        self.path_edit = QLineEdit()
        self.args_edit = QLineEdit()
        self.tags_edit = QLineEdit()
        self.icon_edit = QLineEdit()
        self.hotkey_edit = QLineEdit()
        self.items_edit = QPlainTextEdit()
        self.items_edit.setPlaceholderText("group 类型：填写 launcher_id 列表或 JSON")
        self.usage_label = QLabel("-")

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        self.path_btn = QPushButton("浏览")
        self.path_btn.setFixedWidth(60)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(self.path_btn)
        path_container = QWidget()
        path_container.setLayout(path_row)

        form.addRow("名称", self.name_edit)
        form.addRow("类型", self.type_combo)
        form.addRow("URL", self.url_edit)
        form.addRow("路径", path_container)
        form.addRow("参数(空格分隔)", self.args_edit)
        form.addRow("标签(逗号分隔)", self.tags_edit)
        form.addRow("图标", self.icon_edit)
        form.addRow("热键", self.hotkey_edit)
        form.addRow("套件内容", self.items_edit)
        form.addRow("使用次数", self.usage_label)

        form_wrap.addLayout(form)

        actions = QHBoxLayout()
        self.new_btn = QPushButton("新增")
        self.save_btn = QPushButton("保存")
        self.delete_btn = QPushButton("删除")
        self.run_btn = QPushButton("执行")
        self.import_btn = QPushButton("导入")
        self.export_btn = QPushButton("导出")
        self.close_btn = QPushButton("关闭")
        actions.addWidget(self.new_btn)
        actions.addWidget(self.save_btn)
        actions.addWidget(self.delete_btn)
        actions.addWidget(self.run_btn)
        actions.addWidget(self.import_btn)
        actions.addWidget(self.export_btn)
        actions.addWidget(self.close_btn)

        form_wrap.addLayout(actions)
        layout.addLayout(form_wrap)

        self.list.currentItemChanged.connect(self._on_select)
        self.type_combo.currentTextChanged.connect(self._sync_type_fields)
        self.new_btn.clicked.connect(self._new_item)
        self.save_btn.clicked.connect(self._save_item)
        self.delete_btn.clicked.connect(self._delete_item)
        self.run_btn.clicked.connect(self._run_item)
        self.import_btn.clicked.connect(self._import_data)
        self.export_btn.clicked.connect(self._export_data)
        self.close_btn.clicked.connect(self.close)
        self.path_btn.clicked.connect(self._select_path)

        self.refresh_list()
        self._sync_type_fields(self.type_combo.currentText())

    def refresh_list(self, select_id: int | None = None) -> None:
        self.list.clear()
        items = self._manager.get_all()
        for item in items:
            name = str(item.get("name", "未命名"))
            kind = str(item.get("type", "web"))
            label = f"{name} ({kind})"
            self.list.addItem(label)
        if select_id is not None:
            for idx, item in enumerate(items):
                if int(item.get("id", 0)) == int(select_id):
                    self.list.setCurrentRow(idx)
                    break
        elif items:
            self.list.setCurrentRow(0)

    def _selected_item(self) -> dict | None:
        row = self.list.currentRow()
        items = self._manager.get_all()
        if 0 <= row < len(items):
            return items[row]
        return None

    def _on_select(self) -> None:
        item = self._selected_item()
        if not item:
            self._clear_form()
            return
        self._current_id = int(item.get("id", 0))
        self.name_edit.setText(str(item.get("name", "")))
        self.type_combo.setCurrentText(str(item.get("type", "web")))
        self.url_edit.setText(str(item.get("url", "")))
        self.path_edit.setText(str(item.get("path", "")))
        self.args_edit.setText(" ".join(item.get("args", []) or []))
        self.tags_edit.setText(", ".join(item.get("tags", []) or []))
        self.icon_edit.setText(str(item.get("icon", "")))
        self.hotkey_edit.setText(str(item.get("hotkey", "")))
        self.items_edit.setPlainText(self._format_items(item.get("items", [])))
        self.usage_label.setText(str(item.get("usage_count", 0)))
        self._sync_type_fields(self.type_combo.currentText())

    def _clear_form(self) -> None:
        self._current_id = None
        self.name_edit.clear()
        self.url_edit.clear()
        self.path_edit.clear()
        self.args_edit.clear()
        self.tags_edit.clear()
        self.icon_edit.clear()
        self.hotkey_edit.clear()
        self.items_edit.setPlainText("")
        self.usage_label.setText("-")

    def _new_item(self) -> None:
        self.list.clearSelection()
        self._clear_form()

    def _collect_payload(self) -> dict:
        return {
            "id": self._current_id,
            "name": self.name_edit.text().strip() or "未命名",
            "type": self.type_combo.currentText().strip(),
            "url": self.url_edit.text().strip(),
            "path": self.path_edit.text().strip(),
            "args": [x for x in self.args_edit.text().split(" ") if x],
            "tags": [x.strip() for x in self.tags_edit.text().split(",") if x.strip()],
            "icon": self.icon_edit.text().strip(),
            "hotkey": self.hotkey_edit.text().strip(),
            "items": self._parse_items(self.items_edit.toPlainText()),
        }

    def _save_item(self) -> None:
        payload = self._collect_payload()
        saved = self._manager.save_launcher(payload)
        self.refresh_list(select_id=int(saved.get("id", 0)))
        logging.info("launcher saved: %s", saved.get("name", ""))

    def _delete_item(self) -> None:
        if not self._current_id:
            return
        result = QMessageBox.question(self, "删除启动项", "确认删除当前启动项？")
        if result != QMessageBox.Yes:
            return
        if self._manager.delete_launcher(int(self._current_id)):
            logging.info("launcher deleted: %s", self._current_id)
        self.refresh_list()

    def _run_item(self) -> None:
        if not self._current_id:
            return
        result = self._manager.execute(int(self._current_id))
        QMessageBox.information(self, "启动结果", result.message)

    def _select_path(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择应用程序")
        if path:
            self.path_edit.setText(path)

    def _import_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入启动项", filter="JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if self._manager.import_data(data):
                logging.info("launcher import success")
            self.refresh_list()
        except Exception as exc:
            logging.exception("launcher import failed: %s", exc)
            QMessageBox.warning(self, "导入失败", "无法导入该文件")

    def _export_data(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出启动项", "launchers.json", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._manager.export_data(), f, ensure_ascii=False, indent=2)
            logging.info("launcher export success: %s", path)
        except Exception as exc:
            logging.exception("launcher export failed: %s", exc)
            QMessageBox.warning(self, "导出失败", "无法写入文件")

    def _parse_items(self, text: str) -> list:
        raw = text.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                data = json.loads(raw)
                return data if isinstance(data, list) else []
            except json.JSONDecodeError:
                return []
        items = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                items.append({"launcher_id": int(part)})
            except ValueError:
                continue
        return items

    def _format_items(self, items: list) -> str:
        if not items:
            return ""
        try:
            return json.dumps(items, ensure_ascii=False, indent=2)
        except TypeError:
            return ""

    def _sync_type_fields(self, kind: str) -> None:
        kind = kind or "web"
        is_web = kind == "web"
        is_app = kind == "app"
        is_group = kind == "group"
        self.url_edit.setEnabled(is_web)
        self.path_edit.setEnabled(is_app)
        self.path_btn.setEnabled(is_app)
        self.args_edit.setEnabled(is_app)
        self.items_edit.setEnabled(is_group)


class TodoDialog(QDialog):
    def __init__(self, store: ReminderStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store

        self.setWindowTitle("待办事项")
        self.setMinimumSize(520, 360)
        self.setStyleSheet(
            "QDialog { background: #f7f7f5; }"
            "QLabel { color: #1f1f1f; font-size: 12px; }"
            "QLineEdit, QDateTimeEdit {"
            " background: #ffffff; color: #1f1f1f; border: 1px solid #d5d5d5; border-radius: 6px; padding: 4px;"
            "}"
            "QTableWidget { background: #ffffff; border: 1px solid #d5d5d5; }"
            "QHeaderView::section { background: #ededed; padding: 4px; border: none; }"
            "QPushButton { background: #2f6fed; color: white; border: none; border-radius: 6px; padding: 6px 12px; }"
            "QPushButton:disabled { background: #b8b8b8; }"
        )

        layout = QVBoxLayout(self)
        form = QHBoxLayout()
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("待办事项")
        self.due_input = QDateTimeEdit()
        self.due_input.setCalendarPopup(True)
        self.due_input.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.due_input.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        calendar = self.due_input.calendarWidget()
        if calendar is not None:
            calendar.setStyleSheet(
                "QCalendarWidget QWidget { background: #ffffff; color: #1f1f1f; }"
                "QCalendarWidget QAbstractItemView {"
                " background: #ffffff; color: #1f1f1f; selection-background-color: #2f6fed;"
                " selection-color: #ffffff; }"
                "QCalendarWidget QToolButton { color: #1f1f1f; }"
                "QCalendarWidget QMenu { background: #ffffff; color: #1f1f1f; }"
            )
        self.add_btn = QPushButton("添加")
        form.addWidget(self.title_input, 2)
        form.addWidget(self.due_input, 1)
        form.addWidget(self.add_btn)
        layout.addLayout(form)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["标题", "时间", "状态"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        self.remove_btn = QPushButton("删除")
        self.close_btn = QPushButton("关闭")
        btn_row.addWidget(self.remove_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        self.add_btn.clicked.connect(self._add_item)
        self.remove_btn.clicked.connect(self._remove_item)
        self.close_btn.clicked.connect(self.close)

        self.refresh()

    def refresh(self) -> None:
        self.table.setRowCount(0)
        todos = self._store.list_todos()
        for item in todos:
            row = self.table.rowCount()
            self.table.insertRow(row)
            title = QTableWidgetItem(str(item.get("title", "")))
            title.setData(Qt.UserRole, int(item.get("id", 0)))
            due_ts = float(item.get("due_ts", 0))
            due_text = time.strftime("%Y-%m-%d %H:%M", time.localtime(due_ts))
            due = QTableWidgetItem(due_text)
            status = QTableWidgetItem("已提醒" if item.get("triggered") else "未提醒")
            self.table.setItem(row, 0, title)
            self.table.setItem(row, 1, due)
            self.table.setItem(row, 2, status)

    def _add_item(self) -> None:
        title = self.title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "提示", "请输入待办事项标题")
            return
        due_dt = self.due_input.dateTime().toSecsSinceEpoch()
        self._store.add_todo(title, due_dt)
        self.title_input.clear()
        self.refresh()

    def _remove_item(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        todo_id = int(item.data(Qt.UserRole) or 0)
        if todo_id:
            self._store.remove_todo(todo_id)
            self.refresh()


class PluginTableModel(QAbstractTableModel):
    def __init__(self, manager: PluginManager) -> None:
        super().__init__()
        self._manager = manager
        self._rows: list[dict] = []
        self.refresh()

    def refresh(self) -> None:
        self.beginResetModel()
        self._rows = self._manager.export_state()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return 6

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        headers = ["启用", "名称", "版本", "状态", "路径", "错误"]
        if 0 <= section < len(headers):
            return headers[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._rows):
            return None
        item = self._rows[row]
        if col == 0:
            if role == Qt.CheckStateRole:
                return Qt.Checked if item.get("enabled") else Qt.Unchecked
            return None
        if role != Qt.DisplayRole:
            return None
        plugin_id = str(item.get("id", ""))
        if col == 1:
            return f"{item.get('name', plugin_id)} ({plugin_id})"
        if col == 2:
            return str(item.get("version", ""))
        if col == 3:
            return "已加载" if item.get("loaded") else "未加载"
        if col == 4:
            return str(item.get("path", ""))
        if col == 5:
            return str(item.get("error", ""))
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemIsEnabled
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:
        if not index.isValid() or index.column() != 0:
            return False
        if role != Qt.CheckStateRole:
            return False
        row = index.row()
        if row < 0 or row >= len(self._rows):
            return False
        plugin_id = str(self._rows[row].get("id", ""))
        enabled = value == Qt.Checked
        if plugin_id:
            self._manager.set_enabled(plugin_id, enabled)
            self.refresh()
            return True
        return False

    def get_item(self, row: int) -> dict:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return {}


class PluginManagerDialog(QDialog):
    def __init__(self, manager: PluginManager, parent=None) -> None:
        super().__init__(parent)
        self._manager = manager

        self.setWindowTitle("插件管理")
        self.setMinimumSize(720, 520)
        self.setStyleSheet(
            "QDialog { background: #f7f7f5; }"
            "QLabel { color: #1f1f1f; font-size: 12px; }"
            "QLineEdit, QPlainTextEdit {"
            " background: #ffffff; color: #1f1f1f; border: 1px solid #d5d5d5; border-radius: 6px; padding: 4px;"
            "}"
            "QTableWidget { background: #ffffff; border: 1px solid #d5d5d5; }"
            "QHeaderView::section { background: #ededed; padding: 4px; border: none; }"
            "QPushButton { background: #2f6fed; color: white; border: none; border-radius: 6px; padding: 6px 12px; }"
            "QPushButton:disabled { background: #b8b8b8; }"
        )

        layout = QVBoxLayout(self)

        actions = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新")
        self.reload_all_btn = QPushButton("重新加载全部")
        self.reload_selected_btn = QPushButton("重新加载选中")
        self.open_panel_btn = QPushButton("打开面板")
        self.install_btn = QPushButton("安装目录")
        self.import_btn = QPushButton("导入压缩包")
        self.export_btn = QPushButton("导出选中")
        self.uninstall_btn = QPushButton("卸载选中")
        self.open_folder_btn = QPushButton("打开插件目录")
        actions.addWidget(self.refresh_btn)
        actions.addWidget(self.reload_all_btn)
        actions.addWidget(self.reload_selected_btn)
        actions.addWidget(self.open_panel_btn)
        actions.addWidget(self.install_btn)
        actions.addWidget(self.import_btn)
        actions.addWidget(self.export_btn)
        actions.addWidget(self.uninstall_btn)
        actions.addWidget(self.open_folder_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.table = QTableView()
        self.model = PluginTableModel(self._manager)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.table, 1)

        test_group = QGroupBox("测试钩子")
        test_layout = QVBoxLayout(test_group)
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("消息"))
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("输入测试消息")
        input_row.addWidget(self.message_input, 1)
        test_layout.addLayout(input_row)

        btn_row = QHBoxLayout()
        self.test_start_btn = QPushButton("on_app_start")
        self.test_ready_btn = QPushButton("on_app_ready")
        self.test_state_btn = QPushButton("on_state")
        self.test_tick_btn = QPushButton("on_tick")
        self.test_user_btn = QPushButton("on_user_message")
        self.test_ai_btn = QPushButton("on_ai_reply")
        self.test_passive_btn = QPushButton("on_passive_message")
        self.test_ai_context_btn = QPushButton("on_ai_context")
        btn_row.addWidget(self.test_start_btn)
        btn_row.addWidget(self.test_ready_btn)
        btn_row.addWidget(self.test_state_btn)
        btn_row.addWidget(self.test_tick_btn)
        btn_row.addWidget(self.test_user_btn)
        btn_row.addWidget(self.test_ai_btn)
        btn_row.addWidget(self.test_passive_btn)
        btn_row.addWidget(self.test_ai_context_btn)
        btn_row.addStretch(1)
        test_layout.addLayout(btn_row)
        layout.addWidget(test_group)

        self.log_tabs = QTabWidget()
        self.plugin_log = QPlainTextEdit()
        self.plugin_log.setReadOnly(True)
        self.plugin_log.setPlaceholderText("插件日志")
        self.action_log = QPlainTextEdit()
        self.action_log.setReadOnly(True)
        self.action_log.setPlaceholderText("操作日志")
        self.log_tabs.addTab(self.plugin_log, "插件日志")
        self.log_tabs.addTab(self.action_log, "操作日志")
        log_actions = QHBoxLayout()
        self.clear_log_btn = QPushButton("清空插件日志")
        log_actions.addWidget(self.clear_log_btn)
        log_actions.addStretch(1)
        layout.addWidget(self.log_tabs, 1)
        layout.addLayout(log_actions)

        self.refresh_btn.clicked.connect(self.refresh)
        self.reload_all_btn.clicked.connect(self._reload_all)
        self.reload_selected_btn.clicked.connect(self._reload_selected)
        self.open_panel_btn.clicked.connect(self._open_panel_selected)
        self.install_btn.clicked.connect(self._install_from_dir)
        self.import_btn.clicked.connect(self._import_zip)
        self.export_btn.clicked.connect(self._export_selected)
        self.uninstall_btn.clicked.connect(self._uninstall_selected)
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.test_start_btn.clicked.connect(self._test_app_start)
        self.test_ready_btn.clicked.connect(self._test_app_ready)
        self.test_state_btn.clicked.connect(self._test_state)
        self.test_tick_btn.clicked.connect(self._test_tick)
        self.test_user_btn.clicked.connect(self._test_user_message)
        self.test_ai_btn.clicked.connect(self._test_ai_reply)
        self.test_passive_btn.clicked.connect(self._test_passive_message)
        self.test_ai_context_btn.clicked.connect(self._test_ai_context)
        self.clear_log_btn.clicked.connect(self._clear_plugin_log)
        self.table.selectionModel().selectionChanged.connect(self._refresh_plugin_log)

        self.refresh()

    def refresh(self) -> None:
        self.model.refresh()
        self._refresh_plugin_log()

    def _selected_plugin_id(self) -> str:
        index = self.table.currentIndex()
        if not index.isValid():
            return ""
        item = self.model.get_item(index.row())
        return str(item.get("id", "")) if item else ""

    def _reload_all(self) -> None:
        self._manager.reload_plugins()
        self._log_action("重新加载全部插件")
        self.refresh()

    def _reload_selected(self) -> None:
        plugin_id = self._selected_plugin_id()
        if not plugin_id:
            return
        self._manager.reload_plugin(plugin_id)
        self._log_action(f"重新加载插件: {plugin_id}")
        self.refresh()

    def _open_panel_selected(self) -> None:
        plugin_id = self._selected_plugin_id()
        if not plugin_id:
            return
        panel = self._manager.open_plugin_panel(plugin_id, parent=self)
        if panel and hasattr(panel, "show"):
            panel.show()
            if hasattr(panel, "raise_"):
                panel.raise_()
            if hasattr(panel, "activateWindow"):
                panel.activateWindow()
            self._log_action(f"打开插件面板: {plugin_id}")
        else:
            QMessageBox.information(self, "插件面板", "该插件未提供管理面板。")
            self._log_action(f"插件无面板: {plugin_id}")

    def _open_folder(self) -> None:
        if QDesktopServices.openUrl(QUrl.fromLocalFile(self._manager.plugin_root)):
            self._log_action("打开插件目录")
        else:
            self._log_action("无法打开插件目录")

    def _install_from_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择插件目录", self._manager.plugin_root)
        if not path:
            return
        ok, message = self._manager.install_from_dir(path)
        QMessageBox.information(self, "安装插件", message)
        self._log_action(message)
        self.refresh()

    def _import_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入插件压缩包", "", "ZIP 文件 (*.zip)")
        if not path:
            return
        ok, message = self._manager.import_from_zip(path)
        QMessageBox.information(self, "导入插件", message)
        self._log_action(message)
        self.refresh()

    def _export_selected(self) -> None:
        plugin_id = self._selected_plugin_id()
        if not plugin_id:
            return
        default_name = f"{plugin_id}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "导出插件", default_name, "ZIP 文件 (*.zip)")
        if not path:
            return
        ok, message = self._manager.export_to_zip(plugin_id, path)
        QMessageBox.information(self, "导出插件", message)
        self._log_action(message)

    def _uninstall_selected(self) -> None:
        plugin_id = self._selected_plugin_id()
        if not plugin_id:
            return
        result = QMessageBox.question(self, "卸载插件", f"确认卸载插件 {plugin_id}？")
        if result != QMessageBox.Yes:
            return
        ok, message = self._manager.uninstall_plugin(plugin_id)
        QMessageBox.information(self, "卸载插件", message)
        self._log_action(message)
        self.refresh()

    def _test_app_start(self) -> None:
        self._manager.on_app_start()
        self._log_action("触发 on_app_start")

    def _test_app_ready(self) -> None:
        self._manager.on_app_ready()
        self._log_action("触发 on_app_ready")

    def _test_state(self) -> None:
        payload = {"status": "active", "idle_ms": 1200, "focus_seconds_today": 42, "input_type": "keyboard", "window_title": "Test"}
        self._manager.on_state(payload)
        self._log_action("触发 on_state")

    def _test_tick(self) -> None:
        payload = {"status": "active", "idle_ms": 800, "focus_seconds_today": 42, "input_type": "mouse", "window_title": "Test"}
        self._manager.on_tick(payload, time.time())
        self._log_action("触发 on_tick")

    def _test_user_message(self) -> None:
        text = self._message_text()
        self._manager.on_user_message(text)
        self._log_action(f"触发 on_user_message: {text}")

    def _test_ai_reply(self) -> None:
        text = self._message_text()
        self._manager.on_ai_reply(text)
        self._log_action(f"触发 on_ai_reply: {text}")

    def _test_passive_message(self) -> None:
        text = self._message_text()
        self._manager.on_passive_message(text)
        self._log_action(f"触发 on_passive_message: {text}")

    def _test_ai_context(self) -> None:
        text = self._message_text()
        context = self._manager.collect_ai_context(text)
        if context:
            joined = " | ".join(context)
            self._log_action(f"触发 on_ai_context: {joined}")
        else:
            self._log_action("触发 on_ai_context: 无返回")

    def _clear_plugin_log(self) -> None:
        plugin_id = self._selected_plugin_id()
        if not plugin_id:
            return
        self._manager.clear_logs(plugin_id)
        self._log_action(f"清空插件日志: {plugin_id}")
        self._refresh_plugin_log()

    def _message_text(self) -> str:
        text = self.message_input.text().strip()
        return text or "测试消息"

    def _log_action(self, text: str) -> None:
        self.action_log.appendPlainText(text)

    def _refresh_plugin_log(self, *_args) -> None:
        plugin_id = self._selected_plugin_id()
        lines = self._manager.get_logs(plugin_id) if plugin_id else []
        self.plugin_log.setPlainText("\n".join(lines))

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
    app.setStyleSheet(
        "QDialog { background: #f7f7f5; }"
        "QMessageBox { background: #f7f7f5; }"
        "QLabel { color: #1f1f1f; font-size: 12px; }"
        "QLineEdit, QPlainTextEdit, QComboBox, QDateTimeEdit {"
        " background: #ffffff; color: #1f1f1f; border: 1px solid #d5d5d5; border-radius: 6px; padding: 4px;"
        "}"
        "QTableWidget, QListWidget { background: #ffffff; border: 1px solid #d5d5d5; }"
        "QHeaderView::section { background: #ededed; padding: 4px; border: none; }"
        "QPushButton { background: #2f6fed; color: #ffffff; border: none; border-radius: 6px; padding: 6px 12px; }"
        "QPushButton:disabled { background: #b8b8b8; }"
        "QCalendarWidget QWidget { background: #ffffff; color: #1f1f1f; }"
        "QCalendarWidget QAbstractItemView {"
        " background: #ffffff; color: #1f1f1f; selection-background-color: #2f6fed; selection-color: #ffffff; }"
        "QCalendarWidget QToolButton { color: #1f1f1f; }"
        "QCalendarWidget QMenu { background: #ffffff; color: #1f1f1f; }"
    )

    stats = FocusStats()
    engine = FocusEngine(stats=stats)
    settings = AppSettings()
    ai_client = AIClient(settings)
    pomodoro = PomodoroEngine(os.path.join(BASE_DIR, "data", "pomodoro.json"))
    reminders = ReminderEngine(ReminderConfig.from_settings(settings.get_settings()))
    settings_data = settings.get_settings()
    texts = TextCatalog(os.path.join(BASE_DIR, "data", "texts.json"))
    passive_base_config = PassiveChatConfig(
        enabled=settings_data.get("passive_enabled", True),
        interval_min=settings_data.get("passive_interval_min", 30),
        random_enabled=settings_data.get("passive_random_enabled", True),
        blessing_enabled=settings_data.get("passive_blessing_enabled", True),
        focus_enabled=settings_data.get("passive_focus_enabled", True),
        focus_interval_min=settings_data.get("passive_focus_interval_min", 60),
    )
    passive_chat = PassiveChatEngine(passive_base_config, texts=texts)
    reminder_store = ReminderStore(os.path.join(BASE_DIR, "data", "reminders.json"))
    bindings_path = settings.get_settings().get("bindings_path", "data/model_bindings.json")
    if not os.path.isabs(bindings_path):
        bindings_path = os.path.join(BASE_DIR, bindings_path)
    binding_manager = ModelBindingManager(bindings_path)
    launchers_path = os.path.join(BASE_DIR, "data", "launchers.json")
    launcher_manager = LauncherManager(launchers_path)
    bridge = BackendBridge(
        ai_client,
        settings=settings,
        pomodoro=pomodoro,
        reminders=reminders,
        reminder_store=reminder_store,
        binding_manager=binding_manager,
        launcher_manager=launcher_manager,
    )
    plugin_manager = PluginManager(BASE_DIR, settings, bridge, texts=texts)
    bridge.set_plugin_manager(plugin_manager)
    plugin_manager.load_plugins()
    plugin_manager.on_app_start()
    plugin_manager.on_settings_updated(settings.get_settings())
    bridge.pluginsUpdated.emit({"plugins": plugin_manager.export_state()})

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
                "QMessageBox { background-color: #f7f7f5; }"
                "QLabel { color: #1f1f1f; font-size: 13px; }"
                "QPushButton { min-width: 72px; padding: 4px 10px; "
                "background: #2f6fed; color: white; border: none; border-radius: 6px; }"
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

    binding_dialog = None
    launcher_dialog = None
    todo_dialog = None
    plugin_dialog = None

    def open_binding_dialog() -> None:
        nonlocal binding_dialog
        if binding_dialog is None:
            binding_dialog = BindingDialog(
                settings,
                binding_manager,
                preview_handler=lambda motion, expression: bridge.bindingPreview.emit(motion or "", expression or ""),
                parent=window,
            )
        binding_dialog.show()
        binding_dialog.raise_()
        binding_dialog.activateWindow()

    def open_launcher_dialog() -> None:
        nonlocal launcher_dialog
        if launcher_dialog is None:
            launcher_dialog = LauncherEditorDialog(launcher_manager, parent=window)
        launcher_dialog.refresh_list()
        launcher_dialog.show()
        launcher_dialog.raise_()
        launcher_dialog.activateWindow()

    def open_todo_dialog() -> None:
        nonlocal todo_dialog
        if todo_dialog is None:
            todo_dialog = TodoDialog(reminder_store, parent=window)
        todo_dialog.refresh()
        todo_dialog.show()
        todo_dialog.raise_()
        todo_dialog.activateWindow()

    def open_plugin_dialog() -> None:
        nonlocal plugin_dialog
        if plugin_dialog is None:
            plugin_dialog = PluginManagerDialog(plugin_manager, parent=window)
        plugin_dialog.refresh()
        plugin_dialog.show()
        plugin_dialog.raise_()
        plugin_dialog.activateWindow()

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
    bridge.set_open_binding_dialog(open_binding_dialog)
    bridge.set_open_launcher_dialog(open_launcher_dialog)
    bridge.set_open_todo_dialog(open_todo_dialog)
    bridge.set_open_plugin_dialog(open_plugin_dialog)
    bridge.settingsUpdated.connect(plugin_manager.on_settings_updated)
    bridge.aiReply.connect(plugin_manager.on_ai_reply)
    bridge.passiveMessage.connect(plugin_manager.on_passive_message)
    bridge.userMessage.connect(plugin_manager.on_user_message)
    logging.info("window shown")
    plugin_manager.on_app_ready()
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
        template = texts.get_text(
            "system.welcome_reward",
            "欢迎回来！连续登录第 {streak} 天，获得好感 +{reward}",
        )
        bridge.push_passive_message(template.format(streak=streak, reward=reward))
    welcome_list = texts.get_list("system.welcome", ["欢迎回来～今天也一起加油吧！"])
    if welcome_list:
        bridge.push_passive_message(random.choice(welcome_list))

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

        def toggle_model_edit() -> None:
            current = settings.get_settings().get("model_edit_mode", False)
            bridge.setSettings({"model_edit_mode": not bool(current)})

        def open_launcher_panel() -> None:
            logging.info("hotkey open launcher panel")
            bridge.requestOpenPanel("launcher-panel")

        handlers = {
            1: toggle_pet,
            2: open_note,
            3: toggle_pomodoro,
            4: toggle_model_edit,
            5: open_launcher_panel,
        }
        hotkey_filter = HotkeyFilter(handlers)
        app.installNativeEventFilter(hotkey_filter)
        app._hotkey_filter = hotkey_filter

        def register_hotkeys(data: dict) -> None:
            hotkey_manager.unregister_all()
            handlers.clear()
            handlers.update(
                {
                    1: toggle_pet,
                    2: open_note,
                    3: toggle_pomodoro,
                    4: toggle_model_edit,
                    5: open_launcher_panel,
                }
            )
            mapping = [
                (1, data.get("hotkey_toggle_pet", "Ctrl+Shift+L")),
                (2, data.get("hotkey_note", "Ctrl+Shift+P")),
                (3, data.get("hotkey_pomodoro", "Ctrl+Shift+T")),
                (4, data.get("hotkey_model_edit", "Ctrl+Shift+M")),
                (5, data.get("hotkey_launcher_panel", "Ctrl+Shift+Space")),
            ]
            used = set()
            for hotkey_id, text in mapping:
                parsed = parse_hotkey(str(text))
                if not parsed:
                    logging.warning("hotkey parse failed: %s", text)
                    continue
                modifiers, key = parsed
                if (modifiers, key) in used:
                    logging.warning("hotkey conflict: %s", text)
                    continue
                used.add((modifiers, key))
                if not hotkey_manager.register(hotkey_id, modifiers, key):
                    logging.warning("hotkey register failed: %s", text)
                else:
                    logging.info("hotkey registered: %s", text)

            # launcher item hotkeys
            for item in launcher_manager.get_all():
                if not isinstance(item, dict):
                    continue
                hotkey_text = str(item.get("hotkey", "")).strip()
                if not hotkey_text:
                    continue
                parsed = parse_hotkey(hotkey_text)
                if not parsed:
                    logging.warning("launcher hotkey parse failed: %s", hotkey_text)
                    continue
                modifiers, key = parsed
                if (modifiers, key) in used:
                    logging.warning("launcher hotkey conflict: %s", hotkey_text)
                    continue
                hotkey_id = 1000 + int(item.get("id", 0))
                handlers[hotkey_id] = lambda launcher_id=int(item.get("id", 0)): bridge.executeLauncher(launcher_id)
                used.add((modifiers, key))
                if not hotkey_manager.register(hotkey_id, modifiers, key):
                    logging.warning("launcher hotkey register failed: %s", hotkey_text)
                else:
                    logging.info("launcher hotkey registered: %s", hotkey_text)

    register_hotkeys(settings.get_settings())
    bridge.settingsUpdated.connect(register_hotkeys)
    bridge.launchersUpdated.connect(lambda _data: register_hotkeys(settings.get_settings()))
    app.aboutToQuit.connect(hotkey_manager.unregister_all)
    app.aboutToQuit.connect(plugin_manager.shutdown)

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
        now = time.time()
        update_mood(state, now)
        plugin_state = {
            "status": state.status,
            "idle_ms": state.idle_ms,
            "focus_seconds_today": state.focus_seconds_today,
            "input_type": state.input_type,
            "window_title": state.window_title,
        }
        plugin_manager.on_state(plugin_state)
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

        plugin_manager.on_tick(plugin_state, now)
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
            "typing": texts.get_list(
                "passive.interaction.typing",
                ["加油！", "键盘敲得很有节奏～", "专注模式已开启！"],
            ),
            "idle": texts.get_list(
                "passive.interaction.idle",
                ["我有点困了，要不要休息一下？", "休息片刻再继续吧。", "记得活动下肩膀～"],
            ),
            "switch": texts.get_list(
                "passive.interaction.switch",
                ["专心一点哦。", "任务切换太快会分神～", "先把这一件做完？"],
            ),
            "browser": texts.get_list(
                "passive.interaction.browser",
                ["需要我帮你查找资料吗？", "记得把要点记下来～", "浏览结束记得回到任务哦。"],
            ),
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
                template = texts.get_text(
                    "system.pomodoro_complete",
                    "完成番茄专注，获得好感 +{reward}",
                )
                bridge.push_passive_message(template.format(reward=reward))
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
