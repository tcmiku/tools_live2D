from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryItem:
    memory_type: str
    key: str
    content: str


class MemoryPolicy:
    _name_patterns = [
        re.compile(r"(?:叫我|称呼我为)\s*([^\s，。！!？?]{1,20})"),
        re.compile(r"我叫\s*([^\s，。！!？?]{1,20})"),
    ]

    def extract(self, user_text: str, assistant_text: str | None = None) -> list[MemoryItem]:
        text = str(user_text or "").strip()
        if not text:
            return []
        items: dict[str, MemoryItem] = {}

        name = self._extract_name(text)
        if name:
            items["user_name"] = MemoryItem("preferences", "user_name", name)

        if "以后用中文" in text or "默认用中文" in text:
            items["language"] = MemoryItem("preferences", "language", "zh-CN")

        if "步骤列表" in text or "最小可运行" in text or "MVP" in text.upper():
            items["response_style"] = MemoryItem(
                "preferences",
                "response_style",
                "步骤列表/最小可运行/MVP",
            )

        return list(items.values())

    def _extract_name(self, text: str) -> str:
        for pattern in self._name_patterns:
            match = pattern.search(text)
            if match:
                return match.group(1).strip()
        return ""
