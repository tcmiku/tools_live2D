from __future__ import annotations

import json
import logging
import os
import subprocess
import webbrowser
from dataclasses import dataclass
from typing import Any, List


@dataclass
class LauncherResult:
    ok: bool
    message: str


class LauncherManager:
    def __init__(self, path: str) -> None:
        self._path = path
        self._data: dict[str, Any] = {"launchers": [], "recent": []}
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            if not isinstance(self._data, dict):
                self._data = {"launchers": [], "recent": []}
        except Exception as exc:
            logging.exception("launcher read failed: %s", exc)
            self._data = {"launchers": [], "recent": []}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logging.exception("launcher write failed: %s", exc)

    def _next_id(self) -> int:
        existing = [int(item.get("id", 0)) for item in self._data.get("launchers", []) if isinstance(item, dict)]
        return (max(existing) + 1) if existing else 1

    def get_all(self) -> list[dict[str, Any]]:
        items = self._data.get("launchers", [])
        return items if isinstance(items, list) else []

    def get_recent_ids(self) -> list[int]:
        recent = self._data.get("recent", [])
        if not isinstance(recent, list):
            return []
        return [int(x) for x in recent if isinstance(x, int)]

    def get_recent(self) -> list[dict[str, Any]]:
        recent_ids = self.get_recent_ids()
        lookup = {int(item.get("id", 0)): item for item in self.get_all() if isinstance(item, dict)}
        return [lookup[i] for i in recent_ids if i in lookup]

    def save_launcher(self, launcher: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(launcher, dict):
            return {}
        items = self.get_all()
        launcher_id = launcher.get("id")
        if not launcher_id:
            launcher_id = self._next_id()
        normalized = self._normalize_launcher({**launcher, "id": launcher_id})
        updated = False
        for idx, item in enumerate(items):
            if int(item.get("id", 0)) == int(launcher_id):
                items[idx] = normalized
                updated = True
                break
        if not updated:
            items.append(normalized)
        self._data["launchers"] = items
        self._save()
        return normalized

    def delete_launcher(self, launcher_id: int) -> bool:
        items = self.get_all()
        before = len(items)
        items = [item for item in items if int(item.get("id", 0)) != int(launcher_id)]
        if len(items) == before:
            return False
        self._data["launchers"] = items
        recent = [rid for rid in self.get_recent_ids() if rid != int(launcher_id)]
        self._data["recent"] = recent
        self._save()
        return True

    def search(self, query: str = "", tag: str | None = None) -> list[dict[str, Any]]:
        query = (query or "").strip().lower()
        tag = (tag or "").strip().lower()
        items = [item for item in self.get_all() if isinstance(item, dict)]

        def score(item: dict[str, Any]) -> int:
            name = str(item.get("name", "")).lower()
            tags = [str(t).lower() for t in item.get("tags", []) if isinstance(t, str)]
            hit = (query in name) or any(query in t for t in tags)
            if query and not hit:
                return -1
            if tag and tag not in tags:
                return -1
            usage = int(item.get("usage_count", 0))
            recent = 1 if int(item.get("id", 0)) in self.get_recent_ids() else 0
            return usage + (recent * 50)

        scored = [(score(item), item) for item in items]
        scored = [pair for pair in scored if pair[0] >= 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    def execute(self, launcher_id: int) -> LauncherResult:
        item = self._find_by_id(int(launcher_id))
        if not item:
            return LauncherResult(False, "启动项不存在")
        result = self._execute_item(item)
        if result.ok:
            self._touch_usage(int(launcher_id))
        return result

    def export_data(self) -> dict[str, Any]:
        return {
            "launchers": self.get_all(),
            "recent": self.get_recent_ids(),
        }

    def import_data(self, data: dict[str, Any]) -> bool:
        if not isinstance(data, dict):
            return False
        launchers = data.get("launchers", [])
        if not isinstance(launchers, list):
            return False
        self._data["launchers"] = [self._normalize_launcher(item) for item in launchers if isinstance(item, dict)]
        recent = data.get("recent", [])
        self._data["recent"] = [int(x) for x in recent if isinstance(x, int)] if isinstance(recent, list) else []
        self._save()
        return True

    def _normalize_launcher(self, launcher: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(launcher.get("id", 0)) or self._next_id(),
            "name": str(launcher.get("name", "未命名")),
            "type": str(launcher.get("type", "web")),
            "url": str(launcher.get("url", "")),
            "path": str(launcher.get("path", "")),
            "args": launcher.get("args", []) if isinstance(launcher.get("args", []), list) else [],
            "items": launcher.get("items", []) if isinstance(launcher.get("items", []), list) else [],
            "icon": str(launcher.get("icon", "")),
            "tags": [str(t) for t in launcher.get("tags", []) if isinstance(t, str)],
            "hotkey": str(launcher.get("hotkey", "")),
            "usage_count": int(launcher.get("usage_count", 0)),
        }

    def _find_by_id(self, launcher_id: int) -> dict[str, Any] | None:
        for item in self.get_all():
            if int(item.get("id", 0)) == int(launcher_id):
                return item
        return None

    def _touch_usage(self, launcher_id: int) -> None:
        items = self.get_all()
        for item in items:
            if int(item.get("id", 0)) == launcher_id:
                item["usage_count"] = int(item.get("usage_count", 0)) + 1
                break
        recent = [launcher_id] + [rid for rid in self.get_recent_ids() if rid != launcher_id]
        self._data["recent"] = recent[:10]
        self._data["launchers"] = items
        self._save()

    def _execute_item(self, item: dict[str, Any]) -> LauncherResult:
        kind = str(item.get("type", "web"))
        try:
            if kind == "web":
                url = str(item.get("url", "")).strip()
                if not url:
                    return LauncherResult(False, "URL 为空")
                webbrowser.open(url)
                return LauncherResult(True, "已打开网页")
            if kind == "app":
                path = str(item.get("path", "")).strip()
                if not path:
                    return LauncherResult(False, "路径为空")
                args = item.get("args", []) if isinstance(item.get("args", []), list) else []
                subprocess.Popen([path, *args])
                return LauncherResult(True, "已启动应用")
            if kind == "group":
                items = item.get("items", []) if isinstance(item.get("items", []), list) else []
                for child in items:
                    if isinstance(child, dict) and "launcher_id" in child:
                        ref = self._find_by_id(int(child.get("launcher_id", 0)))
                        if ref:
                            self._execute_item(ref)
                        continue
                    if isinstance(child, dict):
                        self._execute_item(self._normalize_launcher(child))
                return LauncherResult(True, "已启动套件")
            return LauncherResult(False, "未知启动类型")
        except Exception as exc:
            logging.exception("launcher execute failed: %s", exc)
            return LauncherResult(False, "启动失败")
