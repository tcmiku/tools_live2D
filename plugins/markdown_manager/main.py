from __future__ import annotations

import json
import os
import threading
import time
import re
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QObject, Signal, QThread, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QMenu,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


DEFAULT_CONFIG = {
    "dirs": [],
    "ignore": [".git", "node_modules", ".venv"],
    "status_filters": ["全部", "草稿", "已校验", "已发布"],
    "sort_mode": "recent_updated",
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


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


@dataclass
class MarkdownItem:
    title: str
    path: str
    updated_at: float
    created_at: float
    status: str
    source: str
    pinned: bool = False


class MarkdownTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._headers = ["状态", "标题", "更新时间", "来源"]
        self._rows: list[MarkdownItem] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self._rows[index.row()]
        col = index.column()
        if col == 0:
            emoji_map = {
                "草稿": "⏳",
                "已校验": "✅",
                "已发布": "🚀",
            }
            emoji = emoji_map.get(row.status, "📄")
            return f"{emoji} {row.status}"
        if col == 1:
            return row.title
        if col == 2:
            return time.strftime("%Y-%m-%d", time.localtime(row.updated_at))
        if col == 3:
            return row.source
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self._headers[section]
        return None

    def set_rows(self, rows: list[MarkdownItem]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def get_row(self, row: int) -> MarkdownItem | None:
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]


class ScanWorker(QObject):
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, roots: list[str], ignores: list[str]) -> None:
        super().__init__()
        self.roots = roots
        self.ignores = set(ignores)

    def run(self) -> None:
        try:
            items = []
            for root in self.roots:
                for path in self._walk(root):
                    item = self._build_item(path)
                    if item:
                        items.append(item)
            self.finished.emit(items)
        except Exception as exc:
            self.error.emit(str(exc))

    def _walk(self, root: str) -> list[str]:
        results = []
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in self.ignores]
            for name in files:
                if name.lower().endswith(".md"):
                    results.append(os.path.join(base, name))
        return results

    def _build_item(self, path: str) -> MarkdownItem | None:
        try:
            stat = os.stat(path)
        except Exception:
            return None
        title = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#"):
                        title = line.lstrip("#").strip() or title
                        break
        except Exception:
            pass
        return MarkdownItem(
            title=title,
            path=path,
            updated_at=stat.st_mtime,
            created_at=stat.st_ctime,
            status="草稿",
            source=os.path.basename(os.path.dirname(path)),
        )


