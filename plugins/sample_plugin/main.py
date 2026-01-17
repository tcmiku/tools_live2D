from __future__ import annotations

import time


class Plugin:
    def __init__(self, context) -> None:
        self.context = context
        self._last_status = None

    def on_app_ready(self) -> None:
        self.context.block_passive(2.0)
        self.context.bridge.push_passive_message("Sample plugin ready.")

    def on_state(self, state: dict) -> None:
        status = state.get("status")
        if status == self._last_status:
            return
        self._last_status = status
        path = self.context.get_data_path("status.log")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{time.time():.0f} status={status}\n")
