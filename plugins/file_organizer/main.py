from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QObject, Signal, Slot, QThread, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)


DEFAULT_CATEGORIES = ["文档", "图片", "视频", "音乐", "压缩包", "程序", "其他", "待分类"]
DEFAULT_RULES = {
    "文档": [".pdf", ".doc", ".docx", ".txt", ".md", ".ppt", ".pptx", ".xls", ".xlsx"],
    "图片": [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"],
    "视频": [".mp4", ".mov", ".mkv", ".avi", ".flv", ".wmv"],
    "音乐": [".mp3", ".flac", ".aac", ".wav", ".ogg"],
    "压缩包": [".zip", ".rar", ".7z", ".tar", ".gz"],
    "程序": [".exe", ".msi", ".bat", ".cmd", ".sh", ".app", ".apk"],
}
DEFAULT_OPTIONS = {
    "create_subfolders": True,
    "overwrite": False,
    "include_subdirs": False,
    "only_existing_folders": False,
}


def _read_json(path: str, fallback: Any) -> Any:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return fallback


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _ensure_list(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, list) and value:
        return [str(item) for item in value]
    return list(fallback)


def _safe_name(name: str) -> str:
    return re.sub(r"[\\/:*?\"<>|]+", "_", name).strip() or "unknown"


@dataclass
class PreviewRow:
    file: str
    category: str
    target: str
    status: str


class PreviewTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._headers = ["文件", "分类", "目标", "状态"]
        self._rows: list[PreviewRow] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self._rows[index.row()]
        column = index.column()
        if column == 0:
            return row.file
        if column == 1:
            return row.category
        if column == 2:
            return row.target
        if column == 3:
            return row.status
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self._headers[section]
        return None

    def set_rows(self, rows: list[PreviewRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


class HistoryTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._headers = ["时间", "源目录", "总数", "已移动", "失败", "待分类"]
        self._rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self._rows[index.row()]
        column = index.column()
        if column == 0:
            ts = row.get("ts", 0)
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        if column == 1:
            return row.get("source_dir", "")
        summary = row.get("summary", {})
        if column == 2:
            return summary.get("total", 0)
        if column == 3:
            return summary.get("moved", 0)
        if column == 4:
            return summary.get("failed", 0)
        if column == 5:
            return summary.get("review", 0)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self._headers[section]
        return None

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

class OrganizerWorker(QObject):
    progress = Signal(int, int, int, int)
    previewReady = Signal(list)
    finished = Signal(dict, list)
    error = Signal(str)

    def __init__(
        self,
        mode: str,
        source_dir: str,
        options: dict,
        categories: list[str],
        rules: dict[str, list[str]],
        review_folder: str,
        ai_enabled: bool,
        ai_call: Callable[[str], str] | None,
        ai_batch_size: int = 60,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.source_dir = source_dir
        self.options = options
        self.categories = categories
        self.rules = rules
        self.review_folder = review_folder
        self.ai_enabled = ai_enabled
        self.ai_call = ai_call
        self.ai_batch_size = max(10, int(ai_batch_size))

    @Slot()
    def run(self) -> None:
        try:
            files = self._scan_files()
            total = len(files)
            moved = 0
            failed = 0
            self.progress.emit(0, total, moved, failed)
            plan, preview_rows, review_count = self._classify_files(files)
            self.previewReady.emit(preview_rows)
            if self.mode != "run":
                summary = {"total": total, "moved": 0, "failed": 0, "review": review_count}
                self.finished.emit(summary, [])
                return
            moves: list[dict] = []
            for category, items in plan.items():
                for file_path in items:
                    target_path = self._build_target_path(category, file_path)
                    try:
                        if not self.options.get("overwrite", False):
                            if os.path.exists(target_path):
                                review_path = self._build_target_path(self.review_folder, file_path)
                                if os.path.exists(review_path):
                                    failed += 1
                                    self.progress.emit(0, total, moved, failed)
                                    continue
                                os.makedirs(os.path.dirname(review_path), exist_ok=True)
                                shutil.move(file_path, review_path)
                                moves.append({"from": file_path, "to": review_path})
                                moved += 1
                                self.progress.emit(0, total, moved, failed)
                                continue
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        shutil.move(file_path, target_path)
                        moves.append({"from": file_path, "to": target_path})
                        moved += 1
                    except Exception:
                        failed += 1
                    self.progress.emit(0, total, moved, failed)
            summary = {"total": total, "moved": moved, "failed": failed, "review": review_count}
            self.finished.emit(summary, moves)
        except Exception as exc:
            self.error.emit(str(exc))

    def _scan_files(self) -> list[str]:
        if not os.path.isdir(self.source_dir):
            return []
        files: list[str] = []
        if self.options.get("include_subdirs", False):
            for root, _, filenames in os.walk(self.source_dir):
                for name in filenames:
                    files.append(os.path.join(root, name))
        else:
            for name in os.listdir(self.source_dir):
                path = os.path.join(self.source_dir, name)
                if os.path.isfile(path):
                    files.append(path)
        return files

    def _classify_files(self, files: list[str]) -> tuple[dict[str, list[str]], list[PreviewRow], int]:
        ext_map = {}
        for category, exts in self.rules.items():
            for ext in exts:
                ext_map[ext.lower()] = category
        plan: dict[str, list[str]] = {category: [] for category in self.categories}
        unknown: list[str] = []
        for path in files:
            _, ext = os.path.splitext(path)
            category = ext_map.get(ext.lower())
            if category:
                plan.setdefault(category, []).append(path)
            else:
                unknown.append(path)
        if unknown:
            ai_result = {}
            if self.ai_enabled and self.ai_call:
                ai_result = self._classify_with_ai(unknown)
            for path in unknown:
                category = ai_result.get(path)
                if not category:
                    category = self.review_folder
                plan.setdefault(category, []).append(path)
        preview_rows: list[PreviewRow] = []
        review_count = 0
        for category, items in plan.items():
            for path in items:
                target = self._build_target_path(category, path)
                status = "待移动" if self.mode == "run" else "预览"
                if category == self.review_folder:
                    status = "待分类"
                    review_count += 1
                preview_rows.append(
                    PreviewRow(
                        file=os.path.relpath(path, self.source_dir),
                        category=category,
                        target=os.path.relpath(target, self.source_dir),
                        status=status,
                    )
                )
        preview_rows.sort(key=lambda row: row.file.lower())
        return plan, preview_rows, review_count

    def _classify_with_ai(self, files: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for start in range(0, len(files), self.ai_batch_size):
            chunk = files[start : start + self.ai_batch_size]
            prompt, id_map = self._build_prompt(chunk)
            reply = self.ai_call(prompt) if self.ai_call else ""
            mapping = self._parse_ai_reply(reply)
            for category, ids in mapping.items():
                for item_id in ids:
                    path = id_map.get(item_id)
                    if path and path not in result:
                        result[path] = category
            for path in chunk:
                if path not in result:
                    result[path] = self.review_folder
        return result

    def _build_prompt(self, files: list[str]) -> tuple[str, dict[str, str]]:
        id_map: dict[str, str] = {}
        lines = []
        for idx, path in enumerate(files, start=1):
            rel = os.path.relpath(path, self.source_dir)
            item_id = f"f{idx}"
            id_map[item_id] = path
            lines.append(f"- {item_id} | {rel}")
        categories = "、".join(self.categories)
        prompt = (
            "请根据文件名和扩展名，将以下文件分类到指定类别中。\n"
            f"类别：{categories}\n"
            "若无法判断，请归入“待分类”。\n\n"
            "文件列表：\n"
            + "\n".join(lines)
            + "\n\n"
            '返回 JSON 格式：{"分类": ["文件ID1", "文件ID2", ...]}\n'
            "仅返回 JSON。"
        )
        return prompt, id_map

    def _parse_ai_reply(self, reply: str) -> dict[str, list[str]]:
        if not reply:
            return {}
        text = reply.strip()
        if not text.startswith("{"):
            match = re.search(r"\{.*\}", text, re.S)
            if match:
                text = match.group(0)
        try:
            data = json.loads(text)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        cleaned: dict[str, list[str]] = {}
        for key, value in data.items():
            if not isinstance(value, list):
                continue
            items = [str(item).strip() for item in value if str(item).strip()]
            if items:
                cleaned[str(key).strip()] = items
        return cleaned

    def _build_target_path(self, category: str, file_path: str) -> str:
        base_name = os.path.basename(file_path)
        if category == self.review_folder:
            folder = os.path.join(self.source_dir, _safe_name(self.review_folder))
            return os.path.join(folder, base_name)
        if self.options.get("create_subfolders", True):
            folder = os.path.join(self.source_dir, _safe_name(category))
            return os.path.join(folder, base_name)
        return os.path.join(self.source_dir, base_name)


class CategorySuggestWorker(QObject):
    finished = Signal(list)
    error = Signal(str)

    def __init__(
        self,
        source_dir: str,
        include_subdirs: bool,
        ai_call: Callable[[str], str] | None,
        sample_limit: int = 120,
    ) -> None:
        super().__init__()
        self.source_dir = source_dir
        self.include_subdirs = include_subdirs
        self.ai_call = ai_call
        self.sample_limit = max(10, int(sample_limit))
        self._ext_set: set[str] = set()
        self._ext_examples: dict[str, list[str]] = {}
        self._folder_names: list[str] = []

    @Slot()
    def run(self) -> None:
        try:
            ext_map = self._scan_files()
            if not ext_map:
                self.finished.emit([])
                return
            prompt = self._build_prompt(ext_map)
            reply = self.ai_call(prompt) if self.ai_call else ""
            categories = self._parse_reply(reply, self._ext_set)
            self.finished.emit(categories)
        except Exception as exc:
            self.error.emit(str(exc))

    def _scan_files(self) -> dict[str, list[str]]:
        if not os.path.isdir(self.source_dir):
            return {}
        ext_map: dict[str, list[str]] = {}
        self._folder_names = [
            name
            for name in os.listdir(self.source_dir)
            if os.path.isdir(os.path.join(self.source_dir, name))
        ]
        if self.include_subdirs:
            for root, _, filenames in os.walk(self.source_dir):
                for name in filenames:
                    rel = os.path.relpath(os.path.join(root, name), self.source_dir)
                    ext = os.path.splitext(name)[1].lower() or "(no_ext)"
                    ext_map.setdefault(ext, []).append(rel)
        else:
            for name in os.listdir(self.source_dir):
                path = os.path.join(self.source_dir, name)
                if os.path.isfile(path):
                    ext = os.path.splitext(name)[1].lower() or "(no_ext)"
                    ext_map.setdefault(ext, []).append(name)
        trimmed: dict[str, list[str]] = {}
        for ext, items in ext_map.items():
            trimmed[ext] = items[:5]
        self._ext_set = set(trimmed.keys())
        self._ext_examples = trimmed
        return trimmed

    def _build_prompt(self, ext_map: dict[str, list[str]]) -> str:
        ext_stats = []
        for ext, items in sorted(ext_map.items(), key=lambda item: item[0]):
            ext_stats.append(f"{ext}({len(items)})")
        examples = []
        for ext, items in sorted(ext_map.items(), key=lambda item: item[0]):
            example = "、".join(items[:5])
            examples.append(f"- {ext}: {example}")
        return (
            "请基于扩展名与示例文件名，推断合理的分类类别（中文短语）。\n"
            "不要生成与列表无关的类别，不要包含“待分类”。\n"
            "如果已有文件夹名称可复用，请优先使用已有名称。\n"
            "仅返回 JSON 数组，元素格式：\n"
            "[{\"category\":\"文档\",\"exts\":[\".pdf\",\".docx\"]},\n"
            " {\"category\":\"设计素材\",\"ext\":\".psd\"}]\n\n"
            f"扩展名统计：{', '.join(ext_stats)}\n"
            f"已有文件夹：{', '.join(self._folder_names) if self._folder_names else '无'}\n"
            "示例文件：\n"
            f"{os.linesep.join(examples)}\n"
        )

    def _parse_reply(self, reply: str, ext_set: set[str]) -> list[dict]:
        if not reply:
            return []
        text = reply.strip()
        if not text.startswith("["):
            match = re.search(r"\[.*\]", text, re.S)
            if match:
                text = match.group(0)
        try:
            data = json.loads(text)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        cleaned: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("category", "") or item.get("name", "")).strip()
            if not name or name == "待分类":
                continue
            exts = item.get("exts", [])
            if not isinstance(exts, list):
                exts = []
            ext_single = item.get("ext")
            if ext_single and isinstance(ext_single, (str, int, float)):
                exts.append(ext_single)
            cleaned_exts = []
            for ext in exts:
                value = str(ext).strip().lower()
                if not value:
                    continue
                if value not in ext_set and value != "(no_ext)":
                    continue
                if value not in cleaned_exts:
                    cleaned_exts.append(value)
            if not cleaned_exts:
                continue
            if any(existing.get("name") == name for existing in cleaned):
                continue
            cleaned.append({"name": name, "exts": cleaned_exts})
        return cleaned

class Plugin:
    def __init__(self, context) -> None:
        self.context = context
        self.config_path = context.get_data_path("config.json")
        self.history_path = context.get_data_path("history.json")
        self.log_path = context.get_data_path("plugin.log")
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8"):
                pass
        except Exception:
            pass
        self.config = self._load_config()
        self.history: list[dict] = _read_json(self.history_path, [])
        self._thread: QThread | None = None
        self._worker: OrganizerWorker | None = None
        self._ai_thread: QThread | None = None
        self._ai_worker: CategorySuggestWorker | None = None
        self._build_ui_state()

    def on_load(self, context) -> None:
        self.context.info("file organizer plugin loaded")

    def on_unload(self) -> None:
        self._stop_worker()
        self._stop_ai_worker()

    def _notify(self, message: str) -> None:
        if not message:
            return
        self.context.info(message)
        bridge = getattr(self.context, "bridge", None)
        if bridge and hasattr(bridge, "push_passive_message"):
            def _emit() -> None:
                bridge.push_passive_message(message)
                self.context.block_passive(2.5)

            QTimer.singleShot(0, _emit)

    def get_panel(self, parent=None):
        panel = QDialog(None)
        panel.setWindowTitle("文件整理插件")
        panel.setMinimumSize(920, 620)
        panel.setWindowModality(Qt.NonModal)
        flags = Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint
        flags |= Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
        panel.setWindowFlags(flags)
        panel.setObjectName("fileOrganizerPanel")
        panel.setStyleSheet(
            """
            QWidget#fileOrganizerPanel {
                background-color: #f7f4ee;
                color: #2d2a24;
            }
            QGroupBox {
                border: 1px solid #d8d2c4;
                border-radius: 6px;
                margin-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
            QLineEdit, QComboBox, QListWidget, QTableView {
                background-color: #ffffff;
                border: 1px solid #d2c9b8;
                border-radius: 4px;
                padding: 4px 6px;
            }
            QPushButton {
                background-color: #3a6ea5;
                color: #ffffff;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:disabled {
                background-color: #b7c5d4;
            }
            QCheckBox {
                padding: 2px;
            }
            QHeaderView::section {
                background-color: #ede7dc;
                padding: 6px;
                border: 1px solid #d8d2c4;
            }
            """
        )
        main_layout = QVBoxLayout(panel)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        top_group = QGroupBox("整理配置")
        top_layout = QVBoxLayout(top_group)
        top_layout.setSpacing(8)

        folder_row = QHBoxLayout()
        folder_label = QLabel("源文件夹")
        self.folder_edit = QLineEdit()
        browse_btn = QPushButton("选择...")
        browse_btn.clicked.connect(self._choose_folder)
        folder_row.addWidget(folder_label)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse_btn)
        top_layout.addLayout(folder_row)

        ai_row = QHBoxLayout()
        self.ai_enabled = QCheckBox("启用 AI 分类")
        self.provider_combo = QComboBox()
        self.model_combo = QComboBox()
        ai_row.addWidget(self.ai_enabled)
        ai_row.addWidget(QLabel("AI Provider"))
        ai_row.addWidget(self.provider_combo, 1)
        ai_row.addWidget(QLabel("AI Model"))
        ai_row.addWidget(self.model_combo, 1)
        top_layout.addLayout(ai_row)

        options_row = QHBoxLayout()
        self.create_subfolders = QCheckBox("创建子文件夹")
        self.overwrite_files = QCheckBox("覆盖同名文件")
        self.include_subdirs = QCheckBox("分析子目录")
        self.only_existing_folders = QCheckBox("只使用已有文件夹，不新增类别")
        options_row.addWidget(self.create_subfolders)
        options_row.addWidget(self.overwrite_files)
        options_row.addWidget(self.include_subdirs)
        options_row.addWidget(self.only_existing_folders)
        options_row.addStretch(1)
        top_layout.addLayout(options_row)

        categories_row = QHBoxLayout()
        categories_label = QLabel("分类类别")
        self.categories_list = QListWidget()
        self.categories_list.setEditTriggers(QListWidget.DoubleClicked | QListWidget.EditKeyPressed)
        categories_buttons = QVBoxLayout()
        add_btn = QPushButton("新增")
        remove_btn = QPushButton("删除")
        self.ai_suggest_btn = QPushButton("AI 生成")
        add_btn.clicked.connect(self._add_category)
        remove_btn.clicked.connect(self._remove_category)
        self.ai_suggest_btn.clicked.connect(self._on_ai_suggest_categories)
        categories_buttons.addWidget(add_btn)
        categories_buttons.addWidget(remove_btn)
        categories_buttons.addWidget(self.ai_suggest_btn)
        categories_buttons.addStretch(1)
        categories_row.addWidget(categories_label)
        categories_row.addWidget(self.categories_list, 1)
        categories_row.addLayout(categories_buttons)
        top_layout.addLayout(categories_row)

        main_layout.addWidget(top_group)

        splitter = QSplitter(Qt.Horizontal)
        preview_group = QGroupBox("整理预览")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_model = PreviewTableModel()
        self.preview_table = QTableView()
        self.preview_table.setModel(self.preview_model)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        preview_layout.addWidget(self.preview_table)

        history_group = QGroupBox("整理历史")
        history_layout = QVBoxLayout(history_group)
        self.history_model = HistoryTableModel()
        self.history_table = QTableView()
        self.history_table.setModel(self.history_model)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        history_layout.addWidget(self.history_table)

        splitter.addWidget(preview_group)
        splitter.addWidget(history_group)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter, 1)

        action_row = QHBoxLayout()
        self.ai_preview_btn = QPushButton("开始AI分类")
        self.preview_btn = QPushButton("预览")
        self.organize_btn = QPushButton("开始整理")
        self.undo_btn = QPushButton("撤销上一次")
        self.refresh_history_btn = QPushButton("刷新历史")
        self.clear_history_btn = QPushButton("清除历史")
        action_row.addWidget(self.ai_preview_btn)
        action_row.addWidget(self.preview_btn)
        action_row.addWidget(self.organize_btn)
        action_row.addWidget(self.undo_btn)
        action_row.addWidget(self.refresh_history_btn)
        action_row.addWidget(self.clear_history_btn)
        action_row.addStretch(1)
        main_layout.addLayout(action_row)

        status_row = QHBoxLayout()
        self.status_label = QLabel("等待操作")
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.progress_bar, 2)
        main_layout.addLayout(status_row)

        self.preview_btn.clicked.connect(self._on_preview)
        self.organize_btn.clicked.connect(self._on_organize)
        self.undo_btn.clicked.connect(self._on_undo)
        self.refresh_history_btn.clicked.connect(self._reload_history)
        self.clear_history_btn.clicked.connect(self._clear_history)
        self.ai_preview_btn.clicked.connect(self._on_ai_preview)
        self.ai_enabled.toggled.connect(self._save_config_from_ui)
        self.provider_combo.currentIndexChanged.connect(self._save_config_from_ui)
        self.model_combo.currentIndexChanged.connect(self._save_config_from_ui)
        self.folder_edit.textChanged.connect(self._save_config_from_ui)
        self.create_subfolders.toggled.connect(self._save_config_from_ui)
        self.overwrite_files.toggled.connect(self._save_config_from_ui)
        self.include_subdirs.toggled.connect(self._save_config_from_ui)
        self.only_existing_folders.toggled.connect(self._save_config_from_ui)
        self.categories_list.itemChanged.connect(self._save_config_from_ui)

        self._apply_config_to_ui()
        self._reload_history()
        return panel

    def _build_ui_state(self) -> None:
        self.folder_edit = None
        self.ai_enabled = None
        self.provider_combo = None
        self.model_combo = None
        self.create_subfolders = None
        self.overwrite_files = None
        self.include_subdirs = None
        self.only_existing_folders = None
        self.categories_list = None
        self.ai_suggest_btn = None
        self.ai_preview_btn = None
        self.clear_history_btn = None
        self.preview_btn = None
        self.organize_btn = None
        self.undo_btn = None
        self.refresh_history_btn = None
        self.status_label = None
        self.progress_bar = None
        self.preview_model = None
        self.preview_table = None
        self.history_model = None
        self.history_table = None

    def _load_config(self) -> dict:
        config = _read_json(self.config_path, {})
        categories = _ensure_list(config.get("categories"), DEFAULT_CATEGORIES)
        if "待分类" not in categories:
            categories.append("待分类")
        rules = config.get("rules")
        if not isinstance(rules, dict):
            rules = {}
        merged_rules = {}
        for category in categories:
            if category in rules and isinstance(rules[category], list):
                merged_rules[category] = [str(item) for item in rules[category]]
            elif category in DEFAULT_RULES:
                merged_rules[category] = list(DEFAULT_RULES[category])
            else:
                merged_rules[category] = []
        options = config.get("options")
        if not isinstance(options, dict):
            options = {}
        merged_options = DEFAULT_OPTIONS.copy()
        merged_options.update({k: bool(v) for k, v in options.items() if k in merged_options})
        merged_options["only_existing_folders"] = bool(options.get("only_existing_folders", False))
        ai_provider = str(config.get("ai_provider", "")).strip()
        ai_model = str(config.get("ai_model", "")).strip()
        source_dir = str(config.get("source_dir", "")).strip()
        review_folder = str(config.get("review_folder_name", "待分类")).strip() or "待分类"
        return {
            "source_dir": source_dir,
            "ai_provider": ai_provider,
            "ai_model": ai_model,
            "categories": categories,
            "rules": merged_rules,
            "options": merged_options,
            "review_folder_name": review_folder,
            "ai_enabled": bool(config.get("ai_enabled", True)),
        }

    def _save_config(self) -> None:
        _write_json(self.config_path, self.config)

    def _apply_config_to_ui(self) -> None:
        if not self.folder_edit:
            return
        self.folder_edit.setText(self.config.get("source_dir", ""))
        self.ai_enabled.setChecked(bool(self.config.get("ai_enabled", True)))
        self.create_subfolders.setChecked(bool(self.config["options"].get("create_subfolders", True)))
        self.overwrite_files.setChecked(bool(self.config["options"].get("overwrite", False)))
        self.include_subdirs.setChecked(bool(self.config["options"].get("include_subdirs", False)))
        self.only_existing_folders.setChecked(bool(self.config["options"].get("only_existing_folders", False)))
        self._load_ai_options()
        self.categories_list.blockSignals(True)
        self.categories_list.clear()
        for category in self.config.get("categories", []):
            item = QListWidgetItem(category)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.categories_list.addItem(item)
        self.categories_list.blockSignals(False)

    def _load_ai_options(self) -> None:
        self.provider_combo.blockSignals(True)
        self.model_combo.blockSignals(True)
        self.provider_combo.clear()
        self.model_combo.clear()
        providers = []
        settings = None
        if hasattr(self.context, "settings"):
            settings = self.context.settings
        if settings:
            data = settings.get_settings()
            providers = data.get("ai_providers", [])
        enabled_providers = [p for p in providers if isinstance(p, dict) and p.get("enabled", True)]
        if not enabled_providers:
            enabled_providers = providers
        for item in enabled_providers:
            name = str(item.get("name", "OpenAI兼容"))
            self.provider_combo.addItem(name)
        models = []
        for item in enabled_providers:
            model = str(item.get("model", "")).strip()
            if model and model not in models:
                models.append(model)
        for model in models:
            self.model_combo.addItem(model)
        provider_target = self.config.get("ai_provider", "")
        if provider_target:
            idx = self.provider_combo.findText(provider_target)
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)
        model_target = self.config.get("ai_model", "")
        if model_target:
            idx = self.model_combo.findText(model_target)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
        self.provider_combo.blockSignals(False)
        self.model_combo.blockSignals(False)

    def _collect_config_from_ui(self) -> dict:
        categories = []
        for i in range(self.categories_list.count()):
            text = self.categories_list.item(i).text().strip()
            if text and text not in categories:
                categories.append(text)
        if "待分类" not in categories:
            categories.append("待分类")
        rules = self.config.get("rules", {})
        merged_rules = {}
        for category in categories:
            if category in rules and isinstance(rules[category], list):
                merged_rules[category] = rules[category]
            elif category in DEFAULT_RULES:
                merged_rules[category] = list(DEFAULT_RULES[category])
            else:
                merged_rules[category] = []
        return {
            "source_dir": self.folder_edit.text().strip(),
            "ai_provider": self.provider_combo.currentText().strip(),
            "ai_model": self.model_combo.currentText().strip(),
            "categories": categories,
            "rules": merged_rules,
            "options": {
                "create_subfolders": self.create_subfolders.isChecked(),
                "overwrite": self.overwrite_files.isChecked(),
                "include_subdirs": self.include_subdirs.isChecked(),
                "only_existing_folders": self.only_existing_folders.isChecked(),
            },
            "review_folder_name": "待分类",
            "ai_enabled": self.ai_enabled.isChecked(),
        }

    def _save_config_from_ui(self) -> None:
        if not self.folder_edit:
            return
        self.config = self._collect_config_from_ui()
        self._save_config()

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(None, "选择需要整理的文件夹")
        if folder:
            self.folder_edit.setText(folder)

    def _add_category(self) -> None:
        item = QListWidgetItem("新分类")
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.categories_list.addItem(item)
        self.categories_list.setCurrentItem(item)
        self.categories_list.editItem(item)

    def _remove_category(self) -> None:
        item = self.categories_list.currentItem()
        if not item:
            return
        if item.text().strip() == "待分类":
            QMessageBox.information(None, "提示", "“待分类”为系统保留分类，不能删除。")
            return
        row = self.categories_list.row(item)
        self.categories_list.takeItem(row)

    def _on_ai_suggest_categories(self) -> None:
        if self._ai_thread:
            QMessageBox.information(None, "提示", "AI 分类生成进行中，请稍候。")
            return
        source_dir = self.folder_edit.text().strip()
        if not source_dir or not os.path.isdir(source_dir):
            QMessageBox.warning(None, "提示", "请选择有效的源文件夹。")
            return
        ai_call = self._get_ai_call()
        if not ai_call:
            QMessageBox.warning(None, "提示", "AI 未配置，请先在 AI 设置中填写 API Key。")
            return
        self._notify("让我看看这些文件，马上给你想一套分类。")
        include_subdirs = bool(self.include_subdirs.isChecked())
        self._ai_thread = QThread()
        self._ai_worker = CategorySuggestWorker(
            source_dir=source_dir,
            include_subdirs=include_subdirs,
            ai_call=ai_call,
        )
        self._ai_worker.moveToThread(self._ai_thread)
        self._ai_thread.started.connect(self._ai_worker.run)
        self._ai_worker.finished.connect(self._apply_ai_categories, Qt.QueuedConnection)
        self._ai_worker.error.connect(self._on_ai_suggest_error, Qt.QueuedConnection)
        self._ai_thread.finished.connect(self._cleanup_ai_worker, Qt.QueuedConnection)
        self._ai_thread.start()
        self.status_label.setText("AI 正在生成分类...")
        self.context.info("ai category generation started")

    def _on_ai_suggest_error(self, message: str) -> None:
        self.context.error(f"ai category error: {message}")
        self._notify("咦，分类没生成出来，可能是 AI 配置有点问题。")
        QMessageBox.critical(None, "AI 分类生成失败", message)
        QTimer.singleShot(0, self._stop_ai_worker)

    def _apply_ai_categories(self, categories: list[dict]) -> None:
        QTimer.singleShot(0, self._stop_ai_worker)
        cleaned = []
        rules = {}
        source_dir = self.folder_edit.text().strip()
        existing_folders = []
        if source_dir and os.path.isdir(source_dir):
            existing_folders = [
                name
                for name in os.listdir(source_dir)
                if os.path.isdir(os.path.join(source_dir, name))
            ]
        only_existing = bool(self.only_existing_folders.isChecked())
        ai_map: dict[str, list[str]] = {}
        for item in categories:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name or name == "待分类":
                continue
            exts = item.get("exts", [])
            if not isinstance(exts, list) or not exts:
                continue
            ai_map[name] = [str(ext).strip().lower() for ext in exts if str(ext).strip()]
        for name in existing_folders:
            if name and name != "待分类" and name not in cleaned:
                cleaned.append(name)
                rules[name] = ai_map.get(name, [])
        if not only_existing:
            for name, exts in ai_map.items():
                if name in cleaned:
                    continue
                cleaned.append(name)
                rules[name] = exts
        if not cleaned:
            QMessageBox.information(None, "提示", "未生成有效分类，请检查源目录或 AI 配置。")
            self.status_label.setText("AI 分类生成失败")
            self._notify("这次没想出合适的分类，我们换个目录或检查下配置吧。")
            return
        if "待分类" not in cleaned:
            cleaned.append("待分类")
        rules.setdefault("待分类", [])
        self.config["categories"] = cleaned
        self.config["rules"] = rules
        self._save_config()
        self.categories_list.blockSignals(True)
        self.categories_list.clear()
        for category in cleaned:
            item = QListWidgetItem(category)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.categories_list.addItem(item)
        self.categories_list.blockSignals(False)
        self.status_label.setText("AI 分类已生成")
        self._notify("分类想好了，已经整理到列表里啦。")

    def _on_ai_preview(self) -> None:
        if not self.ai_enabled.isChecked():
            self.ai_enabled.setChecked(True)
        self._notify("我先帮你看看 AI 会怎么分。")
        self._start_worker("preview")

    def _on_preview(self) -> None:
        self._notify("我先给你预览一下，不会动文件的。")
        self._start_worker("preview")

    def _on_organize(self) -> None:
        self._notify("我开始整理啦，过程里会告诉你进度。")
        self._start_worker("run")

    def _on_undo(self) -> None:
        if not self.history:
            QMessageBox.information(None, "提示", "暂无可撤销的整理记录。")
            return
        last = self.history[-1]
        moves = last.get("moves", [])
        source_dir = last.get("source_dir", "")
        if not moves:
            QMessageBox.information(None, "提示", "记录中没有可撤销的移动项。")
            return
        review_folder = os.path.join(source_dir, _safe_name("待分类"))
        os.makedirs(review_folder, exist_ok=True)
        undone = 0
        failed = 0
        for item in reversed(moves):
            origin = item.get("from")
            current = item.get("to")
            if not origin or not current or not os.path.exists(current):
                continue
            if os.path.exists(origin):
                failed += 1
                continue
            try:
                os.makedirs(os.path.dirname(origin), exist_ok=True)
                shutil.move(current, origin)
                undone += 1
            except Exception:
                failed += 1
        self.context.info(f"undo completed: moved={undone} failed={failed}")
        QMessageBox.information(None, "撤销完成", f"已撤销 {undone} 项，失败 {failed} 项。")
        self._notify("上一次整理我帮你撤回啦。")
        self.history.pop()
        _write_json(self.history_path, self.history)
        self._reload_history()

    def _reload_history(self) -> None:
        self.history = _read_json(self.history_path, [])
        if self.history_model:
            self.history_model.set_rows(self.history)

    def _clear_history(self) -> None:
        confirm = QMessageBox.question(
            None,
            "清除历史",
            "确认清除所有整理历史记录？",
        )
        if confirm != QMessageBox.Yes:
            return
        self.history = []
        _write_json(self.history_path, self.history)
        self._reload_history()
        self.context.info("history cleared")
        self._notify("历史记录我清空了。")

    def _start_worker(self, mode: str) -> None:
        if self._thread:
            QMessageBox.information(None, "提示", "已有整理任务在运行，请等待完成。")
            return
        config = self._collect_config_from_ui()
        source_dir = config.get("source_dir", "")
        if not source_dir or not os.path.isdir(source_dir):
            QMessageBox.warning(None, "提示", "请选择有效的源文件夹。")
            return
        base_dir = getattr(self.context, "base_dir", "")
        if base_dir:
            base_dir = os.path.abspath(base_dir)
            target_dir = os.path.abspath(source_dir)
            if os.path.commonpath([base_dir, target_dir]) == base_dir:
                QMessageBox.warning(
                    None,
                    "提示",
                    "为避免影响主程序运行，禁止整理程序目录或其子目录。",
                )
                self.context.warn(f"blocked organizing app directory: {target_dir}")
                return
        ai_call = self._get_ai_call()
        self._thread = QThread()
        self._worker = OrganizerWorker(
            mode=mode,
            source_dir=source_dir,
            options=config["options"],
            categories=config["categories"],
            rules=config["rules"],
            review_folder=config.get("review_folder_name", "待分类"),
            ai_enabled=config.get("ai_enabled", True),
            ai_call=ai_call,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.previewReady.connect(self._on_preview_ready, Qt.QueuedConnection)
        self._worker.progress.connect(self._on_progress, Qt.QueuedConnection)
        self._worker.finished.connect(
            lambda summary, moves: self._on_finished(mode, summary, moves),
            Qt.QueuedConnection,
        )
        self._worker.error.connect(self._on_error, Qt.QueuedConnection)
        self._thread.finished.connect(self._cleanup_worker, Qt.QueuedConnection)
        self._thread.start()
        self._set_busy(True)
        self.context.info(f"task started: mode={mode} source={source_dir}")

    def _get_ai_call(self) -> Callable[[str], str] | None:
        bridge = getattr(self.context, "bridge", None)
        ai_client = getattr(bridge, "_ai_client", None) if bridge else None
        if not ai_client:
            return None
        return lambda prompt: ai_client.call(prompt, 0, plugin_context=None)

    def _stop_worker(self) -> None:
        if not self._thread:
            return
        if QThread.currentThread() == self._thread:
            self._thread.quit()
            return
        self._thread.quit()
        self._thread.wait(2000)
        self._cleanup_worker()

    def _cleanup_worker(self) -> None:
        if self._worker:
            self._worker.deleteLater()
        if self._thread:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self._set_busy(False)

    def _stop_ai_worker(self) -> None:
        if not self._ai_thread:
            return
        if QThread.currentThread() == self._ai_thread:
            self._ai_thread.quit()
            return
        self._ai_thread.quit()
        self._ai_thread.wait(2000)
        self._cleanup_ai_worker()

    def _cleanup_ai_worker(self) -> None:
        if self._ai_worker:
            self._ai_worker.deleteLater()
        if self._ai_thread:
            self._ai_thread.deleteLater()
        self._ai_thread = None
        self._ai_worker = None

    def _set_busy(self, busy: bool) -> None:
        if not self.preview_btn:
            return
        if self.ai_suggest_btn:
            self.ai_suggest_btn.setEnabled(not busy)
        if self.ai_preview_btn:
            self.ai_preview_btn.setEnabled(not busy)
        self.preview_btn.setEnabled(not busy)
        self.organize_btn.setEnabled(not busy)
        self.undo_btn.setEnabled(not busy)
        self.refresh_history_btn.setEnabled(not busy)

    def _on_preview_ready(self, rows: list) -> None:
        if not self.preview_model:
            return
        self.preview_model.set_rows(rows)

    def _on_progress(self, scanned: int, total: int, moved: int, failed: int) -> None:
        if not self.progress_bar:
            return
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(min(total, moved + failed))
        self.status_label.setText(f"总数 {total} | 已移动 {moved} | 失败 {failed}")

    def _on_finished(self, mode: str, summary: dict, moves: list) -> None:
        if mode == "run":
            record = {
                "ts": int(time.time()),
                "source_dir": self.folder_edit.text().strip(),
                "options": self.config.get("options", {}),
                "moves": moves,
                "summary": summary,
            }
            self.history.append(record)
            _write_json(self.history_path, self.history)
            self._reload_history()
            self.context.info(f"task finished: moved={summary.get('moved')} failed={summary.get('failed')}")
            self._notify("整理完成啦，文件已经各就各位。")
        else:
            self.context.info("preview generated")
            self._notify("预览好了，先看看再决定要不要整理吧。")
        self.status_label.setText("完成")
        QTimer.singleShot(0, self._stop_worker)

    def _on_error(self, message: str) -> None:
        self.context.error(f"task error: {message}")
        QMessageBox.critical(None, "整理失败", message)
        self._notify("整理时出了一点小状况，可以看看日志哦。")
        QTimer.singleShot(0, self._stop_worker)


def create_plugin(context):
    return Plugin(context)
