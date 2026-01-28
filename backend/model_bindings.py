from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class MotionBinding:
    motion: str | None = None
    expression: str | None = None


@dataclass
class ModelBindings:
    name: str
    bindings: dict[str, dict[str, MotionBinding]]
    default_binding: MotionBinding


class ModelBindingManager:
    def __init__(self, path: str) -> None:
        self._path = path
        self._data: Dict[str, Any] = {}
        self._load()

    def _default_data(self) -> Dict[str, Any]:
        return {
            "presets": {
                "日常": {
                    "name": "日常模式",
                    "bindings": {
                        "mood_开心": {"motion": "Tap", "expression": None},
                        "mood_愉快": {"motion": "Flick", "expression": None},
                        "mood_平静": {"motion": "Idle", "expression": None},
                        "status_active": {"motion": "Tap", "expression": None},
                        "status_idle": {"motion": "Idle", "expression": None},
                        "pomodoro_focus": {"motion": "Tap", "expression": None},
                        "ai_greeting": {"motion": "Tap", "expression": None},
                    },
                }
            },
            "models": {},
        }

    def _load(self) -> None:
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = self._default_data()
        else:
            self._data = self._default_data()

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _ensure_model(self, model_path: str) -> Dict[str, Any]:
        models = self._data.setdefault("models", {})
        if model_path not in models:
            name = os.path.splitext(os.path.basename(model_path))[0] or model_path
            models[model_path] = {"name": name, "bindings": {}, "default": {"motion": "Idle", "expression": None}}
        return models[model_path]

    def _normalize_binding(self, raw: dict | None) -> MotionBinding:
        if not isinstance(raw, dict):
            return MotionBinding()
        motion = raw.get("motion")
        expression = raw.get("expression")
        return MotionBinding(motion or None, expression or None)

    def _flatten_bindings(self, bindings: dict) -> dict[str, dict]:
        flat: dict[str, dict] = {}
        for category, items in bindings.items():
            if not isinstance(items, dict):
                continue
            for key, binding in items.items():
                flat[f"{category}_{key}"] = {
                    "motion": binding.get("motion"),
                    "expression": binding.get("expression"),
                }
        return flat

    def _expand_bindings(self, bindings: dict) -> dict[str, dict]:
        expanded: dict[str, dict] = {}
        for key, value in bindings.items():
            if not isinstance(value, dict):
                continue
            if "_" not in key:
                continue
            category, item_key = key.split("_", 1)
            expanded.setdefault(category, {})[item_key] = {
                "motion": value.get("motion"),
                "expression": value.get("expression"),
            }
        return expanded

    def get_model(self, model_path: str) -> dict:
        model = self._ensure_model(model_path)
        return {
            "model_path": model_path,
            "name": model.get("name", model_path),
            "bindings": model.get("bindings", {}),
            "default": model.get("default", {"motion": "Idle", "expression": None}),
        }

    def get_binding(self, model_path: str, category: str, key: str) -> MotionBinding:
        model = self._ensure_model(model_path)
        bindings = model.get("bindings", {})
        if isinstance(bindings, dict):
            cat = bindings.get(category, {})
            if isinstance(cat, dict) and key in cat:
                return self._normalize_binding(cat.get(key))
        default = model.get("default")
        return self._normalize_binding(default if isinstance(default, dict) else None)

    def set_binding(self, model_path: str, category: str, key: str, binding: MotionBinding) -> None:
        model = self._ensure_model(model_path)
        bindings = model.setdefault("bindings", {})
        if category == "default":
            model["default"] = {"motion": binding.motion, "expression": binding.expression}
        else:
            category_map = bindings.setdefault(category, {})
            category_map[key] = {"motion": binding.motion, "expression": binding.expression}
        self._save()

    def reset_model(self, model_path: str) -> None:
        model = self._ensure_model(model_path)
        model["bindings"] = {}
        self._save()

    def get_all_models(self) -> dict:
        return self._data.get("models", {})

    def get_presets(self) -> dict:
        return self._data.get("presets", {})

    def apply_preset(self, model_path: str, preset_name: str) -> bool:
        presets = self._data.get("presets", {})
        preset = presets.get(preset_name)
        if not isinstance(preset, dict):
            return False
        raw_bindings = preset.get("bindings", {})
        if not isinstance(raw_bindings, dict):
            return False
        if any("_" in key for key in raw_bindings.keys()):
            bindings = self._expand_bindings(raw_bindings)
        else:
            bindings = raw_bindings
        model = self._ensure_model(model_path)
        model["bindings"] = bindings
        self._save()
        return True

    def export_preset(self, model_path: str) -> dict:
        model = self._ensure_model(model_path)
        bindings = model.get("bindings", {})
        return {
            "name": model.get("name", model_path),
            "bindings": self._flatten_bindings(bindings),
        }

    def save_preset(self, model_path: str, preset_name: str) -> bool:
        name = preset_name.strip()
        if not name:
            return False
        preset = self.export_preset(model_path)
        preset["name"] = name
        presets = self._data.setdefault("presets", {})
        presets[name] = preset
        self._save()
        return True

    def import_preset(self, preset_data: dict) -> bool:
        if not isinstance(preset_data, dict):
            return False
        name = str(preset_data.get("name", "")).strip() or "导入预设"
        bindings = preset_data.get("bindings", {})
        if not isinstance(bindings, dict):
            return False
        presets = self._data.setdefault("presets", {})
        presets[name] = {"name": name, "bindings": bindings}
        self._save()
        return True
