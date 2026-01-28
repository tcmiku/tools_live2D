from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any


class ClipboardHistory:
    def __init__(self, path: str, max_items: int = 30) -> None:
        self._path = path
        self._max_items = max_items
        self._items: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._items = data[: self._max_items]
        except Exception as exc:
            logging.exception("clipboard load failed: %s", exc)
            self._items = []

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logging.exception("clipboard save failed: %s", exc)

    def get_items(self) -> List[Dict[str, Any]]:
        return list(self._items)

    def add_text(self, text: str) -> bool:
        clean = text.strip()
        if not clean:
            return False
        if self._items and self._items[0].get("text") == clean:
            return False
        entry = {
            "text": clean,
            "time": datetime.now().isoformat(timespec="seconds"),
        }
        self._items.insert(0, entry)
        self._items = self._items[: self._max_items]
        self._save()
        return True

    def clear(self) -> None:
        self._items = []
        self._save()
