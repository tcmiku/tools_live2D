from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


DEFAULT_CONFIG = {
    "enabled": True,
    "auto_check_interval_min": 60,
    "timeout_sec": 3,
    "site_list": [
        "https://www.baidu.com",
        "https://www.google.com",
        "https://www.github.com",
        "https://gitee.com",
        "https://www.bilibili.com",
        "https://www.zhihu.com",
        "https://www.csdn.net",
        "https://stackoverflow.com",
        "https://developer.mozilla.org",
        "https://www.aliyun.com",
        "https://cloud.tencent.com",
    ],
}


def _read_json(path: str, fallback: Any) -> Any:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
    except Exception:
        pass
    return fallback


def _write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _normalize_url(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    return value


def _split_host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or url
    if parsed.port:
        return host, parsed.port
    if parsed.scheme == "http":
        return host, 80
    return host, 443


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


class Plugin:
    def __init__(self, context) -> None:
        self.context = context
        self.config_path = context.get_data_path("config.json")
        self.history_path = context.get_data_path("history.json")
        self.config = self._load_config()
        self.history = self._load_history()
        self._last_check_ts = 0.0
        self._checking = False
        self._diagnosing = False
        self._check_seq = 0
        self._panel = None
        self._score_label = None
        self._summary_label = None
        self._suggest_label = None
        self._status_label = None
        self._site_table = None
        self._diagnose_box = None
        self._enabled_toggle = None
        self._interval_spin = None
        self._timeout_spin = None
        self._site_text = None

    def on_load(self, context) -> None:
        self.context.info("network diag plugin loaded")

    def on_unload(self) -> None:
        self._save_config()
        self._save_history()

    def on_tick(self, state_dict: dict, now_ts: float) -> None:
        if not self.config.get("enabled", True):
            return
        interval_min = max(5, _safe_int(self.config.get("auto_check_interval_min"), 60))
        if now_ts - self._last_check_ts < interval_min * 60:
            return
        if self._checking:
            return
        self._last_check_ts = now_ts
        self._start_site_check(auto=True)

    def get_panel(self, parent=None):
        panel = QDialog(parent)
        panel.setWindowTitle("网络诊断助手")
        panel.setMinimumSize(900, 640)
        root = QVBoxLayout(panel)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("网络诊断助手")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(title)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        summary_card = QGroupBox("网络评分")
        summary_layout = QVBoxLayout(summary_card)
        score_label = QLabel("评分：-")
        score_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        summary_label = QLabel("平均延迟：- | 可用性：-- | 抖动：-")
        suggest_label = QLabel("建议：-")
        summary_layout.addWidget(score_label)
        summary_layout.addWidget(summary_label)
        summary_layout.addWidget(suggest_label)
        overview_layout.addWidget(summary_card)

        action_row = QHBoxLayout()
        check_btn = QPushButton("一键检测")
        check_btn.setStyleSheet(
            "QPushButton { background: #1e7f1e; color: white; padding: 6px 14px; border-radius: 6px; }"
            "QPushButton:hover { background: #166116; }"
        )
        diag_btn = QPushButton("一键诊断")
        diag_btn.setStyleSheet(
            "QPushButton { background: #c06500; color: white; padding: 6px 14px; border-radius: 6px; }"
            "QPushButton:hover { background: #9b4f00; }"
        )
        action_row.addWidget(check_btn)
        action_row.addWidget(diag_btn)
        action_row.addStretch(1)
        overview_layout.addLayout(action_row)
        status_label = QLabel("状态：就绪")
        status_label.setStyleSheet("color: #444;")
        overview_layout.addWidget(status_label)
        tabs.addTab(overview_tab, "总览")

        site_tab = QWidget()
        site_layout = QVBoxLayout(site_tab)
        self._site_table = QTableWidget(0, 3)
        self._site_table.setHorizontalHeaderLabels(["网站", "延迟(ms)", "状态"])
        self._site_table.horizontalHeader().setStretchLastSection(True)
        self._site_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        site_layout.addWidget(self._site_table, 1)
        tabs.addTab(site_tab, "站点检测")

        diag_tab = QWidget()
        diag_layout = QVBoxLayout(diag_tab)
        diagnose_box = QPlainTextEdit()
        diagnose_box.setReadOnly(True)
        diag_layout.addWidget(diagnose_box, 1)
        tabs.addTab(diag_tab, "诊断")

        settings_tab = QWidget()
        settings_layout = QFormLayout(settings_tab)
        enabled_toggle = QCheckBox("启用自动检测")
        interval_spin = QSpinBox()
        interval_spin.setRange(5, 360)
        interval_spin.setSuffix(" 分钟")
        timeout_spin = QSpinBox()
        timeout_spin.setRange(1, 10)
        timeout_spin.setSuffix(" 秒")
        site_text = QPlainTextEdit()
        site_text.setPlaceholderText("每行一个站点，例如 https://www.github.com")
        save_btn = QPushButton("保存设置")
        reload_btn = QPushButton("重新加载")
        btn_row = QHBoxLayout()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(reload_btn)
        btn_row.addStretch(1)
        settings_layout.addRow(enabled_toggle)
        settings_layout.addRow("自动检测间隔", interval_spin)
        settings_layout.addRow("超时", timeout_spin)
        settings_layout.addRow("站点列表", site_text)
        settings_layout.addRow(QWidget(), btn_row)
        tabs.addTab(settings_tab, "设置")

        check_btn.clicked.connect(lambda: self._start_site_check(auto=False))
        diag_btn.clicked.connect(self._start_diagnostics)
        save_btn.clicked.connect(self._save_config_from_ui)
        reload_btn.clicked.connect(self._reload_from_file)

        self._panel = panel
        self._score_label = score_label
        self._summary_label = summary_label
        self._suggest_label = suggest_label
        self._status_label = status_label
        self._diagnose_box = diagnose_box
        self._enabled_toggle = enabled_toggle
        self._interval_spin = interval_spin
        self._timeout_spin = timeout_spin
        self._site_text = site_text

        self._apply_config_to_ui()
        self._update_overview(self.history.get("last_summary"))
        return panel

    def _load_config(self) -> dict:
        data = _read_json(self.config_path, {})
        config = DEFAULT_CONFIG.copy()
        if isinstance(data, dict):
            config.update(data)
        sites = []
        for item in config.get("site_list", []):
            url = _normalize_url(item)
            if url and url not in sites:
                sites.append(url)
        config["site_list"] = sites
        return config

    def _save_config(self) -> None:
        _write_json(self.config_path, self.config)

    def _load_history(self) -> dict:
        data = _read_json(self.history_path, {})
        if isinstance(data, dict):
            data.setdefault("site_checks", [])
            data.setdefault("last_summary", {})
            return data
        return {"site_checks": [], "last_summary": {}}

    def _save_history(self) -> None:
        _write_json(self.history_path, self.history)

    def _apply_config_to_ui(self) -> None:
        if not self._enabled_toggle:
            return
        self._enabled_toggle.setChecked(bool(self.config.get("enabled", True)))
        self._interval_spin.setValue(_safe_int(self.config.get("auto_check_interval_min"), 60))
        self._timeout_spin.setValue(_safe_int(self.config.get("timeout_sec"), 3))
        self._site_text.setPlainText("\n".join(self.config.get("site_list", [])))

    def _save_config_from_ui(self) -> None:
        if not self._enabled_toggle:
            return
        self.config["enabled"] = bool(self._enabled_toggle.isChecked())
        self.config["auto_check_interval_min"] = int(self._interval_spin.value())
        self.config["timeout_sec"] = int(self._timeout_spin.value())
        raw_sites = self._site_text.toPlainText().splitlines()
        sites = []
        for item in raw_sites:
            url = _normalize_url(item)
            if url and url not in sites:
                sites.append(url)
        self.config["site_list"] = sites
        self._save_config()

    def _reload_from_file(self) -> None:
        self.config = self._load_config()
        self._apply_config_to_ui()

    def _start_site_check(self, auto: bool) -> None:
        if self._checking:
            return
        self._checking = True
        self._set_status("检测中...")
        self._check_seq += 1
        seq = self._check_seq
        self._schedule_check_timeout(seq)

        def _worker() -> None:
            try:
                result = self._run_site_checks()
            except Exception as exc:
                result = {"error": str(exc)}
            self._run_in_ui(lambda: self._finish_site_check(result, seq))

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_site_check(self, result: dict, seq: int) -> None:
        if seq != self._check_seq:
            return
        self._checking = False
        error = result.get("error")
        if error:
            self._set_status(f"检测失败：{error}")
            if self.context:
                self.context.error(f"site check failed: {error}")
            return
        summary = result.get("summary", {})
        rows = result.get("rows", [])
        self.history["last_summary"] = summary
        self._append_history(rows)
        self._save_history()
        self._update_overview(summary)
        self._update_site_table(rows)
        self._set_status("检测完成")

    def _schedule_check_timeout(self, seq: int) -> None:
        sites = self.config.get("site_list", [])
        per_site = max(1, _safe_int(self.config.get("timeout_sec"), 3))
        max_seconds = max(5, (len(sites) or 1) * per_site + 5)
        QTimer.singleShot(max_seconds * 1000, lambda: self._on_check_timeout(seq))

    def _on_check_timeout(self, seq: int) -> None:
        if seq != self._check_seq or not self._checking:
            return
        self._checking = False
        self._set_status("检测超时")
        if self.context:
            self.context.warn("site check timeout")

    def _append_history(self, rows: list[dict]) -> None:
        items = self.history.get("site_checks", [])
        ts = int(time.time())
        for row in rows:
            items.append(
                {
                    "ts": ts,
                    "url": row.get("url"),
                    "latency_ms": row.get("latency_ms"),
                    "ok": bool(row.get("ok")),
                }
            )
        self.history["site_checks"] = items[-2000:]

    def _run_site_checks(self) -> dict:
        timeout = max(1, _safe_int(self.config.get("timeout_sec"), 3))
        rows = []
        latencies = []
        ok_count = 0
        for url in self.config.get("site_list", []):
            host, port = _split_host_port(url)
            ok, latency_ms = self._check_host(host, port, timeout)
            if ok and latency_ms is not None:
                latencies.append(latency_ms)
                ok_count += 1
            rows.append(
                {
                    "url": url,
                    "latency_ms": latency_ms,
                    "ok": ok,
                }
            )
        summary = self._build_summary(latencies, ok_count, len(rows))
        return {"summary": summary, "rows": rows}

    def _check_host(self, host: str, port: int, timeout: int) -> tuple[bool, float | None]:
        start = time.time()
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            latency = (time.time() - start) * 1000.0
            return True, round(latency, 2)
        except Exception:
            return False, None

    def _build_summary(self, latencies: list[float], ok_count: int, total: int) -> dict:
        avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        jitter = round(max(latencies) - min(latencies), 2) if len(latencies) > 1 else 0.0
        success_rate = ok_count / total if total else 0.0
        stability_score = max(0.0, 100.0 - avg_latency / 2.0) * 0.7 + max(0.0, 100.0 - jitter * 2.0) * 0.3
        availability_score = success_rate * 100.0
        final_score = max(0.0, min(100.0, stability_score * 0.5 + availability_score * 0.5))
        grade = self._score_grade(final_score)
        suggest = self._build_suggest(avg_latency, jitter, success_rate)
        return {
            "score": round(final_score, 1),
            "grade": grade,
            "avg_latency": avg_latency,
            "jitter": jitter,
            "success_rate": round(success_rate * 100.0, 1),
            "suggest": suggest,
        }

    def _score_grade(self, score: float) -> str:
        if score >= 90:
            return "A+"
        if score >= 80:
            return "A"
        if score >= 70:
            return "B"
        if score >= 60:
            return "C"
        return "D"

    def _build_suggest(self, avg_latency: float, jitter: float, success_rate: float) -> str:
        if success_rate < 0.7:
            return "可用性较差，建议检查路由器或联系运营商。"
        if avg_latency > 200:
            return "延迟偏高，建议更换 DNS 或切换网络。"
        if jitter > 30:
            return "波动较大，建议检查 WiFi 信号或使用有线网络。"
        return "网络状态良好，继续保持。"

    def _update_overview(self, summary: dict | None) -> None:
        if not self._score_label:
            return
        if not summary:
            self._score_label.setText("评分：-")
            self._summary_label.setText("平均延迟：- | 可用性：-- | 抖动：-")
            self._suggest_label.setText("建议：-")
            return
        self._score_label.setText(f"评分：{summary.get('grade')} ({summary.get('score')})")
        self._summary_label.setText(
            f"平均延迟：{summary.get('avg_latency')} ms | 可用性：{summary.get('success_rate')}% | 抖动：{summary.get('jitter')} ms"
        )
        self._suggest_label.setText(f"建议：{summary.get('suggest')}")

    def _update_site_table(self, rows: list[dict]) -> None:
        if not self._site_table:
            return
        self._site_table.setRowCount(len(rows))
        for row_idx, item in enumerate(rows):
            url = item.get("url", "")
            latency = item.get("latency_ms")
            ok = item.get("ok", False)
            self._site_table.setItem(row_idx, 0, QTableWidgetItem(url))
            self._site_table.setItem(row_idx, 1, QTableWidgetItem("-" if latency is None else str(latency)))
            self._site_table.setItem(row_idx, 2, QTableWidgetItem("正常" if ok else "失败"))

    def _start_diagnostics(self) -> None:
        if self._diagnosing:
            return
        self._diagnosing = True
        self._set_status("诊断中...")

        def _worker() -> None:
            try:
                result = self._run_diagnostics()
                error = None
            except Exception as exc:
                result = ""
                error = str(exc)
            self._run_in_ui(lambda: self._finish_diagnostics(result, error))

        threading.Thread(target=_worker, daemon=True).start()

    def _finish_diagnostics(self, result: str, error: str | None = None) -> None:
        self._diagnosing = False
        if error:
            message = f"诊断失败：{error}"
            if self._diagnose_box:
                self._diagnose_box.setPlainText(message)
            self._set_status(message)
            if self.context:
                self.context.error(f"diagnostics failed: {error}")
            return
        if self._diagnose_box:
            self._diagnose_box.setPlainText(result)
        self._set_status("诊断完成")

    def _run_diagnostics(self) -> str:
        sites = self.config.get("site_list", [])
        target = sites[0] if sites else "https://www.baidu.com"
        host, _ = _split_host_port(target)
        sections = []
        sections.append(self._run_command(["nslookup", host], "DNS 解析"))
        sections.append(self._run_command(["ping", "-n", "4", host], "Ping 检测"))
        sections.append(self._run_command(["tracert", "-d", host], "路由追踪"))
        sections.append(self._proxy_info())
        return "\n\n".join(sections)

    def _run_command(self, command: list[str], title: str) -> str:
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="ignore",
            )
            output = proc.stdout.strip() or proc.stderr.strip() or "无输出"
            return f"【{title}】\n{output}"
        except Exception as exc:
            return f"【{title}】\n执行失败: {exc}"

    def _proxy_info(self) -> str:
        env_http = os.getenv("HTTP_PROXY", "") or os.getenv("http_proxy", "")
        env_https = os.getenv("HTTPS_PROXY", "") or os.getenv("https_proxy", "")
        win_proxy = self._run_command(["netsh", "winhttp", "show", "proxy"], "系统代理")
        env_text = f"HTTP_PROXY={env_http or '未设置'}\nHTTPS_PROXY={env_https or '未设置'}"
        return f"【代理检测】\n{env_text}\n\n{win_proxy}"

    def _set_status(self, text: str) -> None:
        if self._status_label:
            self._status_label.setText(f"状态：{text}")

    def _run_in_ui(self, func) -> None:
        if self._panel:
            QTimer.singleShot(0, self._panel, func)
        else:
            QTimer.singleShot(0, func)


def create_plugin(context):
    return Plugin(context)
