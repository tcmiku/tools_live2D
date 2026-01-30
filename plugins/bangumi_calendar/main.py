from __future__ import annotations

import json
import os
import threading
import time
from datetime import date
from typing import Any
from urllib.parse import urlparse

import requests
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl


CALENDAR_URL = "https://api.bgm.tv/calendar"
CACHE_TTL_SEC = 7 * 24 * 3600
BUBBLE_INTERVAL_SEC = 6 * 3600
REFRESH_BUBBLE_INTERVAL_SEC = 7 * 24 * 3600
KEYWORDS = ["新番", "放送", "动画更新", "今天更新", "周几更新"]

WEEKDAY_LABELS = {
    1: "周一",
    2: "周二",
    3: "周三",
    4: "周四",
    5: "周五",
    6: "周六",
    7: "周日",
}


def _read_json(path: str, fallback: Any) -> Any:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
    except Exception:
        pass
    return fallback


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _default_calendar() -> dict:
    return {
        "fetched_at": 0,
        "weekdays": {str(i): [] for i in range(1, 8)},
    }


def _today_weekday() -> int:
    return date.today().isoweekday()


class Plugin:
    def __init__(self, context) -> None:
        self.context = context
        self.calendar_path = context.get_data_path("calendar.json")
        self.state_path = context.get_data_path("state.json")
        self.cover_dir = context.get_data_path("covers")
        self._update_lock = threading.Lock()
        self._updating = False
        self._bubble_sent_this_round = False
        self._grid = None
        self._updated_label = None
        self._totals_label = None
        self._progress_bar = None
        self._refresh_btn = None
        self._refresh_hint = None
        self.state = self._load_state()

    def on_load(self, context) -> None:
        self.context.info("bangumi calendar plugin loaded")

    def on_unload(self) -> None:
        self._save_state()

    def on_app_ready(self) -> None:
        self._ensure_calendar()
        self._maybe_bubble_today()

    def on_user_message(self, text: str) -> None:
        self._bubble_sent_this_round = False
        if not self._match_keywords(text):
            return
        self._ensure_calendar()
        context_text = self._build_ai_context()
        if context_text:
            self.context.add_ai_context(context_text)
        self._maybe_send_bubble(
            "今天是周五，新番更新还挺多的",
            check_round=True,
        )

    def get_panel(self, parent=None):
        panel = QDialog(parent)
        panel.setWindowTitle("Bangumi 新番日历")
        panel.setMinimumSize(920, 560)

        root = QVBoxLayout(panel)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("Bangumi 新番日历（周视图）")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        updated_label = QLabel("")
        updated_label.setStyleSheet("color: #666;")
        totals_label = QLabel("")
        totals_label.setStyleSheet("color: #333; font-weight: 600;")

        info_row = QHBoxLayout()
        info_row.addWidget(updated_label)
        info_row.addStretch(1)
        info_row.addWidget(totals_label)
        root.addLayout(info_row)

        refresh_btn = QPushButton("手动刷新缓存")
        refresh_btn.setStyleSheet(
            "QPushButton { background: #2f6fed; color: white; padding: 6px 12px; border-radius: 6px; }"
            "QPushButton:hover { background: #2459bf; }"
        )
        local_refresh_btn = QPushButton("刷新本地数据")
        local_refresh_btn.setStyleSheet(
            "QPushButton { background: #e9edf2; color: #1f2937; padding: 6px 12px; border-radius: 6px; }"
            "QPushButton:hover { background: #dfe6ee; }"
        )
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setVisible(False)
        progress.setFixedWidth(180)
        refresh_hint = QLabel("")
        refresh_hint.setStyleSheet("color: #2f6fed;")
        refresh_row = QHBoxLayout()
        refresh_row.addWidget(refresh_btn)
        refresh_row.addWidget(local_refresh_btn)
        refresh_row.addWidget(progress)
        refresh_row.addWidget(refresh_hint)
        refresh_row.addStretch(1)
        root.addLayout(refresh_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 1)

        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        scroll.setWidget(container)

        self._grid = grid
        self._updated_label = updated_label
        self._totals_label = totals_label
        self._progress_bar = progress
        self._refresh_btn = refresh_btn
        self._refresh_hint = refresh_hint
        refresh_btn.clicked.connect(self._on_manual_refresh)
        local_refresh_btn.clicked.connect(self._on_local_refresh)

        self._render_calendar(grid, updated_label)
        self._render_totals(totals_label)
        self._log("界面已加载")
        return panel

    def _match_keywords(self, text: str) -> bool:
        if not text:
            return False
        for keyword in KEYWORDS:
            if keyword in text:
                return True
        return False

    def _load_state(self) -> dict:
        data = _read_json(self.state_path, {})
        if not isinstance(data, dict):
            data = {}
        data.setdefault("last_bubble_ts", 0)
        data.setdefault("last_refresh_bubble_ts", 0)
        return data

    def _save_state(self) -> None:
        _write_json(self.state_path, self.state)

    def _load_calendar(self) -> dict:
        data = _read_json(self.calendar_path, None)
        if isinstance(data, dict) and "weekdays" in data:
            return data
        return _default_calendar()

    def _needs_update(self, calendar: dict) -> bool:
        fetched_at = float(calendar.get("fetched_at") or 0)
        if fetched_at <= 0:
            return True
        return (time.time() - fetched_at) >= CACHE_TTL_SEC

    def _ensure_calendar(self, force: bool = False) -> None:
        calendar = self._load_calendar()
        if not force and not self._needs_update(calendar):
            self._log("缓存仍有效，未触发刷新")
            return
        with self._update_lock:
            if self._updating:
                self._log("刷新进行中，请稍候…")
                return
            self._updating = True
        self._on_refresh_start()
        thread = threading.Thread(target=self._update_calendar_worker, daemon=True)
        thread.start()

    def _update_calendar_worker(self) -> None:
        try:
            self._log(f"请求日历：{CALENDAR_URL}")
            calendar = self._fetch_calendar()
            if calendar:
                _write_json(self.calendar_path, calendar)
                self.context.info("bangumi calendar updated")
                self._log("日历刷新成功")
                self._maybe_refresh_bubble()
                self._schedule_ui_refresh(success=True)
            else:
                self.context.warn("bangumi calendar update failed")
                self._log("日历刷新失败")
                self._schedule_ui_refresh(success=False)
        except Exception as exc:
            self.context.warn(f"bangumi calendar update error: {exc}")
            self._log(f"刷新异常：{exc}")
            self._schedule_ui_refresh(success=False)
        finally:
            with self._update_lock:
                self._updating = False

    def _fetch_calendar(self) -> dict | None:
        try:
            resp = requests.get(CALENDAR_URL, timeout=10)
        except Exception as exc:
            self._log(f"请求失败：{exc}")
            return None
        self._log(f"响应状态：{resp.status_code}")
        if resp.status_code != 200:
            return None
        payload = resp.json()
        if not isinstance(payload, list):
            self._log("响应解析失败：payload 非列表")
            return None
        weekdays = {str(i): [] for i in range(1, 8)}
        for day in payload:
            weekday_info = day.get("weekday") or {}
            weekday_id = weekday_info.get("id")
            items = day.get("items") or []
            if not weekday_id or str(weekday_id) not in weekdays:
                continue
            for item in items:
                entry = self._extract_entry(item)
                if entry:
                    weekdays[str(weekday_id)].append(entry)
        return {"fetched_at": int(time.time()), "weekdays": weekdays}

    def _extract_entry(self, item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        subject_id = item.get("id")
        title = item.get("name_cn") or item.get("name") or ""
        title_jp = item.get("name") or ""
        url = item.get("url") or ""
        cover_url = ""
        images = item.get("images") or {}
        for key in ("common", "large", "medium", "small", "grid"):
            if images.get(key):
                cover_url = images[key]
                break
        cover_path = self._download_cover(cover_url, subject_id)
        return {
            "id": subject_id,
            "title": title,
            "title_jp": title_jp,
            "cover": cover_path,
            "url": url,
        }

    def _download_cover(self, url: str, subject_id: Any) -> str:
        if not url:
            return ""
        try:
            os.makedirs(self.cover_dir, exist_ok=True)
            ext = os.path.splitext(urlparse(url).path)[1] or ".jpg"
            filename = f"{subject_id}{ext}"
            path = os.path.join(self.cover_dir, filename)
            if os.path.exists(path):
                return path
            self._log(f"下载封面：{subject_id}")
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                self._log(f"封面下载失败：{subject_id} status={resp.status_code}")
                return ""
            with open(path, "wb") as handle:
                handle.write(resp.content)
            return path
        except Exception:
            return ""

    def _build_ai_context(self) -> str:
        calendar = self._load_calendar()
        fetched_at = int(calendar.get("fetched_at") or 0)
        if fetched_at <= 0:
            return ""
        today = _today_weekday()
        today_list = calendar.get("weekdays", {}).get(str(today), []) or []
        date_str = time.strftime("%Y-%m-%d", time.localtime(fetched_at))
        lines = ["【新番日历｜Bangumi】", f"数据更新时间：{date_str}"]
        weekday_label = WEEKDAY_LABELS.get(today, "今天")
        if today_list:
            lines.append(f"今天（{weekday_label}）更新的新番：")
            for item in today_list:
                title = item.get("title") or item.get("title_jp") or "未知标题"
                lines.append(f"- {title}")
        else:
            lines.append(f"今天（{weekday_label}）没有新番更新。")
        return "\n".join(lines)

    def _maybe_send_bubble(self, text: str, check_round: bool) -> None:
        now = time.time()
        last_ts = float(self.state.get("last_bubble_ts") or 0)
        if now - last_ts < BUBBLE_INTERVAL_SEC:
            return
        if check_round and self._bubble_sent_this_round:
            return
        if hasattr(self.context, "bridge") and hasattr(self.context.bridge, "push_passive_message"):
            self.context.bridge.push_passive_message(text)
            self.state["last_bubble_ts"] = now
            self._save_state()
            if check_round:
                self._bubble_sent_this_round = True

    def _maybe_bubble_today(self) -> None:
        calendar = self._load_calendar()
        today = _today_weekday()
        today_list = calendar.get("weekdays", {}).get(str(today), []) or []
        if not today_list:
            return
        self._maybe_send_bubble("今天有新番更新哦", check_round=False)

    def _maybe_refresh_bubble(self) -> None:
        now = time.time()
        last_ts = float(self.state.get("last_refresh_bubble_ts") or 0)
        if now - last_ts < REFRESH_BUBBLE_INTERVAL_SEC:
            return
        self._maybe_send_bubble("本周的新番日历更新好了", check_round=False)
        self.state["last_refresh_bubble_ts"] = now
        self._save_state()

    def _render_calendar(self, layout: QGridLayout, updated_label: QLabel) -> None:
        calendar = self._load_calendar()
        fetched_at = int(calendar.get("fetched_at") or 0)
        if fetched_at > 0:
            updated_label.setText(f"数据更新时间：{time.strftime('%Y-%m-%d', time.localtime(fetched_at))}")
        else:
            updated_label.setText("数据更新时间：暂无缓存")
        for i in range(layout.count()):
            item = layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        weekdays = calendar.get("weekdays", {}) or {}
        for col in range(7):
            day = col + 1
            day_label = QLabel(WEEKDAY_LABELS.get(day, f"周{day}"))
            day_label.setStyleSheet("font-weight: 600;")

            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(6, 6, 6, 6)
            column_layout.setSpacing(8)
            column_layout.addWidget(day_label)

            items = weekdays.get(str(day), []) or []
            if not items:
                empty = QLabel("暂无")
                empty.setStyleSheet("color: #888;")
                column_layout.addWidget(empty)
            else:
                for entry in items:
                    card = self._build_card(entry)
                    column_layout.addWidget(card)
            column_layout.addStretch(1)
            layout.addWidget(column, 0, col)

    def _render_totals(self, totals_label: QLabel) -> None:
        calendar = self._load_calendar()
        weekdays = calendar.get("weekdays", {}) or {}
        today = _today_weekday()
        today_count = len(weekdays.get(str(today), []) or [])
        week_count = sum(len(weekdays.get(str(day), []) or []) for day in range(1, 8))
        totals_label.setText(f"今日总数：{today_count}  本周总数：{week_count}")

    def _schedule_ui_refresh(self, success: bool) -> None:
        if not self._grid or not self._updated_label or not self._totals_label:
            return
        QTimer.singleShot(0, lambda: self._refresh_ui_from_cache(success))

    def _refresh_ui_from_cache(self, success: bool) -> None:
        if not self._grid or not self._updated_label or not self._totals_label:
            return
        self._render_calendar(self._grid, self._updated_label)
        self._render_totals(self._totals_label)
        self._on_refresh_finish(success)

    def _on_manual_refresh(self) -> None:
        self._ensure_calendar(force=True)

    def _on_local_refresh(self) -> None:
        self._log("刷新本地缓存数据")
        self._refresh_ui_from_cache(success=True)

    def _on_refresh_start(self) -> None:
        if self._progress_bar:
            self._progress_bar.setVisible(True)
        if self._refresh_btn:
            self._refresh_btn.setEnabled(False)
        if self._refresh_hint:
            self._refresh_hint.setText("刷新中…")
        self._log("开始刷新日历数据…")

    def _on_refresh_finish(self, success: bool) -> None:
        if self._progress_bar:
            self._progress_bar.setVisible(False)
        if self._refresh_btn:
            self._refresh_btn.setEnabled(True)
        if self._refresh_hint:
            self._refresh_hint.setText("刷新成功" if success else "刷新失败")
            QTimer.singleShot(3000, lambda: self._refresh_hint.setText(""))
        if success:
            self._log("刷新完成")
        else:
            self._log("刷新结束（未更新）")

    def _log(self, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.context.info(text)

    def _build_card(self, entry: dict) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet(
            "QFrame { border: 1px solid #e5e7eb; border-radius: 6px; }"
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        cover_label = QLabel()
        cover_label.setFixedSize(48, 64)
        cover_path = entry.get("cover") or ""
        if cover_path and os.path.exists(cover_path):
            pixmap = QPixmap(cover_path).scaled(
                48, 64, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            cover_label.setPixmap(pixmap)
        else:
            cover_label.setText("无封面")
            cover_label.setAlignment(Qt.AlignCenter)
            cover_label.setStyleSheet("background: #f3f4f6; color: #888;")

        title_label = QLabel(entry.get("title") or entry.get("title_jp") or "未知标题")
        title_label.setWordWrap(True)
        title_font = QFont()
        title_font.setPointSize(10)
        title_label.setFont(title_font)

        layout.addWidget(cover_label)
        layout.addWidget(title_label, 1)

        url = entry.get("url") or ""

        def _open_url() -> None:
            if url:
                QDesktopServices.openUrl(QUrl(url))

        frame.mousePressEvent = lambda _event: _open_url()
        return frame


def create_plugin(context):
    return Plugin(context)
