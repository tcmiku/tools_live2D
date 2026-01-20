from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import subprocess
from dataclasses import dataclass
from typing import Any

import requests

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QThread, QTimer, QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QInputDialog,
)


DEFAULT_CONFIG = {
    "enabled": True,
    "tool_call_mode": "strict",
    "risk_confirm": {"enabled": True, "remember": True, "remembered": {}},
    "file_scope": {"allowed_dirs": []},
    "tool_allowlist": [],
    "tool_denylist": [],
    "ai_api": {"mode": "reuse", "base_url": "", "api_key": "", "model": ""},
    "install_tools": {"npm_path": "", "npx_path": ""},
    "servers": [
        {
            "id": "default",
            "name": "Local MCP",
            "protocol": "auto",
            "url": "http://localhost:3000",
            "token": "",
            "command": "",
            "args": [],
            "enabled": True,
        }
    ],
    "default_server": "default",
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


class MCPClient:
    def __init__(self, server: dict) -> None:
        self.server = server

    def list_tools(self) -> list[dict]:
        protocol = str(self.server.get("protocol", "auto")).lower()
        for proto in self._iter_protocols(protocol):
            try:
                if proto == "ws":
                    return self._ws_list_tools()
                if proto == "http":
                    return self._http_list_tools()
                if proto == "stdio":
                    return self._stdio_list_tools()
            except Exception:
                continue
        raise RuntimeError("无法连接 MCP 服务器")

    def call_tool(self, name: str, args: dict) -> dict:
        protocol = str(self.server.get("protocol", "auto")).lower()
        for proto in self._iter_protocols(protocol):
            try:
                if proto == "ws":
                    return self._ws_call_tool(name, args)
                if proto == "http":
                    return self._http_call_tool(name, args)
                if proto == "stdio":
                    return self._stdio_call_tool(name, args)
            except Exception:
                continue
        raise RuntimeError("工具调用失败")

    def _iter_protocols(self, protocol: str) -> list[str]:
        if protocol in ("ws", "http", "stdio"):
            return [protocol]
        return ["ws", "http", "stdio"]

    def _headers(self) -> dict:
        token = str(self.server.get("token", "")).strip()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    def _http_list_tools(self) -> list[dict]:
        base_url = str(self.server.get("url", "")).rstrip("/")
        if not base_url:
            raise RuntimeError("HTTP URL 未配置")
        payload = {"type": "tools/list"}
        resp = requests.post(f"{base_url}/tools/list", json=payload, headers=self._headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("tools") or data.get("result", {}).get("tools") or []

    def _http_call_tool(self, name: str, args: dict) -> dict:
        base_url = str(self.server.get("url", "")).rstrip("/")
        if not base_url:
            raise RuntimeError("HTTP URL 未配置")
        payload = {"type": "tools/call", "tool": name, "args": args}
        resp = requests.post(f"{base_url}/tools/call", json=payload, headers=self._headers(), timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", data)

    def _ws_list_tools(self) -> list[dict]:
        try:
            import asyncio
            import websockets
        except Exception as exc:
            raise RuntimeError(f"WebSocket 不可用: {exc}") from exc
        url = str(self.server.get("url", "")).strip()
        if not url:
            raise RuntimeError("WebSocket URL 未配置")

        async def _run():
            async with websockets.connect(url, extra_headers=self._headers()) as ws:
                await ws.send(json.dumps({"type": "tools/list"}))
                message = await ws.recv()
                data = json.loads(message)
                return data.get("tools") or data.get("result", {}).get("tools") or []

        return asyncio.run(_run())

    def _ws_call_tool(self, name: str, args: dict) -> dict:
        try:
            import asyncio
            import websockets
        except Exception as exc:
            raise RuntimeError(f"WebSocket 不可用: {exc}") from exc
        url = str(self.server.get("url", "")).strip()
        if not url:
            raise RuntimeError("WebSocket URL 未配置")

        async def _run():
            async with websockets.connect(url, extra_headers=self._headers()) as ws:
                await ws.send(json.dumps({"type": "tools/call", "tool": name, "args": args}))
                message = await ws.recv()
                data = json.loads(message)
                return data.get("result", data)

        return asyncio.run(_run())

    def _stdio_list_tools(self) -> list[dict]:
        response = self._stdio_request({"type": "tools/list"})
        return response.get("tools") or response.get("result", {}).get("tools") or []

    def _stdio_call_tool(self, name: str, args: dict) -> dict:
        return self._stdio_request({"type": "tools/call", "tool": name, "args": args})

    def _stdio_request(self, payload: dict) -> dict:
        command = str(self.server.get("command", "")).strip()
        args = self.server.get("args", [])
        if not command:
            raise RuntimeError("stdio command 未配置")
        if not isinstance(args, list):
            args = []
        cmd_list = [command] + [str(item) for item in args]
        proc = subprocess.Popen(
            cmd_list,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline().strip()
        proc.kill()
        if not line:
            raise RuntimeError("stdio 返回为空")
        return json.loads(line)


class UiDispatcher(QObject):
    run = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.run.connect(self._invoke)

    def _invoke(self, func) -> None:
        func()


class ServerTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._headers = ["名称", "协议", "地址/命令", "启用"]
        self._rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return row.get("name", "")
            if col == 1:
                return row.get("protocol", "")
            if col == 2:
                return row.get("url") or row.get("command", "")
            if col == 3:
                return "是" if row.get("enabled", True) else "否"
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self._headers[section]
        return None

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def get_row(self, row: int) -> dict | None:
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]


class ToolTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._headers = ["工具", "描述", "风险", "可用"]
        self._rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return row.get("name", "")
            if col == 1:
                return row.get("description", "")
            if col == 2:
                return "是" if row.get("risk", False) else "否"
            if col == 3:
                return "是" if row.get("enabled", True) else "否"
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self._headers[section]
        return None

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def get_row(self, row: int) -> dict | None:
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]


class ToolRequestWorker(QThread):
    def __init__(self, server: dict, parent=None) -> None:
        super().__init__(parent)
        self.server = server
        self.result: list[dict] | None = None
        self.error: str | None = None

    def run(self) -> None:
        try:
            client = MCPClient(self.server)
            self.result = client.list_tools()
        except Exception as exc:
            self.error = str(exc)


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
        self.history = _read_json(self.history_path, [])
        self._tools_cache: list[dict] = []
        self._ui_dispatcher = UiDispatcher()
        self._build_ui_state()

    def on_load(self, context) -> None:
        self.context.info("mcp client plugin loaded")

    def get_ai_context(self, user_text: str) -> str:
        if not self.config.get("enabled", True):
            return ""
        tools = self._get_tools()
        if not tools:
            return ""
        tool_call = self._select_tool_call(user_text, tools)
        if not tool_call:
            return ""
        tool_name = tool_call.get("tool")
        args = tool_call.get("args", {})
        if not tool_name:
            return ""
        if not self._is_tool_allowed(tool_name):
            return f"MCP 工具 {tool_name} 被禁止调用。"
        if self._is_risky_tool(tool_name, tools):
            if self._risk_confirmation_required(tool_name) and not self._confirm_risk(tool_name, args):
                return f"MCP 工具 {tool_name} 需要用户确认，已取消调用。"
        try:
            result = self._call_tool(tool_name, args)
            self._append_history(tool_name, args, result)
            return f"MCP 工具结果({tool_name}): {result}"
        except Exception as exc:
            return f"MCP 工具调用失败({tool_name}): {exc}"

    def get_panel(self, parent=None):
        panel = QDialog(None)
        panel.setWindowTitle("MCP 工具客户端")
        panel.setMinimumSize(900, 620)
        flags = Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint
        flags |= Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
        panel.setWindowFlags(flags)

        root = QVBoxLayout(panel)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        server_tab = QWidget()
        server_layout = QVBoxLayout(server_tab)
        server_layout.addWidget(QLabel("MCP 服务器"))
        self.server_model = ServerTableModel()
        self.server_table = QTableView()
        self.server_table.setModel(self.server_model)
        self.server_table.horizontalHeader().setStretchLastSection(True)
        server_layout.addWidget(self.server_table, 1)

        server_actions = QHBoxLayout()
        self.add_server_btn = QPushButton("新增")
        self.remove_server_btn = QPushButton("删除")
        self.default_server_btn = QPushButton("设为默认")
        self.refresh_tools_btn = QPushButton("刷新工具")
        self.test_server_btn = QPushButton("测试连接")
        self.import_json_btn = QPushButton("导入JSON")
        server_actions.addWidget(self.add_server_btn)
        server_actions.addWidget(self.remove_server_btn)
        server_actions.addWidget(self.default_server_btn)
        server_actions.addWidget(self.refresh_tools_btn)
        server_actions.addWidget(self.test_server_btn)
        server_actions.addWidget(self.import_json_btn)
        server_layout.addLayout(server_actions)

        server_form = QFormLayout()
        self.server_name = QLineEdit()
        self.server_protocol = QComboBox()
        self.server_protocol.addItems(["auto", "ws", "http", "stdio"])
        self.server_url = QLineEdit()
        self.server_token = QLineEdit()
        self.server_command = QLineEdit()
        self.server_args = QLineEdit()
        self.server_enabled = QCheckBox("启用该服务器")
        server_form.addRow("名称", self.server_name)
        server_form.addRow("协议", self.server_protocol)
        server_form.addRow("URL", self.server_url)
        server_form.addRow("Token", self.server_token)
        server_form.addRow("Command", self.server_command)
        server_form.addRow("Args", self.server_args)
        server_form.addRow(self.server_enabled)
        server_layout.addLayout(server_form)

        tools_tab = QWidget()
        tools_layout = QVBoxLayout(tools_tab)
        tools_layout.addWidget(QLabel("工具列表"))
        self.tool_model = ToolTableModel()
        self.tool_table = QTableView()
        self.tool_table.setModel(self.tool_model)
        self.tool_table.horizontalHeader().setStretchLastSection(True)
        tools_layout.addWidget(self.tool_table, 1)

        settings_tab = QWidget()
        settings_layout = QFormLayout(settings_tab)
        self.enabled_toggle = QCheckBox("启用 MCP 工具")
        self.call_mode_combo = QComboBox()
        self.call_mode_combo.addItems(["strict", "lenient"])
        self.risk_confirm_toggle = QCheckBox("高风险工具需要确认")
        self.ai_mode_combo = QComboBox()
        self.ai_mode_combo.addItems(["reuse", "custom"])
        self.ai_base_url = QLineEdit()
        self.ai_api_key = QLineEdit()
        self.ai_api_key.setEchoMode(QLineEdit.Password)
        self.ai_model = QLineEdit()
        self.allowed_dirs = QListWidget()
        self.add_dir_btn = QPushButton("添加目录")

        settings_layout.addRow(self.enabled_toggle)
        settings_layout.addRow("工具调用格式", self.call_mode_combo)
        settings_layout.addRow(self.risk_confirm_toggle)
        settings_layout.addRow("AI 设置模式", self.ai_mode_combo)
        settings_layout.addRow("AI Base URL", self.ai_base_url)
        settings_layout.addRow("AI API Key", self.ai_api_key)
        settings_layout.addRow("AI Model", self.ai_model)
        settings_layout.addRow("允许文件目录", self.allowed_dirs)
        settings_layout.addRow(self.add_dir_btn)

        install_tab = QWidget()
        install_layout = QFormLayout(install_tab)
        self.install_dir = QLineEdit()
        self.install_browse_btn = QPushButton("选择目录")
        install_dir_row = QHBoxLayout()
        install_dir_row.addWidget(self.install_dir, 1)
        install_dir_row.addWidget(self.install_browse_btn)
        self.npm_install_btn = QPushButton("npm i")
        self.npm_build_btn = QPushButton("npm run build")
        self.npx_package = QLineEdit()
        self.npx_install_btn = QPushButton("npx 安装")
        self.npm_path = QLineEdit()
        self.npx_path = QLineEdit()
        self.detect_tools_btn = QPushButton("自动探测")
        self.cancel_install_btn = QPushButton("取消安装")
        self.install_log = QPlainTextEdit()
        self.install_log.setReadOnly(True)
        install_layout.addRow("项目目录", install_dir_row)
        install_layout.addRow(self.npm_install_btn, self.npm_build_btn)
        install_layout.addRow("npx 包名", self.npx_package)
        install_layout.addRow(self.npx_install_btn)
        install_layout.addRow("npm 路径(可选)", self.npm_path)
        install_layout.addRow("npx 路径(可选)", self.npx_path)
        install_layout.addRow(self.detect_tools_btn, self.cancel_install_btn)
        install_layout.addRow("安装日志", self.install_log)

        tabs.addTab(server_tab, "服务器")
        tabs.addTab(tools_tab, "工具")
        tabs.addTab(settings_tab, "设置")
        tabs.addTab(install_tab, "安装")

        self.add_server_btn.clicked.connect(self._add_server)
        self.remove_server_btn.clicked.connect(self._remove_server)
        self.default_server_btn.clicked.connect(self._set_default_server)
        self.refresh_tools_btn.clicked.connect(self._refresh_tools)
        self.test_server_btn.clicked.connect(self._test_server)
        self.import_json_btn.clicked.connect(self._import_json)
        self.add_dir_btn.clicked.connect(self._add_allowed_dir)
        self.install_browse_btn.clicked.connect(self._choose_install_dir)
        self.npm_install_btn.clicked.connect(lambda: self._run_install("npm", ["i"]))
        self.npm_build_btn.clicked.connect(lambda: self._run_install("npm", ["run", "build"]))
        self.npx_install_btn.clicked.connect(self._run_npx_install)
        self.detect_tools_btn.clicked.connect(self._detect_install_tools)
        self.cancel_install_btn.clicked.connect(self._cancel_install)
        self.npm_path.textChanged.connect(self._save_config_from_ui)
        self.npx_path.textChanged.connect(self._save_config_from_ui)
        self.enabled_toggle.toggled.connect(self._save_config_from_ui)
        self.call_mode_combo.currentIndexChanged.connect(self._save_config_from_ui)
        self.risk_confirm_toggle.toggled.connect(self._save_config_from_ui)
        self.ai_mode_combo.currentIndexChanged.connect(self._save_config_from_ui)
        self.ai_base_url.textChanged.connect(self._save_config_from_ui)
        self.ai_api_key.textChanged.connect(self._save_config_from_ui)
        self.ai_model.textChanged.connect(self._save_config_from_ui)
        self.server_table.selectionModel().selectionChanged.connect(self._on_server_selected)
        self.server_name.textChanged.connect(self._save_server_detail)
        self.server_protocol.currentIndexChanged.connect(self._save_server_detail)
        self.server_url.textChanged.connect(self._save_server_detail)
        self.server_token.textChanged.connect(self._save_server_detail)
        self.server_command.textChanged.connect(self._save_server_detail)
        self.server_args.textChanged.connect(self._save_server_detail)
        self.server_enabled.toggled.connect(self._save_server_detail)

        self._apply_config_to_ui()
        return panel

    def _build_ui_state(self) -> None:
        self.server_model = None
        self.server_table = None
        self.tool_model = None
        self.tool_table = None
        self.add_server_btn = None
        self.remove_server_btn = None
        self.default_server_btn = None
        self.refresh_tools_btn = None
        self.test_server_btn = None
        self.import_json_btn = None
        self.server_name = None
        self.server_protocol = None
        self.server_url = None
        self.server_token = None
        self.server_command = None
        self.server_args = None
        self.server_enabled = None
        self.enabled_toggle = None
        self.call_mode_combo = None
        self.risk_confirm_toggle = None
        self.ai_mode_combo = None
        self.ai_base_url = None
        self.ai_api_key = None
        self.ai_model = None
        self.allowed_dirs = None
        self.add_dir_btn = None
        self.install_dir = None
        self.install_browse_btn = None
        self.npm_install_btn = None
        self.npm_build_btn = None
        self.npx_package = None
        self.npx_install_btn = None
        self.npm_path = None
        self.npx_path = None
        self.detect_tools_btn = None
        self.cancel_install_btn = None
        self.install_log = None
        self._install_proc = None
        self._install_timer = None

    def _load_config(self) -> dict:
        data = _read_json(self.config_path, {})
        config = DEFAULT_CONFIG.copy()
        config.update(data if isinstance(data, dict) else {})
        config["servers"] = _safe_list(config.get("servers")) or DEFAULT_CONFIG["servers"]
        if not config.get("default_server"):
            config["default_server"] = config["servers"][0].get("id", "default")
        return config

    def _save_config(self) -> None:
        _write_json(self.config_path, self.config)

    def _apply_config_to_ui(self) -> None:
        if not self.server_model:
            return
        self.server_model.set_rows(self.config.get("servers", []))
        self._on_server_selected()
        self.enabled_toggle.setChecked(bool(self.config.get("enabled", True)))
        self.call_mode_combo.setCurrentText(self.config.get("tool_call_mode", "strict"))
        self.risk_confirm_toggle.setChecked(bool(self.config.get("risk_confirm", {}).get("enabled", True)))
        ai_api = self.config.get("ai_api", {})
        self.ai_mode_combo.setCurrentText(ai_api.get("mode", "reuse"))
        self.ai_base_url.setText(ai_api.get("base_url", ""))
        self.ai_api_key.setText(ai_api.get("api_key", ""))
        self.ai_model.setText(ai_api.get("model", ""))
        self.allowed_dirs.clear()
        for item in self.config.get("file_scope", {}).get("allowed_dirs", []):
            self.allowed_dirs.addItem(item)
        install_tools = self.config.get("install_tools", {})
        self.npm_path.setText(install_tools.get("npm_path", ""))
        self.npx_path.setText(install_tools.get("npx_path", ""))

    def _save_config_from_ui(self) -> None:
        if not self.enabled_toggle:
            return
        self.config["enabled"] = bool(self.enabled_toggle.isChecked())
        self.config["tool_call_mode"] = self.call_mode_combo.currentText()
        self.config["risk_confirm"]["enabled"] = bool(self.risk_confirm_toggle.isChecked())
        ai_api = self.config.get("ai_api", {})
        ai_api["mode"] = self.ai_mode_combo.currentText()
        ai_api["base_url"] = self.ai_base_url.text().strip()
        ai_api["api_key"] = self.ai_api_key.text().strip()
        ai_api["model"] = self.ai_model.text().strip()
        self.config["ai_api"] = ai_api
        self.config["file_scope"]["allowed_dirs"] = [self.allowed_dirs.item(i).text() for i in range(self.allowed_dirs.count())]
        install_tools = self.config.get("install_tools", {})
        install_tools["npm_path"] = self.npm_path.text().strip()
        install_tools["npx_path"] = self.npx_path.text().strip()
        self.config["install_tools"] = install_tools
        self._save_config()

    def _on_server_selected(self) -> None:
        if not self.server_table:
            return
        index = self.server_table.currentIndex()
        row = index.row() if index.isValid() else 0
        server = self.server_model.get_row(row) if self.server_model else None
        if not server:
            return
        widgets = [
            self.server_name,
            self.server_protocol,
            self.server_url,
            self.server_token,
            self.server_command,
            self.server_enabled,
        ]
        for widget in widgets:
            widget.blockSignals(True)
        self.server_name.setText(server.get("name", ""))
        self.server_protocol.setCurrentText(server.get("protocol", "auto"))
        self.server_url.setText(server.get("url", ""))
        self.server_token.setText(server.get("token", ""))
        self.server_command.setText(server.get("command", ""))
        args = server.get("args", [])
        if not isinstance(args, list):
            args = []
        self.server_args.setText(" ".join([str(item) for item in args]))
        self.server_enabled.setChecked(bool(server.get("enabled", True)))
        for widget in widgets:
            widget.blockSignals(False)

    def _save_server_detail(self) -> None:
        index = self.server_table.currentIndex()
        if not index.isValid():
            return
        servers = self.config.get("servers", [])
        row = index.row()
        if row < 0 or row >= len(servers):
            return
        servers[row]["name"] = self.server_name.text().strip()
        servers[row]["protocol"] = self.server_protocol.currentText().strip()
        servers[row]["url"] = self.server_url.text().strip()
        servers[row]["token"] = self.server_token.text().strip()
        servers[row]["command"] = self.server_command.text().strip()
        args_text = self.server_args.text().strip()
        servers[row]["args"] = args_text.split() if args_text else []
        servers[row]["enabled"] = bool(self.server_enabled.isChecked())
        self.config["servers"] = servers
        self.server_model.set_rows(servers)
        self._save_config()

    def _add_server(self) -> None:
        servers = self.config.get("servers", [])
        new_id = f"server_{len(servers) + 1}"
        servers.append(
            {
                "id": new_id,
                "name": f"MCP Server {len(servers) + 1}",
                "protocol": "auto",
                "url": "http://localhost:3000",
                "token": "",
                "command": "",
                "enabled": True,
            }
        )
        self.config["servers"] = servers
        self.server_model.set_rows(servers)
        self._save_config()

    def _remove_server(self) -> None:
        index = self.server_table.currentIndex()
        if not index.isValid():
            return
        servers = self.config.get("servers", [])
        del servers[index.row()]
        self.config["servers"] = servers
        if self.config.get("default_server") and not any(s.get("id") == self.config["default_server"] for s in servers):
            self.config["default_server"] = servers[0].get("id", "") if servers else ""
        self.server_model.set_rows(servers)
        self._save_config()

    def _set_default_server(self) -> None:
        index = self.server_table.currentIndex()
        if not index.isValid():
            return
        row = self.server_model.get_row(index.row())
        if not row:
            return
        self.config["default_server"] = row.get("id", "")
        self._tools_cache = []
        self._save_config()
        QMessageBox.information(None, "提示", f"已设置默认服务器: {row.get('name', '')}")

    def _refresh_tools(self) -> None:
        try:
            tools = self._get_tools(refresh=True)
            self.tool_model.set_rows(tools)
            QMessageBox.information(None, "提示", f"已加载 {len(tools)} 个工具")
        except Exception as exc:
            QMessageBox.warning(None, "提示", f"加载工具失败: {exc}")

    def _test_server(self) -> None:
        server = self._select_server()
        if not server:
            QMessageBox.warning(None, "提示", "未选择 MCP 服务器")
            return
        self.test_server_btn.setEnabled(False)
        worker = ToolRequestWorker(server)

        def _done() -> None:
            self.test_server_btn.setEnabled(True)
            if worker.error:
                QMessageBox.warning(None, "提示", f"连接失败: {worker.error}")
            else:
                tools = worker.result or []
                QMessageBox.information(None, "提示", f"连接成功，工具数：{len(tools)}")

        worker.finished.connect(_done)
        worker.start()

    def _import_json(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            None,
            "导入 MCP JSON",
            "粘贴 MCP Server JSON：",
        )
        if not ok or not text.strip():
            return
        try:
            data = json.loads(text)
        except Exception as exc:
            QMessageBox.warning(None, "提示", f"JSON 解析失败: {exc}")
            return
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if not isinstance(servers, dict):
            QMessageBox.warning(None, "提示", "未找到 mcpServers 字段")
            return
        current = self.config.get("servers", [])
        for key, item in servers.items():
            if not isinstance(item, dict):
                continue
            current.append(
                {
                    "id": key,
                    "name": key,
                    "protocol": "stdio",
                    "url": "",
                    "token": "",
                    "command": str(item.get("command", "")).strip(),
                    "args": _safe_list(item.get("args")),
                    "enabled": True,
                }
            )
        self.config["servers"] = current
        if not self.config.get("default_server") and current:
            self.config["default_server"] = current[0].get("id", "")
        self.server_model.set_rows(current)
        self._save_config()
        QMessageBox.information(None, "提示", "已导入 MCP 服务器配置")

    def _add_allowed_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(None, "选择允许访问的目录")
        if not folder:
            return
        self.allowed_dirs.addItem(folder)
        self._save_config_from_ui()

    def _choose_install_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(None, "选择 MCP 项目目录")
        if not folder:
            return
        self.install_dir.setText(folder)

    def _run_npx_install(self) -> None:
        package = self.npx_package.text().strip()
        if not package:
            QMessageBox.information(None, "提示", "请输入 npx 包名")
            return
        self._run_install("npx", ["--yes", package])

    def _run_install(self, program: str, args: list[str]) -> None:
        if self._install_proc:
            QMessageBox.information(None, "提示", "已有安装任务在运行。")
            return
        custom_path = ""
        if program == "npm":
            custom_path = self.config.get("install_tools", {}).get("npm_path", "")
        if program == "npx":
            custom_path = self.config.get("install_tools", {}).get("npx_path", "")
        custom_path = custom_path.strip()
        if custom_path and os.path.isfile(custom_path):
            program = custom_path
        elif not shutil.which(program):
            QMessageBox.warning(None, "提示", f"未找到 {program}，请确认已安装并配置到 PATH。")
            return
        workdir = self.install_dir.text().strip()
        if program != "npx" and (not workdir or not os.path.isdir(workdir)):
            QMessageBox.warning(None, "提示", "请选择有效的项目目录。")
            return
        self.install_log.appendPlainText(f"> {program} {' '.join(args)}")
        proc = subprocess.Popen(
            [program, *args],
            cwd=workdir or None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._install_proc = proc
        self._set_install_busy(True)
        self._start_install_timer()

        def _reader() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    QTimer.singleShot(0, lambda text=line: self.install_log.appendPlainText(text))
            code = proc.wait()
            QTimer.singleShot(0, lambda: self._finish_install(code))

        threading.Thread(target=_reader, daemon=True).start()

    def _finish_install(self, code: int) -> None:
        self._install_proc = None
        self._stop_install_timer()
        self._set_install_busy(False)
        self.install_log.appendPlainText(f"完成，退出码: {code}")

    def _set_install_busy(self, busy: bool) -> None:
        self.install_browse_btn.setEnabled(not busy)
        self.npm_install_btn.setEnabled(not busy)
        self.npm_build_btn.setEnabled(not busy)
        self.npx_install_btn.setEnabled(not busy)
        self.detect_tools_btn.setEnabled(not busy)
        self.cancel_install_btn.setEnabled(busy)
        self.install_dir.setEnabled(not busy)
        self.npx_package.setEnabled(not busy)
        self.npm_path.setEnabled(not busy)
        self.npx_path.setEnabled(not busy)

    def _detect_install_tools(self) -> None:
        npm = shutil.which("npm") or ""
        npx = shutil.which("npx") or ""
        if npm:
            self.npm_path.setText(npm)
        if npx:
            self.npx_path.setText(npx)
        if not npm and not npx:
            QMessageBox.information(None, "提示", "未检测到 npm/npx，请确认已安装 Node.js。")

    def _cancel_install(self) -> None:
        if not self._install_proc:
            return
        proc = self._install_proc
        try:
            proc.terminate()
        except Exception:
            pass
        self._install_proc = None
        self._stop_install_timer()
        self._set_install_busy(False)
        self.install_log.appendPlainText("已取消安装任务。")

    def _start_install_timer(self) -> None:
        self._stop_install_timer()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(self._on_install_timeout)
        timer.start(300000)
        self._install_timer = timer

    def _stop_install_timer(self) -> None:
        if self._install_timer:
            self._install_timer.stop()
        self._install_timer = None

    def _on_install_timeout(self) -> None:
        if not self._install_proc:
            return
        self.install_log.appendPlainText("安装超时，已自动取消。")
        self._cancel_install()

    def _select_server(self) -> dict | None:
        default_id = self.config.get("default_server")
        for item in self.config.get("servers", []):
            if item.get("id") == default_id:
                return item
        return self.config.get("servers", [None])[0]

    def _get_tools(self, refresh: bool = False) -> list[dict]:
        if self._tools_cache and not refresh:
            return self._tools_cache
        server = self._select_server()
        if not server:
            return []
        client = MCPClient(server)
        tools = client.list_tools()
        allowlist = set(self.config.get("tool_allowlist", []))
        denylist = set(self.config.get("tool_denylist", []))
        enriched = []
        for tool in tools or []:
            name = str(tool.get("name", ""))
            enabled = True
            if allowlist:
                enabled = name in allowlist
            if name in denylist:
                enabled = False
            enriched.append(
                {
                    "name": name,
                    "description": tool.get("description", ""),
                    "risk": bool(tool.get("risk", False)),
                    "enabled": enabled,
                }
            )
        self._tools_cache = enriched
        return enriched

    def _select_tool_call(self, user_text: str, tools: list[dict]) -> dict:
        tool_descriptions = []
        for tool in tools:
            tool_descriptions.append(
                f"- {tool.get('name')}: {tool.get('description', '')}"
            )
        mode = self.config.get("tool_call_mode", "strict")
        prompt = (
            "你是工具路由器，根据用户问题选择是否调用 MCP 工具。\n"
            "可用工具如下：\n"
            + "\n".join(tool_descriptions)
            + "\n\n"
            "如果不需要工具，返回：{\"tool\": null}\n"
            "如果需要工具，返回：{\"tool\": \"tool_name\", \"args\": {}}"
        )
        reply = self._call_ai_router(user_text, prompt)
        if not reply:
            return {}
        return self._parse_tool_call(reply, strict=(mode == "strict"))

    def _call_ai_router(self, user_text: str, tool_prompt: str) -> str:
        payload = {
            "messages": [
                {"role": "system", "content": tool_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.0,
            "max_tokens": 300,
        }
        base_url, api_key, model = self._resolve_ai_settings()
        if not base_url or not api_key or not model:
            return ""
        try:
            resp = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={**payload, "model": model},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            self.context.warn(f"mcp router ai failed: {exc}")
            return ""

    def _resolve_ai_settings(self) -> tuple[str, str, str]:
        mode = self.config.get("ai_api", {}).get("mode", "reuse")
        if mode == "custom":
            api = self.config.get("ai_api", {})
            return api.get("base_url", ""), api.get("api_key", ""), api.get("model", "")
        settings = getattr(self.context, "settings", None)
        if not settings:
            return "", "", ""
        data = settings.get_settings()
        providers = data.get("ai_providers", [])
        for item in providers:
            if not isinstance(item, dict) or not item.get("enabled", True):
                continue
            return item.get("base_url", ""), item.get("api_key", ""), item.get("model", "")
        return "", "", ""

    def _parse_tool_call(self, reply: str, strict: bool) -> dict:
        text = reply.strip()
        if strict:
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    return data
            except Exception:
                return {}
            return {}
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _is_tool_allowed(self, tool_name: str) -> bool:
        allowlist = set(self.config.get("tool_allowlist", []))
        denylist = set(self.config.get("tool_denylist", []))
        if allowlist and tool_name not in allowlist:
            return False
        if tool_name in denylist:
            return False
        return True

    def _is_risky_tool(self, tool_name: str, tools: list[dict]) -> bool:
        for tool in tools:
            if tool.get("name") == tool_name and tool.get("risk"):
                return True
        keywords = ["delete", "remove", "rm", "write", "update", "drop"]
        return any(key in tool_name.lower() for key in keywords)

    def _risk_confirmation_required(self, tool_name: str) -> bool:
        risk = self.config.get("risk_confirm", {})
        if not risk.get("enabled", True):
            return False
        remembered = risk.get("remembered", {})
        return not remembered.get(tool_name, False)

    def _confirm_risk(self, tool_name: str, args: dict) -> bool:
        result = {"ok": False}
        event = threading.Event()

        def _ask() -> None:
            text = f"工具 {tool_name} 可能有风险，是否允许执行？"
            choice = QMessageBox.question(None, "高风险工具确认", text, QMessageBox.Yes | QMessageBox.No)
            result["ok"] = choice == QMessageBox.Yes
            event.set()

        self._ui_dispatcher.run.emit(_ask)
        event.wait(60)
        if result["ok"] and self.config.get("risk_confirm", {}).get("remember", True):
            self.config["risk_confirm"].setdefault("remembered", {})[tool_name] = True
            self._save_config()
        return result["ok"]

    def _call_tool(self, tool_name: str, args: dict) -> dict:
        server = self._select_server()
        if not server:
            raise RuntimeError("未配置 MCP 服务器")
        client = MCPClient(server)
        return client.call_tool(tool_name, args)

    def _append_history(self, tool_name: str, args: dict, result: dict) -> None:
        record = {
            "ts": int(time.time()),
            "tool": tool_name,
            "args": args,
            "result": result,
        }
        history = _safe_list(self.history)
        history.append(record)
        self.history = history[-200:]
        _write_json(self.history_path, self.history)


def create_plugin(context):
    return Plugin(context)
