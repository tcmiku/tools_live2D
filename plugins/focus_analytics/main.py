from __future__ import annotations

import json
import os
import time
from datetime import date
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


DEFAULT_CONFIG = {
    "retention_days": 14,
    "top_n": 10,
    "bar_width": 24,
    "group_by_suffix": True,
    "max_title_len": 60,
    "flush_interval_sec": 10,
    "tracking_enabled": True,
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


def _format_seconds(seconds: float) -> str:
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


class Plugin:
    def __init__(self, context) -> None:
        self.context = context
        self.config_path = context.get_data_path("config.json")
        self.stats_path = context.get_data_path("stats.json")
        self.config = self._load_config()
        self.state = self._load_stats()
        self._last_flush = 0.0
        self._last_ui_update = 0.0
        self._panel = None
        self._summary_label = None
        self._chart_box = None
        self._table = None
        self._status_label = None
        self._retention_spin = None
        self._top_spin = None
        self._bar_spin = None
        self._suffix_toggle = None
        self._max_title_spin = None
        self._tracking_btn = None
        self._clear_btn = None

    def on_load(self, context) -> None:
        self.context.info("focus analytics plugin loaded")

    def on_unload(self) -> None:
        self._flush()

    def on_state(self, state_dict: dict) -> None:
        if not self.config.get("tracking_enabled", True):
            self.state["last_ts"] = time.time()
            return
        title_raw = str(state_dict.get("window_title", "")).strip()
        now = time.time()
        if not title_raw:
            self.state["last_ts"] = now
            return
        title = self._normalize_title(title_raw)
        last_title = self.state.get("last_title")
        last_ts = float(self.state.get("last_ts") or 0.0)
        if not last_ts:
            self.state["last_title"] = title
            self.state["last_ts"] = now
            return
        delta = max(0.0, now - last_ts)
        if last_title and delta > 0:
            self._add_time(last_title, delta)
        if title != last_title:
            self._inc_switch(title)
        self.state["last_title"] = title
        self.state["last_ts"] = now
        self._prune_days()
        if now - self._last_flush >= float(self.config.get("flush_interval_sec", 10)):
            self._flush()
        self._schedule_ui_update(now)

    def get_panel(self, parent=None):
        panel = QDialog(parent)
        panel.setWindowTitle("窗口关注统计")
        panel.setMinimumSize(820, 560)
        root = QVBoxLayout(panel)

        summary = QLabel("")
        summary.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        root.addWidget(summary)

        status_label = QLabel("")
        status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        root.addWidget(status_label)

        chart_box = QPlainTextEdit()
        chart_box.setReadOnly(True)
        chart_box.setLineWrapMode(QPlainTextEdit.NoWrap)
        chart_font = QFont("Consolas")
        chart_box.setFont(chart_font)
        root.addWidget(chart_box, 1)

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["标题", "时长", "切换"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(table, 2)

        settings_group = QGroupBox("设置")
        settings_form = QFormLayout(settings_group)
        retention_spin = QSpinBox()
        retention_spin.setRange(1, 90)
        retention_spin.setValue(int(self.config.get("retention_days", 14)))
        top_spin = QSpinBox()
        top_spin.setRange(3, 50)
        top_spin.setValue(int(self.config.get("top_n", 10)))
        bar_spin = QSpinBox()
        bar_spin.setRange(10, 60)
        bar_spin.setValue(int(self.config.get("bar_width", 24)))
        max_title_spin = QSpinBox()
        max_title_spin.setRange(20, 120)
        max_title_spin.setValue(int(self.config.get("max_title_len", 60)))
        suffix_toggle = QCheckBox("按应用后缀归类（标题 - 应用）")
        suffix_toggle.setChecked(bool(self.config.get("group_by_suffix", True)))
        settings_form.addRow("保留天数", retention_spin)
        settings_form.addRow("排行数量", top_spin)
        settings_form.addRow("柱宽", bar_spin)
        settings_form.addRow("标题最大长度", max_title_spin)
        settings_form.addRow(suffix_toggle)

        actions = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        save_btn = QPushButton("保存设置")
        tracking_btn = QPushButton(self._tracking_label())
        clear_btn = QPushButton("清空统计")
        refresh_btn.setStyleSheet("background: #e9edf2; color: #1f2937; font-weight: bold;")
        save_btn.setStyleSheet("background: #2f6fed; color: #ffffff; font-weight: bold;")
        clear_btn.setStyleSheet("background: #f0ad4e; color: #ffffff; font-weight: bold;")
        tracking_btn.setStyleSheet(
            "background: #d9534f; color: #ffffff; font-weight: bold;"
            if self.config.get("tracking_enabled", True)
            else "background: #2f6fed; color: #ffffff; font-weight: bold;"
        )
        actions.addWidget(refresh_btn)
        actions.addWidget(save_btn)
        actions.addWidget(tracking_btn)
        actions.addWidget(clear_btn)
        actions.addStretch(1)

        root.addWidget(settings_group)
        root.addLayout(actions)

        refresh_btn.clicked.connect(self._update_ui)
        save_btn.clicked.connect(self._save_config_from_ui)
        tracking_btn.clicked.connect(self._toggle_tracking)
        clear_btn.clicked.connect(self._clear_stats)

        self._panel = panel
        self._summary_label = summary
        self._status_label = status_label
        self._chart_box = chart_box
        self._table = table
        self._retention_spin = retention_spin
        self._top_spin = top_spin
        self._bar_spin = bar_spin
        self._suffix_toggle = suffix_toggle
        self._max_title_spin = max_title_spin
        self._tracking_btn = tracking_btn
        self._clear_btn = clear_btn

        self._update_ui()
        return panel

    def _load_config(self) -> dict:
        data = _read_json(self.config_path, {})
        config = DEFAULT_CONFIG.copy()
        if isinstance(data, dict):
            config.update(data)
        return config

    def _save_config_from_ui(self) -> None:
        if not self._retention_spin:
            return
        self.config["retention_days"] = int(self._retention_spin.value())
        self.config["top_n"] = int(self._top_spin.value())
        self.config["bar_width"] = int(self._bar_spin.value())
        self.config["group_by_suffix"] = bool(self._suffix_toggle.isChecked())
        self.config["max_title_len"] = int(self._max_title_spin.value())
        _write_json(self.config_path, self.config)
        self._update_ui()

    def _load_stats(self) -> dict:
        data = _read_json(self.stats_path, {})
        if not isinstance(data, dict):
            data = {}
        data.setdefault("daily", {})
        data.setdefault("last_title", "")
        data.setdefault("last_ts", 0.0)
        return data

    def _flush(self) -> None:
        self._last_flush = time.time()
        _write_json(self.stats_path, self.state)

    def _today_key(self) -> str:
        return date.today().isoformat()

    def _day_bucket(self) -> dict:
        daily = self.state.setdefault("daily", {})
        key = self._today_key()
        bucket = daily.get(key)
        if not isinstance(bucket, dict):
            bucket = {"titles": {}, "total_seconds": 0.0}
            daily[key] = bucket
        bucket.setdefault("titles", {})
        bucket.setdefault("total_seconds", 0.0)
        return bucket

    def _add_time(self, title: str, delta: float) -> None:
        bucket = self._day_bucket()
        titles = bucket["titles"]
        entry = titles.get(title) or {"seconds": 0.0, "switches": 0}
        entry["seconds"] = float(entry.get("seconds", 0.0)) + delta
        titles[title] = entry
        bucket["total_seconds"] = float(bucket.get("total_seconds", 0.0)) + delta

    def _inc_switch(self, title: str) -> None:
        bucket = self._day_bucket()
        titles = bucket["titles"]
        entry = titles.get(title) or {"seconds": 0.0, "switches": 0}
        entry["switches"] = int(entry.get("switches", 0)) + 1
        titles[title] = entry

    def _prune_days(self) -> None:
        keep = int(self.config.get("retention_days", 14))
        daily = self.state.get("daily", {})
        keys = sorted(daily.keys())
        if keep <= 0 or len(keys) <= keep:
            return
        for key in keys[: max(0, len(keys) - keep)]:
            daily.pop(key, None)

    def _normalize_title(self, title: str) -> str:
        text = title.strip()
        if self.config.get("group_by_suffix", True) and " - " in text:
            parts = [item.strip() for item in text.split(" - ") if item.strip()]
            if parts:
                text = parts[-1]
        max_len = int(self.config.get("max_title_len", 60))
        if max_len > 0 and len(text) > max_len:
            text = text[: max_len - 3] + "..."
        return text

    def _get_today_items(self) -> list[tuple[str, float, int]]:
        bucket = self._day_bucket()
        items = []
        for title, entry in bucket.get("titles", {}).items():
            seconds = float(entry.get("seconds", 0.0))
            switches = int(entry.get("switches", 0))
            items.append((title, seconds, switches))
        items.sort(key=lambda item: item[1], reverse=True)
        return items

    def _schedule_ui_update(self, now: float) -> None:
        if not self._panel or not self._panel.isVisible():
            return
        if now - self._last_ui_update < 1.0:
            return
        self._last_ui_update = now
        QTimer.singleShot(0, self._update_ui)

    def _update_ui(self) -> None:
        if not self._panel:
            return
        items = self._get_today_items()
        top_n = int(self.config.get("top_n", 10))
        chart_items = items[:top_n]
        total_seconds = sum(entry[1] for entry in items)
        top_title = chart_items[0][0] if chart_items else "-"
        if self._summary_label:
            self._summary_label.setText(
                f"今日总计：{_format_seconds(total_seconds)} | Top：{top_title}"
            )
        if self._status_label:
            status_text = "运行中" if self.config.get("tracking_enabled", True) else "已暂停"
            self._status_label.setText(f"统计状态：{status_text}")
            self._status_label.setStyleSheet(
                "color: #2f6fed; font-weight: bold;"
                if self.config.get("tracking_enabled", True)
                else "color: #d9534f; font-weight: bold;"
            )
        if self._chart_box:
            self._chart_box.setPlainText(self._build_chart(chart_items))
        if self._table:
            self._table.setRowCount(len(chart_items))
            for row, (title, seconds, switches) in enumerate(chart_items):
                self._table.setItem(row, 0, QTableWidgetItem(title))
                self._table.setItem(row, 1, QTableWidgetItem(_format_seconds(seconds)))
                self._table.setItem(row, 2, QTableWidgetItem(str(switches)))

    def _build_chart(self, items: list[tuple[str, float, int]]) -> str:
        if not items:
            return "No data"
        bar_width = max(10, int(self.config.get("bar_width", 24)))
        label_width = max(12, min(24, int(self.config.get("max_title_len", 60) / 3)))
        max_value = max(item[1] for item in items) or 1.0
        time_width = 8
        pct_width = 6
        header = (
            f"{'No.':>3}  {'Title'.ljust(label_width)} | "
            f"{'Bar'.ljust(bar_width)}  {'Time':>{time_width}}  {'Pct':>{pct_width}}"
        )
        lines = [header, "-" * len(header)]
        for idx, (title, seconds, _switches) in enumerate(items, start=1):
            ratio = seconds / max_value if max_value else 0.0
            bar_len = max(0, min(bar_width, int(round(ratio * bar_width))))
            if bar_len > 0:
                bar = '=' * max(0, bar_len - 1) + '>'
            else:
                bar = ''
            bar = bar.ljust(bar_width)
            label = title[:label_width].ljust(label_width)
            pct = f"{ratio * 100:5.1f}%"
            lines.append(
                f"{idx:>3}  {label} | {bar}  {_format_seconds(seconds):>{time_width}} {pct:>{pct_width}}"
            )
        return "\n".join(lines)

    def _tracking_label(self) -> str:
        return "⏸ 暂停统计" if self.config.get("tracking_enabled", True) else "▶ 启动统计"

    def _toggle_tracking(self) -> None:
        enabled = not bool(self.config.get("tracking_enabled", True))
        self.config["tracking_enabled"] = enabled
        _write_json(self.config_path, self.config)
        if self._tracking_btn:
            self._tracking_btn.setText(self._tracking_label())
            self._tracking_btn.setStyleSheet(
                "background: #d9534f; color: #ffffff; font-weight: bold;"
                if enabled
                else "background: #2f6fed; color: #ffffff; font-weight: bold;"
            )
        self._update_ui()

    def _clear_stats(self) -> None:
        self.state["daily"] = {}
        self.state["last_title"] = ""
        self.state["last_ts"] = 0.0
        self._flush()
        self._update_ui()


def create_plugin(context):
    return Plugin(context)