class Plugin:
    def __init__(self, context) -> None:
        self.context = context
        self.config_path = context.get_data_path("config.json")
        self.index_path = context.get_data_path("index.json")
        self.log_path = context.get_data_path("plugin.log")
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8"):
                pass
        except Exception:
            pass
        self.config = self._load_config()
        self.index: list[MarkdownItem] = self._load_index()
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._build_ui_state()

    def on_unload(self) -> None:
        self._stop_worker()

    def _notify(self, message: str) -> None:
        if not message:
            return
        self.context.info(message)
        bridge = getattr(self.context, "bridge", None)
        if bridge and hasattr(bridge, "push_passive_message"):
            def _emit() -> None:
                bridge.push_passive_message(message)
                self.context.block_passive(2.0)

            QTimer.singleShot(0, _emit)

    def get_panel(self, parent=None):
        panel = QDialog(None)
        panel.setWindowTitle("Markdown Manager")
        panel.setMinimumSize(920, 620)
        flags = Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint
        flags |= Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
        panel.setWindowFlags(flags)
        panel.setStyleSheet(
            """
            QWidget {
                background-color: #fafafa;
                color: #111111;
            }
            QLineEdit, QComboBox, QListWidget, QTableView {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 4px 6px;
            }
            QHeaderView::section {
                background-color: #f5f5f5;
                color: #111111;
                border: 1px solid #e5e7eb;
                padding: 6px 8px;
                font-weight: bold;
            }
            QTableView {
                gridline-color: #e5e7eb;
                alternate-background-color: #f5f5f5;
            }
            QTableView::item:selected {
                background-color: #e6e6e6;
                color: #111111;
            }
            QTabWidget::pane {
                border: 2px solid #111111;
                border-radius: 8px;
                padding: 4px;
            }
            QTabBar::tab {
                background-color: #ffffff;
                border: 2px solid #111111;
                border-bottom: none;
                padding: 6px 14px;
                margin-right: 6px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background-color: #111111;
                color: #ffffff;
            }
            QPushButton#primaryBtn {
                background-color: #2f6fed;
                color: #ffffff;
                border: 2px solid #111111;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton#successBtn {
                background-color: #1f9d63;
                color: #ffffff;
                border: 2px solid #111111;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton#dangerBtn {
                background-color: #d9534f;
                color: #ffffff;
                border: 2px solid #111111;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton#ghostBtn {
                background-color: #f3f4f6;
                color: #1f2937;
                border: 2px solid #111111;
                border-radius: 6px;
                padding: 6px 12px;
            }
            """
        )

        root = QVBoxLayout(panel)

        header = QHBoxLayout()
        title = QLabel("Markdown Manager")
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索标题 / 文件名...")
        self.quick_add_dir_btn = QPushButton("选择目录")
        self.settings_btn = QPushButton("设置")
        self.quick_add_dir_btn.setObjectName("primaryBtn")
        self.settings_btn.setObjectName("ghostBtn")
        header.addWidget(title)
        header.addWidget(self.search_box, 1)
        header.addWidget(self.quick_add_dir_btn)
        header.addWidget(self.settings_btn)
        root.addLayout(header)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        article_tab = QWidget()
        article_layout = QVBoxLayout(article_tab)
        filter_bar = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItems(self.config.get("status_filters", []))
        self.sort_filter = QComboBox()
        self.sort_filter.addItems(["最近更新", "最近创建", "置顶优先", "按来源"])
        self.scan_btn = QPushButton("扫描")
        self.scan_btn.setObjectName("successBtn")
        self.new_doc_btn = QPushButton("新建文档")
        self.new_doc_btn.setObjectName("primaryBtn")
        self.delete_doc_btn = QPushButton("删除文档")
        self.delete_doc_btn.setObjectName("dangerBtn")
        filter_bar.addWidget(self.status_filter)
        filter_bar.addWidget(self.sort_filter)
        filter_bar.addStretch(1)
        filter_bar.addWidget(self.new_doc_btn)
        filter_bar.addWidget(self.delete_doc_btn)
        filter_bar.addWidget(self.scan_btn)
        article_layout.addLayout(filter_bar)

        self.table_model = MarkdownTableModel()
        self.table = QTableView()
        self.table.setModel(self.table_model)
        self.table.horizontalHeader().setStretchLastSection(True)
        article_layout.addWidget(self.table, 1)

        tabs.addTab(article_tab, "文章")

        dir_tab = QWidget()
        dir_layout = QVBoxLayout(dir_tab)
        self.dir_list = QListWidget()
        self.add_dir_btn = QPushButton("添加目录")
        self.remove_dir_btn = QPushButton("移除目录")
        self.add_dir_btn.setObjectName("primaryBtn")
        self.remove_dir_btn.setObjectName("dangerBtn")
        self.ignore_edit = QLineEdit()
        self.ignore_edit.setPlaceholderText("忽略目录，用逗号分隔")
        dir_actions = QHBoxLayout()
        dir_actions.addWidget(self.add_dir_btn)
        dir_actions.addWidget(self.remove_dir_btn)
        dir_layout.addWidget(self.dir_list, 1)
        dir_layout.addLayout(dir_actions)
        dir_layout.addWidget(QLabel("忽略目录"))
        dir_layout.addWidget(self.ignore_edit)

        tabs.addTab(dir_tab, "目录")

        footer = QHBoxLayout()
        self.status_label = QLabel("等待扫描")
        footer.addWidget(self.status_label, 1)
        root.addLayout(footer)

        self.search_box.textChanged.connect(self._apply_filters)
        self.status_filter.currentIndexChanged.connect(self._apply_filters)
        self.sort_filter.currentIndexChanged.connect(self._apply_filters)
        self.scan_btn.clicked.connect(self._start_scan)
        self.new_doc_btn.clicked.connect(self._create_new_doc)
        self.delete_doc_btn.clicked.connect(self._delete_selected)
        self.add_dir_btn.clicked.connect(self._add_dir)
        self.remove_dir_btn.clicked.connect(self._remove_dir)
        self.ignore_edit.textChanged.connect(self._save_dirs)
        self.table.doubleClicked.connect(self._open_selected)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.quick_add_dir_btn.clicked.connect(self._add_dir)

        self._load_dirs_to_ui()
        self._apply_filters()
        return panel

    def _build_ui_state(self) -> None:
        self.search_box = None
        self.quick_add_dir_btn = None
        self.settings_btn = None
        self.status_filter = None
        self.sort_filter = None
        self.scan_btn = None
        self.new_doc_btn = None
        self.delete_doc_btn = None
        self.table = None
        self.table_model = None
        self.dir_list = None
        self.add_dir_btn = None
        self.remove_dir_btn = None
        self.ignore_edit = None
        self.status_label = None

    def _load_config(self) -> dict:
        data = _read_json(self.config_path, {})
        config = DEFAULT_CONFIG.copy()
        config.update(data if isinstance(data, dict) else {})
        config["dirs"] = _safe_list(config.get("dirs"))
        config["ignore"] = _safe_list(config.get("ignore")) or DEFAULT_CONFIG["ignore"]
        return config

    def _load_index(self) -> list[MarkdownItem]:
        data = _read_json(self.index_path, [])
        items = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            items.append(
                MarkdownItem(
                    title=str(item.get("title", "")),
                    path=str(item.get("path", "")),
                    updated_at=float(item.get("updated_at", 0)),
                    created_at=float(item.get("created_at", 0)),
                    status=str(item.get("status", "草稿")),
                    source=str(item.get("source", "")),
                    pinned=bool(item.get("pinned", False)),
                )
            )
        return items

    def _save_index(self) -> None:
        payload = [
            {
                "title": item.title,
                "path": item.path,
                "updated_at": item.updated_at,
                "created_at": item.created_at,
                "status": item.status,
                "source": item.source,
                "pinned": item.pinned,
            }
            for item in self.index
        ]
        _write_json(self.index_path, payload)

    def _load_dirs_to_ui(self) -> None:
        self.dir_list.clear()
        for item in self.config.get("dirs", []):
            self.dir_list.addItem(item)
        self.ignore_edit.setText(", ".join(self.config.get("ignore", [])))

    def _save_dirs(self) -> None:
        self.config["dirs"] = [self.dir_list.item(i).text() for i in range(self.dir_list.count())]
        ignore = [item.strip() for item in self.ignore_edit.text().split(",") if item.strip()]
        self.config["ignore"] = ignore
        _write_json(self.config_path, self.config)

    def _add_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(None, "选择 Markdown 目录")
        if not folder:
            return
        self.dir_list.addItem(folder)
        self._save_dirs()
        self._notify("新目录收到！我已经记下来了。")

    def _remove_dir(self) -> None:
        row = self.dir_list.currentRow()
        if row < 0:
            return
        self.dir_list.takeItem(row)
        self._save_dirs()
        self._notify("这个目录我先放一边啦。")

    def _apply_filters(self) -> None:
        if not self.table_model:
            return
        query = self.search_box.text().strip().lower()
        status = self.status_filter.currentText()
        rows = []
        for item in self.index:
            if status != "全部" and item.status != status:
                continue
            if query and query not in item.title.lower() and query not in os.path.basename(item.path).lower():
                continue
            rows.append(item)
        sort_mode = self.sort_filter.currentText()
        if sort_mode == "最近创建":
            rows.sort(key=lambda x: x.created_at, reverse=True)
        elif sort_mode == "按来源":
            rows.sort(key=lambda x: (x.source.lower(), -x.updated_at))
        elif sort_mode == "置顶优先":
            rows.sort(key=lambda x: (not x.pinned, -x.updated_at))
        else:
            rows.sort(key=lambda x: x.updated_at, reverse=True)
        self.table_model.set_rows(rows)

    def _create_new_doc(self) -> None:
        dirs = self.config.get("dirs", [])
        if not dirs:
            QMessageBox.information(None, "提示", "请先添加目录。")
            return
        selected_dir = dirs[0]
        dialog = QDialog(None)
        dialog.setWindowTitle("新建文档")
        layout = QFormLayout(dialog)
        dir_box = QComboBox()
        dir_box.addItems(dirs)
        title_edit = QLineEdit()
        title_edit.setPlaceholderText("输入标题")
        layout.addRow("目录", dir_box)
        layout.addRow("标题", title_edit)
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("创建")
        cancel_btn = QPushButton("取消")
        ok_btn.setObjectName("primaryBtn")
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addRow(btn_row)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        if dialog.exec() != QDialog.Accepted:
            return
        selected_dir = dir_box.currentText().strip() or selected_dir
        title = title_edit.text().strip() or "新文档"
        safe_title = re.sub(r"[\\/:*?\"<>|]+", "_", title)
        filename = f"{safe_title}.md"
        path = os.path.join(selected_dir, filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n\n")
        except Exception as exc:
            QMessageBox.warning(None, "创建失败", str(exc))
            return
        self._notify("新文档开张啦，写点什么？")
        self._start_scan()
        try:
            os.startfile(path)
        except Exception:
            pass

    def _start_scan(self) -> None:
        if self._thread:
            QMessageBox.information(None, "提示", "正在扫描，请稍候。")
            return
        roots = self.config.get("dirs", [])
        if not roots:
            QMessageBox.information(None, "提示", "请先添加目录。")
            return
        ignores = self.config.get("ignore", [])
        self.status_label.setText("扫描中...")
        self._notify("我去翻翻你的笔记，马上回来～")
        self._thread = QThread()
        self._worker = ScanWorker(roots, ignores)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_scan_finished, Qt.QueuedConnection)
        self._worker.error.connect(self._on_scan_error, Qt.QueuedConnection)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.start()

    def _on_scan_finished(self, items: list) -> None:
        self.index = items
        self._save_index()
        self.status_label.setText(f"已索引 {len(items)} 篇")
        self._apply_filters()
        QTimer.singleShot(0, self._stop_worker)
        self._notify(f"翻完啦，找到 {len(items)} 篇笔记。")

    def _on_scan_error(self, message: str) -> None:
        QMessageBox.warning(None, "扫描失败", message)
        self.status_label.setText("扫描失败")
        QTimer.singleShot(0, self._stop_worker)
        self._notify("扫描时有点小插曲，稍后再试试吧。")

    def _cleanup_worker(self) -> None:
        if self._worker:
            self._worker.deleteLater()
        if self._thread:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None

    def _stop_worker(self) -> None:
        if not self._thread:
            return
        if QThread.currentThread() == self._thread:
            self._thread.quit()
            return
        self._thread.quit()
        self._thread.wait(2000)
        self._cleanup_worker()

    def _open_selected(self) -> None:
        index = self.table.currentIndex()
        if not index.isValid():
            return
        item = self.table_model.get_row(index.row())
        if not item:
            return
        try:
            os.startfile(item.path)
            self._notify("文章已打开，灵感请上线！")
        except Exception as exc:
            QMessageBox.warning(None, "打开失败", str(exc))
            self._notify("这篇我没打开成，可能它搬家了。")

    def _delete_selected(self) -> None:
        index = self.table.currentIndex()
        if not index.isValid():
            QMessageBox.information(None, "提示", "请先选择一篇文档。")
            return
        item = self.table_model.get_row(index.row())
        if not item:
            return
        confirm = QMessageBox.question(None, "删除文档", f"确认删除：{item.title}？")
        if confirm != QMessageBox.Yes:
            return
        try:
            os.remove(item.path)
        except Exception as exc:
            QMessageBox.warning(None, "删除失败", str(exc))
            self._notify("没删成，可能文件正在使用。")
            return
        self.index = [entry for entry in self.index if entry.path != item.path]
        self._save_index()
        self._apply_filters()
        self._notify("文档已删除。")

    def _toggle_status(self, row: int) -> None:
        item = self.table_model.get_row(row)
        if not item:
            return
        statuses = ["草稿", "已校验", "已发布"]
        try:
            idx = statuses.index(item.status)
        except ValueError:
            idx = 0
        item.status = statuses[(idx + 1) % len(statuses)]
        self._save_index()
        self._apply_filters()

    def _set_status(self, row: int, status: str) -> None:
        item = self.table_model.get_row(row)
        if not item:
            return
        item.status = status
        self._save_index()
        self._apply_filters()
        self._notify(f"状态改成“{status}”啦。")

    def _show_context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        menu = QMenu(self.table)
        open_action = menu.addAction("打开")
        status_menu = menu.addMenu("设置状态")
        draft_action = status_menu.addAction("草稿")
        review_action = status_menu.addAction("已校验")
        publish_action = status_menu.addAction("已发布")
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == open_action:
            self.table.selectRow(row)
            self._open_selected()
        elif action == draft_action:
            self._set_status(row, "草稿")
        elif action == review_action:
            self._set_status(row, "已校验")
        elif action == publish_action:
            self._set_status(row, "已发布")


def create_plugin(context):
    return Plugin(context)
