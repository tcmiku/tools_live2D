from __future__ import annotations

from typing import Any


class PromptComposer:
    def _pick(self, data: dict, *keys: str) -> Any:
        for key in keys:
            if key in data and data[key]:
                return data[key]
        return ""

    def _format_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            return "\n".join(parts)
        if isinstance(value, dict):
            parts = [f"{k}: {v}" for k, v in value.items() if str(v).strip()]
            return "\n".join(parts)
        return str(value).strip()

    def compose_injection(self, recall_data: dict) -> str:
        if not isinstance(recall_data, dict):
            return ""
        profile = self._format_value(
            self._pick(recall_data, "PERSONA_PROFILE", "persona_profile", "profile")
        )
        memory = self._format_value(
            self._pick(recall_data, "PERSONA_MEMORY", "persona_memory", "memory")
        )
        snippets = self._format_value(
            self._pick(recall_data, "CHAT_SNIPPETS", "chat_snippets", "snippets")
        )
        if not (profile or memory or snippets):
            return ""
        blocks = ["[PLASTIC_MEMORIES_INJECTION]"]
        if profile:
            blocks.append("[PERSONA_PROFILE]")
            blocks.append(profile)
        if memory:
            blocks.append("[PERSONA_MEMORY]")
            blocks.append(memory)
        if snippets:
            blocks.append("[CHAT_SNIPPETS]")
            blocks.append(snippets)
        blocks.append("[/PLASTIC_MEMORIES_INJECTION]")
        return "\n".join(blocks)

    def build_system_prompt(self, base_system: str, recall_data: dict) -> str:
        injection = self.compose_injection(recall_data)
        if not injection:
            return base_system or ""
        base = str(base_system or "").rstrip()
        if base:
            return f"{base}\n\n{injection}"
        return injection
