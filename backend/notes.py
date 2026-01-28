from __future__ import annotations

import logging
import os


class NoteStore:
    def __init__(self, path: str) -> None:
        self._path = path

    def load(self) -> str:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception as exc:
            logging.exception("note load failed: %s", exc)
        return ""

    def save(self, text: str) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as exc:
            logging.exception("note save failed: %s", exc)
