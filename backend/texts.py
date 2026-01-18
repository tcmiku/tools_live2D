from __future__ import annotations

import json
import logging
import os
from typing import Any, Iterable


class TextCatalog:
    def __init__(self, path: str) -> None:
        self._path = path
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as handle:
                    self._data = json.load(handle) or {}
        except Exception as exc:
            logging.exception("texts read failed: %s", exc)
            self._data = {}

    def _normalize_items(self, items: Iterable[str]) -> list[str]:
        output: list[str] = []
        for item in items:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text:
                output.append(text)
        return output

    def add_texts(self, path: str, items: Iterable[str]) -> None:
        parts = [part for part in str(path).split(".") if part]
        if not parts:
            return
        node: dict[str, Any] = self._data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        key = parts[-1]
        current = node.get(key)
        values = []
        if isinstance(current, list):
            values = list(current)
        values.extend(self._normalize_items(items))
        node[key] = values

    def get_list(self, path: str, fallback: list[str]) -> list[str]:
        parts = [part for part in str(path).split(".") if part]
        node: Any = self._data
        for part in parts:
            if not isinstance(node, dict):
                return fallback
            node = node.get(part)
        if isinstance(node, list):
            values = self._normalize_items(node)
            return values or fallback
        return fallback

    def get_text(self, path: str, fallback: str) -> str:
        parts = [part for part in str(path).split(".") if part]
        node: Any = self._data
        for part in parts:
            if not isinstance(node, dict):
                return fallback
            node = node.get(part)
        if isinstance(node, str) and node.strip():
            return node.strip()
        return fallback
