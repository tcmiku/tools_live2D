from __future__ import annotations

import json
import logging
import os
from typing import Dict, Any


class AppSettings:
    def __init__(self, path: str | None = None) -> None:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self._path = path or os.path.join(base_dir, "data", "settings.json")
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            self._migrate_model_config()
            logging.info("settings loaded: %s", self._path)
        except Exception as exc:
            logging.exception("settings read failed: %s", exc)
            self._data = {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logging.exception("settings write failed: %s", exc)

    def _migrate_model_config(self) -> None:
        model_cfg = self._data.get("model_config")
        if not isinstance(model_cfg, dict):
            return
        settings = self._data.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}
        mapping = {
            "scale": "model_scale",
            "x": "model_x",
            "y": "model_y",
            "xOffset": "model_x_offset",
            "yOffset": "model_y_offset",
        }
        changed = False
        for key, target in mapping.items():
            if key in model_cfg and target not in settings:
                settings[target] = model_cfg[key]
                changed = True
        if changed:
            self._data["settings"] = settings
        self._data.pop("model_config", None)
        if changed:
            self._save()

    def get_settings(self) -> Dict[str, Any]:
        default = {
            "focus_active_ms": 60000,
            "focus_sleep_ms": 120000,
            "window_opacity": 100,
            "model_scale": 0.35,
            "model_x": 0.6,
            "model_y": 0.65,
            "model_x_offset": 0.0,
            "model_y_offset": 0.0,
            "model_path": "model/miku/miku.model3.json",
            "ui_scale": 1.0,
            "animation_speed": 1.0,
            "pomodoro_focus_min": 25,
            "pomodoro_break_min": 5,
            "rest_enabled": True,
            "rest_interval_min": 90,
            "water_enabled": True,
            "water_interval_min": 60,
            "eye_enabled": True,
            "eye_interval_min": 45,
            "ai_provider": "OpenAI兼容",
            "ai_base_url": "https://api.openai.com/v1",
            "ai_model": "gpt-4o-mini",
            "ai_api_key": "",
            "ai_providers": [
                {
                    "name": "OpenAI兼容",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4o-mini",
                    "api_key": "",
                    "enabled": True,
                }
            ],
            "passive_enabled": True,
            "passive_interval_min": 30,
            "passive_random_enabled": True,
            "passive_blessing_enabled": True,
            "passive_focus_enabled": True,
            "passive_focus_interval_min": 60,
            "local_city": "",
            "local_location": "",
            "favor": 50,
            "mood": 60,
            "hotkey_toggle_pet": "Ctrl+Shift+L",
            "hotkey_note": "Ctrl+Shift+P",
            "hotkey_pomodoro": "Ctrl+Shift+T",
            "hotkey_model_edit": "Ctrl+Shift+M",
            "hotkey_launcher_panel": "Ctrl+Shift+Space",
            "last_login_date": "",
            "login_streak": 0,
            "model_edit_mode": False,
            "bindings_path": "data/model_bindings.json",
        }
        stored = self._data.get("settings", {})
        if not isinstance(stored, dict):
            return default
        merged = default.copy()
        for key, value in stored.items():
            merged[key] = value
        merged["ai_providers"] = self._normalize_ai_providers(merged)
        first = merged["ai_providers"][0]
        merged["ai_provider"] = first.get("name", "OpenAI兼容")
        merged["ai_base_url"] = first.get("base_url", "https://api.openai.com/v1")
        merged["ai_model"] = first.get("model", "gpt-4o-mini")
        merged["ai_api_key"] = first.get("api_key", "")
        logging.info("settings merged: model_scale=%s ui_scale=%s opacity=%s", merged["model_scale"], merged["ui_scale"], merged["window_opacity"])
        return merged

    def set_settings(self, values: Dict[str, Any]) -> None:
        if not isinstance(values, dict):
            return
        current = self.get_settings()
        for key in current.keys():
            if key in values:
                current[key] = values[key]
        if "favor" in current:
            try:
                current["favor"] = max(0, min(100, int(current["favor"])))
            except (TypeError, ValueError):
                current["favor"] = 50
        if "mood" in current:
            try:
                current["mood"] = max(0, min(100, int(current["mood"])))
            except (TypeError, ValueError):
                current["mood"] = 60
        current["ai_providers"] = self._normalize_ai_providers(current)
        first = current["ai_providers"][0]
        current["ai_provider"] = first.get("name", "OpenAI兼容")
        current["ai_base_url"] = first.get("base_url", "https://api.openai.com/v1")
        current["ai_model"] = first.get("model", "gpt-4o-mini")
        current["ai_api_key"] = first.get("api_key", "")
        self._data["settings"] = current
        self._save()

    def _normalize_ai_providers(self, data: Dict[str, Any]) -> list[Dict[str, Any]]:
        providers = data.get("ai_providers")
        if isinstance(providers, list) and providers:
            normalized = []
            fallback_key = str(data.get("ai_api_key", "")).strip()
            fallback_url = str(data.get("ai_base_url", "https://api.openai.com/v1")).strip()
            fallback_model = str(data.get("ai_model", "gpt-4o-mini")).strip()
            default_url = "https://api.openai.com/v1"
            default_model = "gpt-4o-mini"
            for item in providers:
                if not isinstance(item, dict):
                    continue
                api_key = str(item.get("api_key", "")).strip() or fallback_key
                base_url = str(item.get("base_url", "")).strip() or fallback_url
                model = str(item.get("model", "")).strip() or fallback_model
                if fallback_url and base_url == default_url:
                    base_url = fallback_url
                if fallback_model and model == default_model:
                    model = fallback_model
                normalized.append(
                    {
                        "name": str(item.get("name", "OpenAI兼容")),
                        "base_url": base_url,
                        "model": model,
                        "api_key": api_key,
                        "enabled": bool(item.get("enabled", True)),
                    }
                )
            if normalized:
                return normalized
        return [
            {
                "name": str(data.get("ai_provider", "OpenAI兼容")),
                "base_url": str(data.get("ai_base_url", "https://api.openai.com/v1")),
                "model": str(data.get("ai_model", "gpt-4o-mini")),
                "api_key": str(data.get("ai_api_key", "")),
                "enabled": True,
            }
        ]

    def get_model_config(self) -> Dict[str, float]:
        settings = self.get_settings()
        return {
            "scale": float(settings["model_scale"]),
            "x": float(settings["model_x"]),
            "y": float(settings["model_y"]),
            "xOffset": float(settings["model_x_offset"]),
            "yOffset": float(settings["model_y_offset"]),
            "uiScale": float(settings["ui_scale"]),
            "animationSpeed": float(settings["animation_speed"]),
        }

    def set_model_config(self, config: Dict[str, Any]) -> None:
        if not isinstance(config, dict):
            return
        current = self.get_settings()
        mapping = {
            "scale": "model_scale",
            "x": "model_x",
            "y": "model_y",
            "xOffset": "model_x_offset",
            "yOffset": "model_y_offset",
            "uiScale": "ui_scale",
            "animationSpeed": "animation_speed",
        }
        for key, target in mapping.items():
            if key in config:
                try:
                    current[target] = float(config[key])
                except (TypeError, ValueError):
                    continue
        self._data["settings"] = current
        self._save()
