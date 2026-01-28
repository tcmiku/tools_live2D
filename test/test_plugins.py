import json
from pathlib import Path

from backend.plugins import PluginManager


class DummyBridge:
    pass


class DummySettings:
    def __init__(self) -> None:
        self._data = {"plugins_enabled": {}}

    def get_settings(self) -> dict:
        return dict(self._data)

    def set_settings(self, values: dict) -> None:
        self._data.update(values or {})


def _write_plugin(base_dir: Path) -> Path:
    plugin_dir = base_dir / "plugins" / "demo_plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "id": "demo_plugin",
                "name": "Demo Plugin",
                "version": "0.1.0",
                "description": "Test plugin",
                "entry": "main.py",
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text(
        "\n".join(
            [
                "import json",
                "",
                "_CTX = None",
                "",
                "def _record(ctx, name, payload=None):",
                "    path = ctx.get_data_path('calls.json')",
                "    try:",
                "        with open(path, 'r', encoding='utf-8') as handle:",
                "            items = json.loads(handle.read())",
                "        if not isinstance(items, list):",
                "            items = []",
                "    except Exception:",
                "        items = []",
                "    items.append({'name': name, 'payload': payload})",
                "    with open(path, 'w', encoding='utf-8') as handle:",
                "        json.dump(items, handle)",
                "",
                "class Plugin:",
                "    def __init__(self, context):",
                "        self.context = context",
                "",
                "    def on_load(self, context):",
                "        global _CTX",
                "        _CTX = context",
                "        _record(context, 'on_load')",
                "",
                "    def on_unload(self):",
                "        _record(_CTX, 'on_unload')",
                "",
                "    def on_app_start(self):",
                "        _record(self.context, 'on_app_start')",
                "",
                "    def on_app_ready(self):",
                "        _record(self.context, 'on_app_ready')",
                "",
                "    def on_settings(self, settings_dict):",
                "        _record(self.context, 'on_settings', settings_dict)",
                "",
                "    def on_state(self, state_dict):",
                "        _record(self.context, 'on_state', state_dict)",
                "",
                "    def on_tick(self, state_dict, now_ts):",
                "        _record(self.context, 'on_tick', {'state': state_dict, 'now': now_ts})",
                "",
                "    def on_user_message(self, text):",
                "        _record(self.context, 'on_user_message', text)",
                "        self.context.add_ai_context('queued context')",
                "",
                "    def on_ai_reply(self, text):",
                "        _record(self.context, 'on_ai_reply', text)",
                "",
                "    def on_passive_message(self, text):",
                "        _record(self.context, 'on_passive_message', text)",
                "",
                "    def get_ai_context(self, text):",
                "        _record(self.context, 'get_ai_context', text)",
                "        return 'hook context'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return plugin_dir


def _load_calls(base_dir: Path) -> list[dict]:
    calls_path = base_dir / "data" / "plugins" / "demo_plugin" / "calls.json"
    if not calls_path.exists():
        return []
    return json.loads(calls_path.read_text(encoding="utf-8"))


def test_plugin_hooks_called(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    manager = PluginManager(str(tmp_path), DummySettings(), DummyBridge())
    manager.load_plugins()
    manager.on_app_start()
    manager.on_app_ready()
    manager.on_settings_updated({"alpha": 1})
    manager.on_state({"status": "active"})
    manager.on_tick({"status": "active"}, 123.0)
    manager.on_user_message("hello")
    manager.on_ai_reply("hi")
    manager.on_passive_message("ping")
    manager.collect_ai_context("weather")
    manager.shutdown()

    calls = _load_calls(tmp_path)
    names = [item.get("name") for item in calls]
    assert "on_load" in names
    assert "on_app_start" in names
    assert "on_app_ready" in names
    assert "on_settings" in names
    assert "on_state" in names
    assert "on_tick" in names
    assert "on_user_message" in names
    assert "on_ai_reply" in names
    assert "on_passive_message" in names
    assert "get_ai_context" in names
    assert "on_unload" in names


def test_plugin_ai_context_and_clear_logs(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    manager = PluginManager(str(tmp_path), DummySettings(), DummyBridge())
    manager.load_plugins()

    manager.on_user_message("hello")
    context = manager.collect_ai_context("天气怎么样")
    assert any("queued context" in item for item in context)
    assert any("hook context" in item for item in context)

    manager._append_log("demo_plugin", "info", "demo log")
    assert manager.get_logs("demo_plugin")
    manager.clear_logs("demo_plugin")
    assert manager.get_logs("demo_plugin") == []
