from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from collections import deque

# 插件规范要点（来自 plugins/README.md 与 backend/plugins.py）：
# - 插件目录：plugins/<plugin_id>/，必须包含 plugin.json 与入口文件
# - plugin.json 字段：id/name/version/description/entry
# - 入口：Plugin 类 / create_plugin(context) / PLUGIN 对象
# - 生命周期钩子：on_app_start/on_app_ready/on_settings/on_state/on_tick/on_ai_reply/on_user_message 等
# - 对话注入：get_ai_context(user_text) / on_ai_context(user_text)

PLUGIN_DIR = os.path.dirname(__file__)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

for _mod in ("pm_client", "pm_prompt", "pm_policy"):
    if _mod in sys.modules:
        del sys.modules[_mod]

from pm_client import PlasticMemoriesClient
from pm_policy import MemoryPolicy
from pm_prompt import PromptComposer


DEFAULT_CONFIG = {
    "enabled": True,
    "base_url": "http://127.0.0.1:8007",
    "user_id": "local",
    "persona_id": "persona_1",
    "template_path": "personas/persona_1",
    "source_app": "tools_live2D",
    "timeout": 10.0,
}


def _read_json(path: str, fallback: dict) -> dict:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return fallback


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


class Plugin:
    def __init__(self, context) -> None:
        self.context = context
        self.config_path = context.get_data_path("config.json")
        self.session_path = context.get_data_path("session_id.txt")
        self.config = self._load_config()
        self.client = self._make_client()
        self.prompt = PromptComposer()
        self.policy = MemoryPolicy()
        self._lock = threading.Lock()
        self._user_queue: deque[str] = deque(maxlen=20)
        self._session_id = self._load_or_create_session_id()
        self._panel = None
        self._panel_fields = {}

    def _log(self, level: str, message: str) -> None:
        if not message:
            return
        if level == "info":
            self.context.info(message)
        elif level == "warn":
            self.context.warn(message)
        else:
            self.context.error(message)

    def _load_config(self) -> dict:
        config = DEFAULT_CONFIG.copy()
        stored = _read_json(self.config_path, {})
        if isinstance(stored, dict):
            config.update(stored)
        config["enabled"] = bool(config.get("enabled", True))

        env_base_url = os.getenv("PM_BASE_URL")
        env_user_id = os.getenv("PM_USER_ID")
        env_persona_id = os.getenv("PM_PERSONA_ID")
        env_template = os.getenv("PM_TEMPLATE_PATH")
        env_source_app = os.getenv("PM_SOURCE_APP")
        env_timeout = os.getenv("PM_TIMEOUT")
        env_enabled = os.getenv("PM_ENABLED")

        if env_base_url:
            config["base_url"] = env_base_url
        if env_user_id:
            config["user_id"] = env_user_id
        if env_persona_id:
            config["persona_id"] = env_persona_id
        if env_template:
            config["template_path"] = env_template
        if env_source_app:
            config["source_app"] = env_source_app
        if env_timeout:
            try:
                config["timeout"] = float(env_timeout)
            except (TypeError, ValueError):
                pass
        config["enabled"] = _parse_bool(env_enabled, bool(config.get("enabled", True)))

        _write_json(self.config_path, config)
        return config

    def _make_client(self) -> PlasticMemoriesClient:
        return PlasticMemoriesClient(
            base_url=str(self.config.get("base_url", "")),
            user_id=str(self.config.get("user_id", "")),
            persona_id=str(self.config.get("persona_id", "")),
            template_path=str(self.config.get("template_path", "")),
            source_app=str(self.config.get("source_app", "")),
            timeout=float(self.config.get("timeout", 10.0)),
            log=self._log,
        )

    def _load_or_create_session_id(self) -> str:
        try:
            if os.path.exists(self.session_path):
                with open(self.session_path, "r", encoding="utf-8") as handle:
                    value = handle.read().strip()
                    if value:
                        return value
        except Exception:
            pass
        value = uuid.uuid4().hex
        try:
            with open(self.session_path, "w", encoding="utf-8") as handle:
                handle.write(value)
        except Exception:
            pass
        return value

    def _is_enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    def on_load(self, context) -> None:
        self.context.info("Plastic Memories 插件已加载")

    def on_app_start(self) -> None:
        if not self._is_enabled():
            return

        def _worker() -> None:
            try:
                ok = self.client.ensure_persona()
                if ok:
                    self.context.info("Plastic Memories 人格检查完成")
            except Exception as exc:
                self.context.warn(f"人格初始化异常: {exc}")

        threading.Thread(target=_worker, daemon=True).start()
        self.context.info("Plastic Memories on_app_start 已触发")

    def get_panel(self, parent=None):
        try:
            from PySide6.QtWidgets import (
                QCheckBox,
                QDialog,
                QFormLayout,
                QHBoxLayout,
                QLabel,
                QLineEdit,
                QPushButton,
                QTextEdit,
                QVBoxLayout,
                QFrame,
            )
        except Exception as exc:
            self.context.warn(f"加载面板失败: {exc}")
            return None

        panel = QDialog(parent)
        panel.setWindowTitle("Plastic Memories")
        panel.setMinimumSize(640, 520)
        panel.setStyleSheet(
            "QWidget { background: #FFFFFF; color: #111111; }"
            "QLabel#Title { font-size: 18px; font-weight: 700; }"
            "QLabel#Muted { color: #666666; }"
            "QFrame#Card { background: #FFFFFF; border: 2px solid #111111; border-radius: 10px; }"
            "QLineEdit, QTextEdit {"
            "  background: #FFFFFF; border: 2px solid #111111; border-radius: 8px; padding: 6px 8px;"
            "}"
            "QCheckBox { spacing: 8px; }"
            "QPushButton { border: 2px solid #111111; border-radius: 8px; padding: 6px 12px; font-weight: 700; }"
            "QPushButton#Save { background: #1F9D63; color: #FFFFFF; }"
            "QPushButton#Test { background: #2F6FED; color: #FFFFFF; }"
        )

        root = QVBoxLayout(panel)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Plastic Memories 配置")
        title.setObjectName("Title")
        root.addWidget(title)

        hint = QLabel(f"配置文件：{self.config_path}")
        hint.setObjectName("Muted")
        root.addWidget(hint)

        card = QFrame()
        card.setObjectName("Card")
        form = QFormLayout(card)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)

        enabled_toggle = QCheckBox("启用插件")
        base_url = QLineEdit()
        user_id = QLineEdit()
        persona_id = QLineEdit()
        template_path = QLineEdit()
        source_app = QLineEdit()
        timeout = QLineEdit()

        form.addRow(enabled_toggle)
        form.addRow("PM_BASE_URL", base_url)
        form.addRow("PM_USER_ID", user_id)
        form.addRow("PM_PERSONA_ID", persona_id)
        form.addRow("PM_TEMPLATE_PATH", template_path)
        form.addRow("PM_SOURCE_APP", source_app)
        form.addRow("PM_TIMEOUT", timeout)
        root.addWidget(card)

        output = QTextEdit()
        output.setReadOnly(True)
        output.setPlaceholderText("测试输出与日志")
        root.addWidget(output, 1)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存配置")
        save_btn.setObjectName("Save")
        test_health = QPushButton("测试 /health")
        test_health.setObjectName("Test")
        test_persona = QPushButton("测试 ensure_persona")
        test_persona.setObjectName("Test")
        test_recall = QPushButton("测试 recall")
        test_recall.setObjectName("Test")
        btn_row.addWidget(save_btn)
        btn_row.addWidget(test_health)
        btn_row.addWidget(test_persona)
        btn_row.addWidget(test_recall)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self._panel = panel
        self._panel_fields = {
            "enabled": enabled_toggle,
            "base_url": base_url,
            "user_id": user_id,
            "persona_id": persona_id,
            "template_path": template_path,
            "source_app": source_app,
            "timeout": timeout,
            "output": output,
        }
        self._apply_config_to_panel()

        save_btn.clicked.connect(self._save_config_from_panel)
        test_health.clicked.connect(self._test_health)
        test_persona.clicked.connect(self._test_persona)
        test_recall.clicked.connect(self._test_recall)

        return panel

    def _apply_config_to_panel(self) -> None:
        if not self._panel_fields:
            return
        self._panel_fields["enabled"].setChecked(bool(self.config.get("enabled", True)))
        self._panel_fields["base_url"].setText(str(self.config.get("base_url", "")))
        self._panel_fields["user_id"].setText(str(self.config.get("user_id", "")))
        self._panel_fields["persona_id"].setText(str(self.config.get("persona_id", "")))
        self._panel_fields["template_path"].setText(str(self.config.get("template_path", "")))
        self._panel_fields["source_app"].setText(str(self.config.get("source_app", "")))
        self._panel_fields["timeout"].setText(str(self.config.get("timeout", 10.0)))

    def _save_config_from_panel(self) -> None:
        if not self._panel_fields:
            return
        self.config["enabled"] = bool(self._panel_fields["enabled"].isChecked())
        self.config["base_url"] = self._panel_fields["base_url"].text().strip()
        self.config["user_id"] = self._panel_fields["user_id"].text().strip()
        self.config["persona_id"] = self._panel_fields["persona_id"].text().strip()
        self.config["template_path"] = self._panel_fields["template_path"].text().strip()
        self.config["source_app"] = self._panel_fields["source_app"].text().strip()
        try:
            self.config["timeout"] = float(self._panel_fields["timeout"].text().strip() or 10.0)
        except (TypeError, ValueError):
            self.config["timeout"] = 10.0
        _write_json(self.config_path, self.config)
        self.client = self._make_client()
        self._append_output("配置已保存并刷新客户端")

    def _append_output(self, text: str) -> None:
        output = self._panel_fields.get("output") if self._panel_fields else None
        if output:
            output.append(text)

    def _test_health(self) -> None:
        ok, msg = self.client.health_check()
        self._append_output(f"/health: {'OK' if ok else 'FAILED'} {msg}")

    def _test_persona(self) -> None:
        ok = self.client.ensure_persona()
        self._append_output(f"ensure_persona: {'OK' if ok else 'FAILED'}")

    def _test_recall(self) -> None:
        sample = "测试召回"
        data = self.client.recall(sample)
        injection = self.prompt.compose_injection(data)
        if injection:
            self._append_output("recall 注入块:\n" + injection)
        else:
            self._append_output("recall 返回为空")

    def get_ai_context(self, user_text: str) -> list[str]:
        if not self._is_enabled():
            return []
        try:
            self.context.info(f"get_ai_context 收到用户输入: {user_text[:40]}")
            recall = self.client.recall(user_text)
            if isinstance(recall, dict):
                keys = ",".join(sorted(recall.keys()))
                self.context.info(f"Recall 返回字段: {keys or 'empty'}")
            payload = recall
            if isinstance(recall, dict) and "data" in recall:
                payload = recall.get("data") or {}
            injection = self.prompt.compose_injection(payload if isinstance(payload, dict) else {})
            if injection:
                self.context.info("Recall 注入已生效")
                return [injection]
            self.context.warn("Recall 返回为空，未注入")
            return []
        except Exception as exc:
            self.context.warn(f"Recall 注入失败: {exc}")
            return []

    def on_user_message(self, text: str) -> None:
        if not self._is_enabled():
            return
        message = str(text or "").strip()
        if not message:
            return
        with self._lock:
            self._user_queue.append(message)
            self.context.info(f"on_user_message 入队: len={len(self._user_queue)}")

    def on_ai_reply(self, text: str) -> None:
        if not self._is_enabled():
            return
        assistant_text = str(text or "").strip()
        if not assistant_text:
            return
        with self._lock:
            user_text = self._user_queue.popleft() if self._user_queue else ""
            self.context.info(f"on_ai_reply 出队: len={len(self._user_queue)}")
        if not user_text:
            self.context.warn("未找到对应 user_text，跳过 Plastic Memories 写入")
            return

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        messages = [
            {"role": "user", "content": user_text, "created_at": now_iso},
            {"role": "assistant", "content": assistant_text, "created_at": now_iso},
        ]
        appended = self.client.append_messages(self._session_id, messages)
        if not appended:
            self.context.warn("消息写入失败，已记录并继续执行")

        items = self.policy.extract(user_text, assistant_text)
        for item in items:
            if item.memory_type not in {
                "persona",
                "preferences",
                "rule",
                "glossary",
                "stable_fact",
            }:
                self.context.warn(f"不支持的记忆类型: {item.memory_type}")
                continue
            ok = self.client.write_memory_item(item.memory_type, item.key, item.content)
            if not ok:
                self.context.warn(f"写入记忆失败: {item.key}")


def create_plugin(context):
    return Plugin(context)
