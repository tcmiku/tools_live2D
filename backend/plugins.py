from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    plugin_id: str
    name: str
    version: str
    description: str
    entry: str
    root_dir: str
    manifest_path: str


class PluginContext:
    def __init__(
        self,
        plugin_id: str,
        plugin_dir: str,
        base_dir: str,
        data_dir: str,
        settings: Any,
        bridge: Any,
        log_handler=None,
        ai_context_handler=None,
        passive_block_handler=None,
    ) -> None:
        self.plugin_id = plugin_id
        self.plugin_dir = plugin_dir
        self.base_dir = base_dir
        self.data_dir = data_dir
        self.settings = settings
        self.bridge = bridge
        self._log_handler = log_handler
        self._ai_context_handler = ai_context_handler
        self._passive_block_handler = passive_block_handler

    def get_data_path(self, *parts: str) -> str:
        path = os.path.join(self.data_dir, "plugins", self.plugin_id, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def log(self, level: str, message: str) -> None:
        if not message:
            return
        if self._log_handler:
            self._log_handler(self.plugin_id, level, message)

    def info(self, message: str) -> None:
        self.log("info", message)

    def warn(self, message: str) -> None:
        self.log("warn", message)

    def error(self, message: str) -> None:
        self.log("error", message)

    def add_ai_context(self, message: str) -> None:
        if not message:
            return
        if self._ai_context_handler:
            self._ai_context_handler(self.plugin_id, message)

    def block_passive(self, seconds: float = 2.0) -> None:
        if self._passive_block_handler:
            self._passive_block_handler(seconds)


class PluginRecord:
    def __init__(self, info: PluginInfo, enabled: bool) -> None:
        self.info = info
        self.enabled = enabled
        self.module = None
        self.instance = None
        self.error = ""
        self.loaded = False
        self.panel = None
        self.context = None

    def _resolve_instance(self, module: Any, context: PluginContext) -> Any:
        if hasattr(module, "PLUGIN"):
            return getattr(module, "PLUGIN")
        if hasattr(module, "create_plugin"):
            return module.create_plugin(context)
        if hasattr(module, "Plugin"):
            return module.Plugin(context)
        return module

    def load(self, context: PluginContext) -> None:
        if not self.enabled:
            return
        self.context = context
        entry_path = os.path.join(self.info.root_dir, self.info.entry)
        if not os.path.exists(entry_path):
            self.error = f"entry not found: {entry_path}"
            return
        try:
            module_name = f"tools_live2d.plugins.{self.info.plugin_id}"
            spec = importlib.util.spec_from_file_location(module_name, entry_path)
            if not spec or not spec.loader:
                raise RuntimeError("failed to create module spec")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            instance = self._resolve_instance(module, context)
            self.module = module
            self.instance = instance
            self.loaded = True
            self.error = ""
            self.call_hook("on_load", context)
            logger.info("plugin loaded: %s", self.info.plugin_id)
        except Exception as exc:
            self.error = str(exc)
            self.loaded = False
            self.module = None
            self.instance = None
            logger.exception("plugin load failed: %s", self.info.plugin_id)

    def unload(self) -> None:
        if not self.loaded:
            return
        if self.panel and hasattr(self.panel, "close"):
            try:
                self.panel.close()
            except Exception:
                logger.exception("plugin panel close failed: %s", self.info.plugin_id)
                if self.context:
                    self.context.error("panel close failed")
        self.panel = None
        try:
            self.call_hook("on_unload")
        except Exception:
            logger.exception("plugin unload hook failed: %s", self.info.plugin_id)
            if self.context:
                self.context.error("on_unload failed")
        if self.module:
            sys.modules.pop(self.module.__name__, None)
        self.loaded = False
        self.module = None
        self.instance = None
        self.context = None

    def call_hook(self, name: str, *args: Any, **kwargs: Any) -> None:
        if not self.loaded or not self.instance:
            return
        handler = getattr(self.instance, name, None)
        if callable(handler):
            handler(*args, **kwargs)

    def open_panel(self, parent=None):
        if not self.loaded or not self.instance:
            return None
        handler = getattr(self.instance, "get_panel", None)
        if callable(handler):
            try:
                panel = handler(parent)
            except Exception:
                logger.exception("plugin get_panel failed: %s", self.info.plugin_id)
                if self.context:
                    self.context.error("get_panel failed")
                return None
            if panel:
                self.panel = panel
            return panel
        handler = getattr(self.instance, "open_panel", None)
        if callable(handler):
            try:
                panel = handler(parent)
            except Exception:
                logger.exception("plugin open_panel failed: %s", self.info.plugin_id)
                if self.context:
                    self.context.error("open_panel failed")
                return None
            if panel:
                self.panel = panel
            return panel
        return None


class PluginManager:
    def __init__(self, base_dir: str, settings: Any, bridge: Any) -> None:
        self.base_dir = base_dir
        self.settings = settings
        self.bridge = bridge
        self.data_dir = os.path.join(base_dir, "data")
        self.plugin_root = os.path.join(base_dir, "plugins")
        os.makedirs(self.plugin_root, exist_ok=True)
        self._records: dict[str, PluginRecord] = {}
        self._logs: dict[str, list[str]] = {}
        self._ai_context: list[str] = []
        self._ai_lock = threading.Lock()
        self._passive_block_until = 0.0

    def block_passive(self, seconds: float = 2.0) -> None:
        try:
            duration = float(seconds)
        except (TypeError, ValueError):
            duration = 0.0
        if duration <= 0:
            return
        self._passive_block_until = max(self._passive_block_until, time.time() + duration)

    def should_block_passive(self, reason: str = "") -> bool:
        now = time.time()
        if now < self._passive_block_until:
            return True
        for record in self._records.values():
            if not record.enabled or not record.loaded or not record.instance:
                continue
            handler = getattr(record.instance, "should_block_passive", None)
            if not callable(handler):
                handler = getattr(record.instance, "on_should_block_passive", None)
            if not callable(handler):
                continue
            try:
                result = handler(reason)
                if bool(result):
                    return True
            except Exception:
                logger.exception("plugin hook failed: %s should_block_passive", record.info.plugin_id)
                self._append_log(record.info.plugin_id, "error", "should_block_passive failed")
        return False

    def _read_manifest(self, manifest_path: str) -> PluginInfo | None:
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            logger.exception("read manifest failed: %s", manifest_path)
            return None
        plugin_id = str(data.get("id", "")).strip()
        name = str(data.get("name", "")).strip() or plugin_id
        version = str(data.get("version", "0.0.0")).strip()
        description = str(data.get("description", "")).strip()
        entry = str(data.get("entry", "main.py")).strip()
        if not plugin_id:
            logger.warning("manifest missing id: %s", manifest_path)
            return None
        root_dir = os.path.dirname(manifest_path)
        return PluginInfo(
            plugin_id=plugin_id,
            name=name,
            version=version,
            description=description,
            entry=entry,
            root_dir=root_dir,
            manifest_path=manifest_path,
        )

    def _is_plugin_dir(self, path: str) -> bool:
        return os.path.isfile(os.path.join(path, "plugin.json"))

    def _find_plugin_dirs(self, root_dir: str) -> list[str]:
        results: list[str] = []
        if not os.path.isdir(root_dir):
            return results
        for entry in os.listdir(root_dir):
            full = os.path.join(root_dir, entry)
            if os.path.isdir(full) and self._is_plugin_dir(full):
                results.append(full)
        return results

    def _scan_manifests(self) -> list[PluginInfo]:
        manifests: list[PluginInfo] = []
        if not os.path.isdir(self.plugin_root):
            return manifests
        for root, dirs, files in os.walk(self.plugin_root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            if "plugin.json" in files:
                info = self._read_manifest(os.path.join(root, "plugin.json"))
                if info:
                    manifests.append(info)
        return manifests

    def _enabled_map(self) -> dict[str, bool]:
        data = self.settings.get_settings()
        enabled = data.get("plugins_enabled")
        if isinstance(enabled, dict):
            return {str(k): bool(v) for k, v in enabled.items()}
        return {}

    def _set_enabled_map(self, enabled: dict[str, bool]) -> None:
        self.settings.set_settings({"plugins_enabled": enabled})

    def load_plugins(self) -> None:
        manifests = self._scan_manifests()
        enabled_map = self._enabled_map()
        next_records: dict[str, PluginRecord] = {}
        for info in manifests:
            enabled = enabled_map.get(info.plugin_id, True)
            record = PluginRecord(info, enabled=enabled)
            if enabled:
                context = PluginContext(
                    plugin_id=info.plugin_id,
                    plugin_dir=info.root_dir,
                    base_dir=self.base_dir,
                    data_dir=self.data_dir,
                    settings=self.settings,
                    bridge=self.bridge,
                    log_handler=self._append_log,
                    ai_context_handler=self._append_ai_context,
                    passive_block_handler=self.block_passive,
                )
                record.load(context)
                if record.error:
                    self._append_log(info.plugin_id, "error", record.error)
            next_records[info.plugin_id] = record
        for plugin_id, record in self._records.items():
            if plugin_id not in next_records:
                record.unload()
        self._records = next_records

    def reload_plugins(self) -> None:
        for record in self._records.values():
            record.unload()
        self._records = {}
        self.load_plugins()

    def reload_plugin(self, plugin_id: str) -> None:
        plugin_id = str(plugin_id or "").strip()
        if not plugin_id:
            return
        record = self._records.get(plugin_id)
        if record:
            record.unload()
        manifests = self._scan_manifests()
        info = next((item for item in manifests if item.plugin_id == plugin_id), None)
        if not info:
            return
        enabled = self._enabled_map().get(plugin_id, True)
        record = PluginRecord(info, enabled=enabled)
        if enabled:
            context = PluginContext(
                plugin_id=info.plugin_id,
                plugin_dir=info.root_dir,
                base_dir=self.base_dir,
                data_dir=self.data_dir,
                settings=self.settings,
                bridge=self.bridge,
                log_handler=self._append_log,
                ai_context_handler=self._append_ai_context,
                passive_block_handler=self.block_passive,
            )
            record.load(context)
            if record.error:
                self._append_log(info.plugin_id, "error", record.error)
        self._records[plugin_id] = record

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        plugin_id = str(plugin_id or "").strip()
        if not plugin_id:
            return
        enabled_map = self._enabled_map()
        enabled_map[plugin_id] = bool(enabled)
        self._set_enabled_map(enabled_map)
        if enabled:
            self.reload_plugin(plugin_id)
        else:
            record = self._records.get(plugin_id)
            if record:
                record.unload()
                record.enabled = False

    def export_state(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for plugin_id, record in sorted(self._records.items(), key=lambda item: item[0]):
            info = record.info
            items.append(
                {
                    "id": info.plugin_id,
                    "name": info.name,
                    "version": info.version,
                    "description": info.description,
                    "enabled": bool(record.enabled),
                    "loaded": bool(record.loaded),
                    "error": record.error or "",
                    "path": info.root_dir,
                }
            )
        return items

    def _append_log(self, plugin_id: str, level: str, message: str) -> None:
        plugin_id = str(plugin_id or "").strip()
        if not plugin_id:
            return
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}"
        items = self._logs.setdefault(plugin_id, [])
        items.append(line)
        if len(items) > 500:
            self._logs[plugin_id] = items[-500:]
        try:
            log_path = os.path.join(self.data_dir, "plugins", plugin_id, "plugin.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            logger.exception("write plugin log failed: %s", plugin_id)

    def _append_ai_context(self, plugin_id: str, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        line = f"[{plugin_id}] {text}"
        with self._ai_lock:
            self._ai_context.append(line)
            if len(self._ai_context) > 50:
                self._ai_context = self._ai_context[-50:]

    def collect_ai_context(self, user_text: str) -> list[str]:
        collected: list[str] = []
        with self._ai_lock:
            if self._ai_context:
                collected.extend(self._ai_context)
                self._ai_context = []
        for record in self._records.values():
            if not record.enabled or not record.loaded or not record.instance:
                continue
            handler = getattr(record.instance, "get_ai_context", None)
            if not callable(handler):
                handler = getattr(record.instance, "on_ai_context", None)
            if not callable(handler):
                continue
            try:
                result = handler(user_text)
                if isinstance(result, str) and result.strip():
                    collected.append(result.strip())
                elif isinstance(result, list):
                    for item in result:
                        if isinstance(item, str) and item.strip():
                            collected.append(item.strip())
            except Exception:
                logger.exception("plugin ai context failed: %s", record.info.plugin_id)
                self._append_log(record.info.plugin_id, "error", "ai context failed")
        return collected

    def get_logs(self, plugin_id: str, limit: int = 200) -> list[str]:
        plugin_id = str(plugin_id or "").strip()
        if not plugin_id:
            return []
        items = self._logs.get(plugin_id, [])
        if items:
            return items[-limit:]
        log_path = os.path.join(self.data_dir, "plugins", plugin_id, "plugin.log")
        if not os.path.exists(log_path):
            return []
        try:
            with open(log_path, "r", encoding="utf-8") as handle:
                lines = handle.read().splitlines()
            self._logs[plugin_id] = lines[-500:]
            return lines[-limit:]
        except Exception:
            logger.exception("read plugin log failed: %s", plugin_id)
            return []

    def clear_logs(self, plugin_id: str | None = None) -> None:
        if plugin_id:
            plugin_id = str(plugin_id).strip()
            if not plugin_id:
                return
            self._logs.pop(plugin_id, None)
            log_path = os.path.join(self.data_dir, "plugins", plugin_id, "plugin.log")
            try:
                if os.path.exists(log_path):
                    os.remove(log_path)
            except Exception:
                logger.exception("clear plugin log failed: %s", plugin_id)
            return
        self._logs.clear()
        plugins_dir = os.path.join(self.data_dir, "plugins")
        if not os.path.isdir(plugins_dir):
            return
        for root, _dirs, files in os.walk(plugins_dir):
            for filename in files:
                if filename != "plugin.log":
                    continue
                full_path = os.path.join(root, filename)
                try:
                    os.remove(full_path)
                except Exception:
                    logger.exception("clear plugin log failed: %s", full_path)

    def install_from_dir(self, source_dir: str) -> tuple[bool, str]:
        if not source_dir or not os.path.isdir(source_dir):
            return False, "目录不存在"
        if not self._is_plugin_dir(source_dir):
            return False, "未找到 plugin.json"
        plugin_name = os.path.basename(os.path.abspath(source_dir))
        target_dir = os.path.join(self.plugin_root, plugin_name)
        if os.path.exists(target_dir):
            return False, "目标插件已存在"
        try:
            shutil.copytree(source_dir, target_dir)
            self.reload_plugins()
            return True, "安装成功"
        except Exception as exc:
            logger.exception("install plugin failed: %s", exc)
            return False, "安装失败"

    def import_from_zip(self, zip_path: str) -> tuple[bool, str]:
        if not zip_path or not os.path.isfile(zip_path):
            return False, "文件不存在"
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmp_dir)
                plugin_dirs = self._find_plugin_dirs(tmp_dir)
                if not plugin_dirs:
                    return False, "压缩包内未找到插件"
                for plugin_dir in plugin_dirs:
                    plugin_name = os.path.basename(os.path.abspath(plugin_dir))
                    target_dir = os.path.join(self.plugin_root, plugin_name)
                    if os.path.exists(target_dir):
                        return False, f"插件已存在: {plugin_name}"
                    shutil.copytree(plugin_dir, target_dir)
            self.reload_plugins()
            return True, "导入成功"
        except Exception as exc:
            logger.exception("import plugin failed: %s", exc)
            return False, "导入失败"

    def export_to_zip(self, plugin_id: str, target_path: str) -> tuple[bool, str]:
        plugin_id = str(plugin_id or "").strip()
        if not plugin_id:
            return False, "插件 ID 为空"
        record = self._records.get(plugin_id)
        if not record:
            return False, "插件不存在"
        source_dir = record.info.root_dir
        if not target_path:
            return False, "目标路径为空"
        try:
            with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(source_dir):
                    for filename in files:
                        full_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(full_path, os.path.dirname(source_dir))
                        zf.write(full_path, rel_path)
            return True, "导出成功"
        except Exception as exc:
            logger.exception("export plugin failed: %s", exc)
            return False, "导出失败"

    def uninstall_plugin(self, plugin_id: str) -> tuple[bool, str]:
        plugin_id = str(plugin_id or "").strip()
        if not plugin_id:
            return False, "插件 ID 为空"
        record = self._records.get(plugin_id)
        if not record:
            return False, "插件不存在"
        try:
            record.unload()
            shutil.rmtree(record.info.root_dir, ignore_errors=False)
            enabled_map = self._enabled_map()
            enabled_map.pop(plugin_id, None)
            self._set_enabled_map(enabled_map)
            self.reload_plugins()
            return True, "卸载成功"
        except Exception as exc:
            logger.exception("uninstall plugin failed: %s", exc)
            return False, "卸载失败"

    def open_plugin_panel(self, plugin_id: str, parent=None):
        plugin_id = str(plugin_id or "").strip()
        if not plugin_id:
            return None
        record = self._records.get(plugin_id)
        if not record or not record.loaded:
            return None
        return record.open_panel(parent)

    def _dispatch(self, hook: str, *args: Any, **kwargs: Any) -> None:
        for record in self._records.values():
            if not record.enabled or not record.loaded:
                continue
            try:
                record.call_hook(hook, *args, **kwargs)
            except Exception:
                logger.exception("plugin hook failed: %s %s", record.info.plugin_id, hook)
                self._append_log(record.info.plugin_id, "error", f"{hook} failed")

    def on_app_start(self) -> None:
        self._dispatch("on_app_start")

    def on_app_ready(self) -> None:
        self._dispatch("on_app_ready")

    def on_settings_updated(self, settings: dict[str, Any]) -> None:
        self._dispatch("on_settings", settings)

    def on_state(self, state: dict[str, Any]) -> None:
        self._dispatch("on_state", state)

    def on_tick(self, state: dict[str, Any], now: float) -> None:
        self._dispatch("on_tick", state, now)

    def on_ai_reply(self, text: str) -> None:
        self._dispatch("on_ai_reply", text)

    def on_user_message(self, text: str) -> None:
        self._dispatch("on_user_message", text)

    def on_passive_message(self, text: str) -> None:
        self._dispatch("on_passive_message", text)

    def shutdown(self) -> None:
        for record in self._records.values():
            record.unload()
