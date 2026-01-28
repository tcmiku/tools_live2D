from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFrame,
)


DEFAULT_CONFIG = {
    "enabled": True,
    "interval_min": 30,
    "quiet_hours": ["23:00", "07:00"],
    "only_when_active": False,
    "packs": [
        {
            "name": "上午专注",
            "active": True,
            "time_range": ["09:00", "12:00"],
            "lines": [
                "加油，我们一起冲刺一下！",
                "今天状态不错，继续！",
                "把最重要的一件事先完成吧。",
                "先专注 10 分钟，进入状态就顺了。",
                "我在这儿陪你，安心做完这一段。",
                "先把任务拆小一点，会更好上手。",
            ],
        },
        {
            "name": "下午续航",
            "active": True,
            "time_range": ["13:30", "18:00"],
            "lines": [
                "再坚持一会儿，效果会更好～",
                "保持节奏，慢慢来也很稳。",
                "喝口水，缓一缓再继续。",
                "给自己一个小目标，做完就休息一下。",
                "专注力是可以积累的，你已经在路上了。",
                "别急，稳定推进就很棒。",
            ],
        },
        {
            "name": "晚间轻松",
            "active": True,
            "time_range": ["19:00", "22:30"],
            "lines": [
                "辛苦啦，做点轻松的任务也不错。",
                "今天的努力很棒哦。",
                "如果有点累，我们慢慢来。",
                "收个尾就好，别给自己太大压力。",
                "给自己一点小奖励吧～",
                "你已经做得很好了。",
            ],
        },
        {
            "name": "夜猫子模式",
            "active": True,
            "time_range": ["22:30", "02:00"],
            "lines": [
                "夜深了，注意保护眼睛和作息哦。",
                "夜猫子也要有节奏，做完就休息吧。",
                "再坚持一小段，别太久。",
                "如果困了就先放一放，明天更清醒。",
                "记得补水，别让自己太累。",
                "我在这儿陪你一会儿。",
            ],
        },
    ],
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


def _parse_time_to_minutes(value: str) -> int | None:
    text = str(value or "").strip()
    if not text or ":" not in text:
        return None
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _minutes_now(ts: float | None = None) -> int:
    now = time.localtime(ts or time.time())
    return now.tm_hour * 60 + now.tm_min


def _in_range(now_min: int, start_min: int, end_min: int) -> bool:
    if start_min <= end_min:
        return start_min <= now_min <= end_min
    return now_min >= start_min or now_min <= end_min


@dataclass
class PackItem:
    pack_id: str
    name: str
    active: bool
    time_range: list[str]
    lines: list[str]


class Plugin:
    def __init__(self, context) -> None:
        self.context = context
        self.config_path = context.get_data_path("config.json")
        self.phrases_path = context.get_data_path("phrases.json")
        self.config = self._load_config()
        self.phrases = self._load_phrases()
        self._normalize_config_and_phrases()
        self._last_emit_ts = 0.0
        self._panel = None
        self._enabled_toggle = None
        self._interval_spin = None
        self._quiet_start = None
        self._quiet_end = None
        self._only_active_toggle = None
        self._pack_list = None
        self._pack_name = None
        self._pack_active = None
        self._pack_start = None
        self._pack_end = None
        self._pack_lines = None
        self._add_pack_btn = None
        self._remove_pack_btn = None
        self._save_pack_btn = None
        self._preview_btn = None
        self._reload_btn = None
        self._pack_count = None
        self._list_hint = None

    def on_load(self, context) -> None:
        self.context.info("encourage pack plugin loaded")

    def on_unload(self) -> None:
        self._save_config()

    def on_tick(self, state_dict: dict, now_ts: float) -> None:
        if not self.config.get("enabled", True):
            return
        if self.config.get("only_when_active", False):
            if str(state_dict.get("status", "")) != "active":
                return
        interval_min = max(1, int(self.config.get("interval_min", 30)))
        if now_ts - self._last_emit_ts < interval_min * 60:
            return
        if self._in_quiet_hours(now_ts):
            return
        line = self._pick_line(now_ts)
        if not line:
            return
        self._last_emit_ts = now_ts
        bridge = getattr(self.context, "bridge", None)
        if bridge and hasattr(bridge, "push_passive_message"):
            bridge.push_passive_message(line)
            self.context.block_passive(2.0)

    def get_panel(self, parent=None):
        panel = QDialog(parent)
        panel.setWindowTitle("定时鼓励语料包")
        panel.setMinimumSize(860, 580)
        panel.setStyleSheet(
            "QWidget { background: #FFFFFF; color: #111111; }"
            "QLabel#Title { font-size: 20px; font-weight: 700; }"
            "QLabel#Muted { color: #666666; }"
            "QFrame#Card { background: #FFFFFF; border: 2px solid #111111; border-radius: 10px; }"
            "QLineEdit, QTextEdit, QListWidget, QSpinBox {"
            "  background: #FFFFFF; border: 2px solid #111111; border-radius: 8px; padding: 6px 8px;"
            "}"
            "QCheckBox { spacing: 8px; }"
            "QListWidget::item { padding: 6px 8px; }"
            "QListWidget::item:selected { background: #FFFFFF; color: #111111; }"
            "QPushButton { border: 2px solid #111111; border-radius: 8px; padding: 6px 12px; font-weight: 700; }"
            "QPushButton#Add { background: #2F6FED; color: #FFFFFF; }"
            "QPushButton#Save { background: #1F9D63; color: #FFFFFF; }"
            "QPushButton#Remove { background: #D9534F; color: #FFFFFF; }"
            "QPushButton#Preview { background: #F0AD4E; color: #111111; }"
            "QPushButton#ToggleOn { background: #1F9D63; color: #FFFFFF; }"
            "QPushButton#ToggleOff { background: #D9534F; color: #FFFFFF; }"
            "QPushButton:pressed { background: #111111; color: #FFFFFF; }"
        )
        root = QVBoxLayout(panel)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("定时鼓励语料包")
        title.setObjectName("Title")
        root.addWidget(title)

        config_card = QFrame()
        config_card.setObjectName("Card")
        config_form = QFormLayout(config_card)
        config_form.setContentsMargins(12, 12, 12, 12)
        config_form.setSpacing(8)
        enabled_toggle = QPushButton("")
        enabled_toggle.setCheckable(True)
        interval_spin = QSpinBox()
        interval_spin.setRange(5, 240)
        interval_spin.setSuffix(" 分钟")
        quiet_start = QLineEdit()
        quiet_end = QLineEdit()
        quiet_start.setPlaceholderText("23:00")
        quiet_end.setPlaceholderText("07:00")
        only_active_toggle = QCheckBox("仅在活跃状态推送")
        config_form.addRow("插件开关", enabled_toggle)
        config_form.addRow("推送间隔", interval_spin)
        config_form.addRow("静默开始", quiet_start)
        config_form.addRow("静默结束", quiet_end)
        config_form.addRow(only_active_toggle)
        root.addWidget(config_card)

        body = QHBoxLayout()
        body.setSpacing(12)
        pack_list = QListWidget()
        pack_list.setMinimumWidth(220)
        list_card = QFrame()
        list_card.setObjectName("Card")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(12, 12, 12, 12)
        list_header = QHBoxLayout()
        list_title = QLabel("语料包列表")
        list_count = QLabel("0 个")
        list_count.setObjectName("Muted")
        list_header.addWidget(list_title)
        list_header.addStretch(1)
        list_header.addWidget(list_count)
        list_layout.addLayout(list_header)
        list_layout.addWidget(pack_list, 1)
        list_hint = QLabel("双击语料包可快速预览")
        list_hint.setObjectName("Muted")
        list_layout.addWidget(list_hint)
        body.addWidget(list_card, 2)

        edit_card = QFrame()
        edit_card.setObjectName("Card")
        edit_form = QFormLayout(edit_card)
        edit_form.setContentsMargins(12, 12, 12, 12)
        edit_form.setSpacing(8)
        pack_name = QLineEdit()
        pack_active = QCheckBox("启用该语料包")
        pack_start = QLineEdit()
        pack_end = QLineEdit()
        pack_start.setPlaceholderText("09:00")
        pack_end.setPlaceholderText("12:00")
        pack_lines = QTextEdit()
        pack_lines.setPlaceholderText("每行一条鼓励语")
        edit_form.addRow("名称", pack_name)
        edit_form.addRow(pack_active)
        edit_form.addRow("开始时间", pack_start)
        edit_form.addRow("结束时间", pack_end)
        edit_form.addRow("语料列表", pack_lines)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("新增语料包")
        remove_btn = QPushButton("删除语料包")
        save_btn = QPushButton("保存语料包")
        preview_btn = QPushButton("立刻推送一条")
        reload_btn = QPushButton("从文件重载")
        add_btn.setObjectName("Add")
        save_btn.setObjectName("Save")
        remove_btn.setObjectName("Remove")
        preview_btn.setObjectName("Preview")
        reload_btn.setObjectName("Preview")
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(preview_btn)
        btn_row.addWidget(reload_btn)
        btn_row.addStretch(1)

        edit_wrap = QVBoxLayout()
        edit_wrap.addWidget(edit_card, 1)
        edit_wrap.addLayout(btn_row)
        body.addLayout(edit_wrap, 3)

        root.addLayout(body)

        enabled_toggle.toggled.connect(self._save_config_from_ui)
        interval_spin.valueChanged.connect(self._save_config_from_ui)
        quiet_start.editingFinished.connect(self._save_config_from_ui)
        quiet_end.editingFinished.connect(self._save_config_from_ui)
        only_active_toggle.toggled.connect(self._save_config_from_ui)
        pack_list.currentItemChanged.connect(self._apply_pack_to_ui)
        pack_list.itemDoubleClicked.connect(self._preview_line)
        add_btn.clicked.connect(self._add_pack)
        remove_btn.clicked.connect(self._remove_pack)
        save_btn.clicked.connect(self._save_pack)
        preview_btn.clicked.connect(self._preview_line)
        reload_btn.clicked.connect(self._reload_from_file)

        self._panel = panel
        self._enabled_toggle = enabled_toggle
        self._interval_spin = interval_spin
        self._quiet_start = quiet_start
        self._quiet_end = quiet_end
        self._only_active_toggle = only_active_toggle
        self._pack_list = pack_list
        self._pack_count = list_count
        self._list_hint = list_hint
        self._pack_name = pack_name
        self._pack_active = pack_active
        self._pack_start = pack_start
        self._pack_end = pack_end
        self._pack_lines = pack_lines
        self._add_pack_btn = add_btn
        self._remove_pack_btn = remove_btn
        self._save_pack_btn = save_btn
        self._preview_btn = preview_btn
        self._reload_btn = reload_btn

        self._apply_config_to_ui()
        return panel

    def _load_config(self) -> dict:
        data = _read_json(self.config_path, {})
        config = DEFAULT_CONFIG.copy()
        if isinstance(data, dict):
            config.update(data)
        config["packs"] = [item for item in config.get("packs", []) if isinstance(item, dict)]
        config["packs"] = _merge_default_packs(config["packs"])
        config["packs"] = _ensure_pack_ids(config["packs"])
        return config

    def _load_phrases(self) -> dict:
        data = _read_json(self.phrases_path, {})
        if isinstance(data, dict):
            packs = data.get("packs")
            if isinstance(packs, dict):
                return packs
        return {}

    def _save_config(self) -> None:
        _write_json(self.config_path, self.config)

    def _save_phrases(self) -> None:
        _write_json(self.phrases_path, {"packs": self.phrases})

    def _normalize_config_and_phrases(self) -> None:
        packs = self.config.get("packs", [])
        if not isinstance(packs, list):
            packs = []
        packs = _ensure_pack_ids(packs)
        default_lines_map = {
            str(item.get("name", "")).strip(): _safe_lines(item.get("lines"))
            for item in DEFAULT_CONFIG.get("packs", [])
        }
        existing_names = {str(item.get("name", "")).strip() for item in packs if str(item.get("name", "")).strip()}
        existing_ids = {str(item.get("id", "")).strip() for item in packs if str(item.get("id", "")).strip()}
        added = False
        for item in DEFAULT_CONFIG.get("packs", []):
            name = str(item.get("name", "")).strip()
            if not name or name in existing_names:
                continue
            pack_id = str(item.get("id", "")).strip()
            if not pack_id or pack_id in existing_ids:
                pack_id = _make_pack_id(name, existing_ids)
            existing_ids.add(pack_id)
            packs.append(
                {
                    "id": pack_id,
                    "name": name,
                    "active": bool(item.get("active", True)),
                    "time_range": _safe_time_range(item.get("time_range")),
                }
            )
            existing_names.add(name)
            added = True
        if added:
            self.config["packs"] = packs
            self._save_config()

        phrases_changed = False
        for item in packs:
            pack_id = str(item.get("id", "")).strip()
            if not pack_id:
                continue
            if pack_id in self.phrases:
                continue
            from_config = _safe_lines(item.get("lines"))
            name = str(item.get("name", "")).strip()
            default_lines = default_lines_map.get(name, [])
            self.phrases[pack_id] = from_config or list(default_lines)
            phrases_changed = True
        if phrases_changed:
            self._save_phrases()

    def _apply_config_to_ui(self) -> None:
        if not self._enabled_toggle:
            return
        enabled = bool(self.config.get("enabled", True))
        self._enabled_toggle.setChecked(enabled)
        self._enabled_toggle.setText("启用插件" if enabled else "已停用")
        self._enabled_toggle.setObjectName("ToggleOn" if enabled else "ToggleOff")
        self._enabled_toggle.style().unpolish(self._enabled_toggle)
        self._enabled_toggle.style().polish(self._enabled_toggle)
        self._interval_spin.setValue(int(self.config.get("interval_min", 30)))
        quiet = self.config.get("quiet_hours", ["23:00", "07:00"])
        quiet_start = quiet[0] if isinstance(quiet, list) and quiet else "23:00"
        quiet_end = quiet[1] if isinstance(quiet, list) and len(quiet) > 1 else "07:00"
        self._quiet_start.setText(str(quiet_start))
        self._quiet_end.setText(str(quiet_end))
        self._only_active_toggle.setChecked(bool(self.config.get("only_when_active", False)))
        self._pack_list.clear()
        for pack in self.config.get("packs", []):
            name = str(pack.get("name", "")).strip() or "未命名"
            item = QListWidgetItem(name)
            self._pack_list.addItem(item)
        if self._pack_count:
            self._pack_count.setText(f"{self._pack_list.count()} 个")
        if self._pack_list.count() > 0:
            self._pack_list.setCurrentRow(0)

    def _save_config_from_ui(self) -> None:
        if not self._enabled_toggle:
            return
        enabled = bool(self._enabled_toggle.isChecked())
        self.config["enabled"] = enabled
        self._enabled_toggle.setText("启用插件" if enabled else "已停用")
        self._enabled_toggle.setObjectName("ToggleOn" if enabled else "ToggleOff")
        self._enabled_toggle.style().unpolish(self._enabled_toggle)
        self._enabled_toggle.style().polish(self._enabled_toggle)
        self.config["interval_min"] = int(self._interval_spin.value())
        quiet_start = self._quiet_start.text().strip()
        quiet_end = self._quiet_end.text().strip()
        self.config["quiet_hours"] = [quiet_start, quiet_end]
        self.config["only_when_active"] = bool(self._only_active_toggle.isChecked())
        self._save_config()

    def _reload_from_file(self) -> None:
        self.config = self._load_config()
        self.phrases = self._load_phrases()
        self._normalize_config_and_phrases()
        self._save_config()
        self._save_phrases()
        self._apply_config_to_ui()

    def _apply_pack_to_ui(self) -> None:
        pack = self._current_pack()
        if not pack or not self._pack_name:
            return
        self._pack_name.setText(pack.name)
        self._pack_active.setChecked(bool(pack.active))
        self._pack_start.setText(pack.time_range[0] if pack.time_range else "")
        self._pack_end.setText(pack.time_range[1] if len(pack.time_range) > 1 else "")
        self._pack_lines.setPlainText("\n".join(pack.lines))

    def _current_pack_index(self) -> int:
        if not self._pack_list:
            return -1
        return self._pack_list.currentRow()

    def _current_pack(self) -> PackItem | None:
        idx = self._current_pack_index()
        packs = self.config.get("packs", [])
        if idx < 0 or idx >= len(packs):
            return None
        item = packs[idx]
        pack_id = str(item.get("id", "")).strip()
        return PackItem(
            pack_id=pack_id,
            name=str(item.get("name", "")),
            active=bool(item.get("active", True)),
            time_range=_safe_time_range(item.get("time_range")),
            lines=_safe_lines(self.phrases.get(pack_id)),
        )

    def _save_pack(self) -> None:
        idx = self._current_pack_index()
        if idx < 0:
            QMessageBox.information(self._panel, "提示", "请先选择一个语料包。")
            return
        name = self._pack_name.text().strip()
        start = self._pack_start.text().strip()
        end = self._pack_end.text().strip()
        if not name:
            QMessageBox.warning(self._panel, "提示", "名称不能为空。")
            return
        if _parse_time_to_minutes(start) is None or _parse_time_to_minutes(end) is None:
            QMessageBox.warning(self._panel, "提示", "时间格式不正确，应为 HH:MM。")
            return
        lines = [line.strip() for line in self._pack_lines.toPlainText().splitlines() if line.strip()]
        if not lines:
            QMessageBox.warning(self._panel, "提示", "语料不能为空。")
            return
        pack_id = str(self.config["packs"][idx].get("id", "")).strip()
        if not pack_id:
            pack_id = _build_pack_id(set(self.phrases.keys()), name)
            self.config["packs"][idx]["id"] = pack_id
        self.config["packs"][idx] = {
            "id": pack_id,
            "name": name,
            "active": bool(self._pack_active.isChecked()),
            "time_range": [start, end],
        }
        self.phrases[pack_id] = lines
        self._save_config()
        self._save_phrases()
        self._apply_config_to_ui()
        self._pack_list.setCurrentRow(idx)

    def _add_pack(self) -> None:
        pack_id = _build_pack_id(set(self.phrases.keys()), "pack")
        self.config.setdefault("packs", []).append(
            {
                "id": pack_id,
                "name": "新语料包",
                "active": True,
                "time_range": ["09:00", "12:00"],
            }
        )
        self.phrases[pack_id] = ["坚持一下，马上就有收获啦！"]
        self._save_config()
        self._save_phrases()
        self._apply_config_to_ui()
        self._pack_list.setCurrentRow(self._pack_list.count() - 1)

    def _remove_pack(self) -> None:
        idx = self._current_pack_index()
        if idx < 0:
            return
        pack = self._current_pack()
        confirm = QMessageBox.question(
            self._panel,
            "删除语料包",
            f"确认删除“{pack.name if pack else ''}”？",
        )
        if confirm != QMessageBox.Yes:
            return
        pack_id = str(self.config["packs"][idx].get("id", "")).strip()
        del self.config["packs"][idx]
        if pack_id:
            self.phrases.pop(pack_id, None)
        self._save_config()
        self._save_phrases()
        self._apply_config_to_ui()

    def _preview_line(self) -> None:
        line = self._pick_line(time.time(), preview=True)
        if not line:
            QMessageBox.information(self._panel, "提示", "当前没有可用的语料。")
            return
        bridge = getattr(self.context, "bridge", None)
        if bridge and hasattr(bridge, "push_passive_message"):
            bridge.push_passive_message(line)
            self.context.block_passive(2.0)

    def _in_quiet_hours(self, now_ts: float) -> bool:
        quiet = self.config.get("quiet_hours", ["23:00", "07:00"])
        start = quiet[0] if isinstance(quiet, list) and quiet else ""
        end = quiet[1] if isinstance(quiet, list) and len(quiet) > 1 else ""
        start_min = _parse_time_to_minutes(start)
        end_min = _parse_time_to_minutes(end)
        if start_min is None or end_min is None:
            return False
        return _in_range(_minutes_now(now_ts), start_min, end_min)

    def _pick_line(self, now_ts: float, preview: bool = False) -> str:
        packs = [PackItem(**_normalize_pack(item, self.phrases)) for item in self.config.get("packs", [])]
        now_min = _minutes_now(now_ts)
        candidates = []
        for pack in packs:
            if not pack.active:
                continue
            start_min = _parse_time_to_minutes(pack.time_range[0]) if pack.time_range else None
            end_min = _parse_time_to_minutes(pack.time_range[1]) if len(pack.time_range) > 1 else None
            if start_min is None or end_min is None:
                continue
            if _in_range(now_min, start_min, end_min):
                candidates.append(pack)
        if not candidates and preview:
            candidates = [pack for pack in packs if pack.active]
        if not candidates:
            return ""
        pack = random.choice(candidates)
        if not pack.lines:
            return ""
        return random.choice(pack.lines)


def _safe_time_range(value: Any) -> list[str]:
    if isinstance(value, list) and value:
        return [str(item) for item in value]
    return ["09:00", "12:00"]


def _safe_lines(value: Any) -> list[str]:
    if isinstance(value, list) and value:
        return [str(item) for item in value if str(item).strip()]
    return []


def _normalize_pack(item: dict, phrases: dict) -> dict:
    pack_id = str(item.get("id", "")).strip()
    return {
        "pack_id": pack_id,
        "name": str(item.get("name", "")),
        "active": bool(item.get("active", True)),
        "time_range": _safe_time_range(item.get("time_range")),
        "lines": _safe_lines(phrases.get(pack_id)),
    }


def _build_pack_id(existing: set[str], base: str) -> str:
    prefix = base.strip().lower().replace(" ", "_") or "pack"
    seed = int(time.time())
    candidate = f"{prefix}_{seed}"
    if candidate not in existing:
        return candidate
    for idx in range(1, 1000):
        candidate = f"{prefix}_{seed}_{idx}"
        if candidate not in existing:
            return candidate
    return f"{prefix}_{seed}_x"


def _make_pack_id(name: str, existing: set[str]) -> str:
    base = name.strip() or "pack"
    candidate = f"{base}_default"
    if candidate not in existing:
        return candidate
    for idx in range(1, 1000):
        candidate = f"{base}_default_{idx}"
        if candidate not in existing:
            return candidate
    return _build_pack_id(existing, base)


def _ensure_pack_ids(packs: list[dict]) -> list[dict]:
    existing = set()
    for item in packs:
        pack_id = str(item.get("id", "")).strip()
        if pack_id:
            existing.add(pack_id)
    for item in packs:
        pack_id = str(item.get("id", "")).strip()
        if pack_id:
            continue
        item["id"] = _build_pack_id(existing, str(item.get("name", "pack")))
        existing.add(item["id"])
    return packs


def _merge_default_packs(packs: list[dict]) -> list[dict]:
    existing_names = {str(item.get("name", "")).strip() for item in packs if str(item.get("name", "")).strip()}
    for item in DEFAULT_CONFIG.get("packs", []):
        name = str(item.get("name", "")).strip()
        if not name or name in existing_names:
            continue
        packs.append(
            {
                "id": str(item.get("id", "")).strip(),
                "name": name,
                "active": bool(item.get("active", True)),
                "time_range": _safe_time_range(item.get("time_range")),
            }
        )
        existing_names.add(name)
    return packs


def create_plugin(context):
    return Plugin(context)
