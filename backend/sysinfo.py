from __future__ import annotations

import logging
from typing import Dict, Any

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None


class SystemInfo:
    def __init__(self) -> None:
        self._last_net = None

    def snapshot(self) -> Dict[str, Any]:
        if not psutil:
            return {
                "cpu": None,
                "memory": None,
                "net_up": None,
                "net_down": None,
                "battery": None,
            }
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            net = psutil.net_io_counters()
            up = None
            down = None
            if self._last_net:
                delta_sent = net.bytes_sent - self._last_net.bytes_sent
                delta_recv = net.bytes_recv - self._last_net.bytes_recv
                up = max(0, int(delta_sent))
                down = max(0, int(delta_recv))
            self._last_net = net
            battery = psutil.sensors_battery()
            battery_percent = None
            if battery:
                battery_percent = int(battery.percent)
            return {
                "cpu": cpu,
                "memory": mem,
                "net_up": up,
                "net_down": down,
                "battery": battery_percent,
            }
        except Exception as exc:
            logging.exception("sysinfo snapshot failed: %s", exc)
            return {
                "cpu": None,
                "memory": None,
                "net_up": None,
                "net_down": None,
                "battery": None,
            }
