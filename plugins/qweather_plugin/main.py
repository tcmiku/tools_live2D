from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


CITY_ID_LIST_URL = "https://note.youdao.com/s/WSokZBTP"
API_URL = "https://aider.meizu.com/app/weather/listWeather"
CITY_ID_PRESETS = [
    ("北京", "101010100"),
    ("上海", "101020100"),
    ("广州", "101280101"),
    ("深圳", "101280601"),
    ("杭州", "101210101"),
    ("武汉", "101200101"),
    ("成都", "101270101"),
    ("重庆", "101040100"),
    ("西安", "101110101"),
    ("南京", "101190101"),
]


@dataclass
class WeatherConfig:
    city_id: str = ""
    city_name: str = ""
    unit: str = "c"
    auto_report: bool = True


class ControlPanel(QDialog):
    def __init__(self, config: WeatherConfig, ai_city: str, readme_handler, parent=None) -> None:
        super().__init__(parent)
        self._readme_handler = readme_handler
        self.setWindowTitle("天气插件控制面板")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.city_id_combo = QComboBox()
        self.city_id_combo.setEditable(True)
        for name, city_id in CITY_ID_PRESETS:
            self.city_id_combo.addItem(f"{name} {city_id}", city_id)
        self._set_city_id(config.city_id)
        self.city_name_edit = QLineEdit(config.city_name)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["c", "f"])
        self.unit_combo.setCurrentText(config.unit or "c")
        self.auto_report_toggle = QCheckBox("启动自动播报")
        self.auto_report_toggle.setChecked(bool(config.auto_report))

        ai_city_label = QLabel(ai_city or "未设置")
        ai_city_label.setStyleSheet("color: #555;")

        use_ai_btn = QPushButton("使用 AI 城市")
        use_ai_btn.setFixedWidth(110)
        use_ai_btn.clicked.connect(lambda: self._apply_ai_city(ai_city))

        city_name_row = QHBoxLayout()
        city_name_row.addWidget(self.city_name_edit, 1)
        city_name_row.addWidget(use_ai_btn)

        city_list_btn = QPushButton("城市ID列表")
        city_list_btn.setFixedWidth(110)
        city_list_btn.clicked.connect(self._open_city_id_list)

        city_id_row = QHBoxLayout()
        city_id_row.addWidget(self.city_id_combo, 1)
        city_id_row.addWidget(city_list_btn)

        form.addRow("城市ID(必填)", city_id_row)
        form.addRow("城市名称(可选)", city_name_row)
        form.addRow("AI 配置城市", ai_city_label)
        form.addRow("单位(c/f)", self.unit_combo)
        form.addRow(self.auto_report_toggle)
        layout.addLayout(form)

        action_row = QHBoxLayout()
        self.tutorial_btn = QPushButton("教程")
        self.tutorial_btn.setFixedWidth(80)
        self.tutorial_btn.clicked.connect(self._open_readme)
        action_row.addWidget(self.tutorial_btn)
        self.test_btn = QPushButton("测试查询")
        action_row.addWidget(self.test_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_ai_city(self, ai_city: str) -> None:
        if ai_city:
            self.city_name_edit.setText(ai_city)

    def _open_city_id_list(self) -> None:
        QDesktopServices.openUrl(QUrl(CITY_ID_LIST_URL))

    def _open_readme(self) -> None:
        if self._readme_handler:
            self._readme_handler()

    def get_values(self) -> WeatherConfig:
        return WeatherConfig(
            city_id=self._get_city_id_value(),
            city_name=self.city_name_edit.text().strip(),
            unit=self.unit_combo.currentText().strip() or "c",
            auto_report=bool(self.auto_report_toggle.isChecked()),
        )

    def _get_city_id_value(self) -> str:
        data = self.city_id_combo.currentData()
        if isinstance(data, str) and data.strip():
            return data.strip()
        text = self.city_id_combo.currentText().strip()
        match = re.search(r"\d{6,}", text)
        return match.group(0) if match else text

    def _set_city_id(self, city_id: str) -> None:
        if not city_id:
            return
        index = self.city_id_combo.findData(city_id)
        if index >= 0:
            self.city_id_combo.setCurrentIndex(index)
        else:
            self.city_id_combo.setCurrentText(city_id)


class WeatherPlugin:
    def __init__(self, context) -> None:
        self.context = context
        self._config = self._load_config()
        self._settings_dialog = None

    def on_app_ready(self) -> None:
        if not self._config.auto_report:
            return
        self._run_async(self._report_today_startup)

    def get_ai_context(self, text: str) -> str:
        if not text:
            return ""
        lowered = text.strip().lower()
        if not any(word in lowered for word in ["天气", "气温", "下雨", "雨伞", "温度", "weather"]):
            return ""
        message = self._build_weather_message()
        if not message:
            return ""
        return f"当前天气信息：{message}"

    def get_panel(self, parent=None):
        ai_city = self._get_ai_city()
        if self._settings_dialog is None or self._settings_dialog.parent() != parent:
            self._settings_dialog = ControlPanel(
                self._config,
                ai_city,
                readme_handler=self._open_readme,
                parent=parent,
            )
            self._settings_dialog.accepted.connect(self._apply_settings_from_dialog)
            self._settings_dialog.test_btn.clicked.connect(self._test_weather)
        return self._settings_dialog

    def _apply_settings_from_dialog(self, dialog=None) -> None:
        target = dialog if dialog is not None else self._settings_dialog
        if not target:
            return
        self._config = target.get_values()
        self._save_config()
        self.context.info("weather settings saved")

    def _test_weather(self) -> None:
        def _worker():
            temp_config = self._config
            if self._settings_dialog:
                temp_config = self._settings_dialog.get_values()
            message = self._build_weather_message(config=temp_config)
            if not message:
                message = "天气插件未配置，请先填写城市ID。"
            self._show_info(message)

        self._run_async(_worker)

    def _show_info(self, message: str) -> None:
        def _show():
            if self._settings_dialog:
                QMessageBox.information(self._settings_dialog, "天气插件", message)

        QTimer.singleShot(0, _show)

    def _run_async(self, func) -> None:
        thread = threading.Thread(target=func, daemon=True)
        thread.start()

    def _config_path(self) -> str:
        return self.context.get_data_path("config.json")

    def _load_config(self) -> WeatherConfig:
        path = self._config_path()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return WeatherConfig(
                city_id=str(data.get("city_id", "")),
                city_name=str(data.get("city_name", "")),
                unit=str(data.get("unit", "c")) or "c",
                auto_report=bool(data.get("auto_report", True)),
            )
        except Exception:
            return WeatherConfig()

    def _save_config(self) -> None:
        path = self._config_path()
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "city_id": self._config.city_id,
                    "city_name": self._config.city_name,
                    "unit": self._config.unit,
                    "auto_report": self._config.auto_report,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )

    def _report_today_startup(self) -> None:
        message = self._build_weather_message()
        if message:
            self.context.bridge.push_passive_message(message)

    def _build_weather_message(self, config: WeatherConfig | None = None) -> str:
        config = config or self._config
        city_id = config.city_id.strip()
        if not city_id:
            self.context.warn("weather city id missing")
            return ""
        payload = self._fetch_json({"cityIds": city_id})
        if not payload:
            return "获取天气失败，请稍后再试。"
        if str(payload.get("code")) != "200":
            return f"天气接口返回异常：{payload.get('message') or payload.get('code')}"
        values = payload.get("value") or []
        if not values:
            return "天气接口返回空数据，请检查城市ID是否正确。"
        data = values[0]
        city = str(data.get("city") or config.city_name or "")

        realtime = data.get("realtime") or {}
        weather_now = str(realtime.get("weather") or "")
        temp_now = realtime.get("temp")
        humidity = realtime.get("sD")
        wind_dir = realtime.get("wD") or ""
        wind_scale = realtime.get("wS") or ""

        weathers = data.get("weathers") or []
        today = weathers[0] if weathers else {}
        temp_day = today.get("temp_day_c")
        temp_night = today.get("temp_night_c")
        if config.unit == "f":
            temp_now = self._to_f(temp_now)
            temp_day = self._to_f(temp_day)
            temp_night = self._to_f(temp_night)
        unit_label = "°F" if config.unit == "f" else "°C"

        indices = data.get("indexes") or []
        dress = self._pick_index(indices, "穿衣指数")
        uv = self._pick_index(indices, "紫外线强度指数")

        umbrella_tip = self._umbrella_tip(weather_now, today.get("weather", ""))
        lines = [
            f"今日{city}天气：{weather_now}，当前{temp_now}{unit_label}。",
            f"最高{temp_day}{unit_label} / 最低{temp_night}{unit_label}，湿度{humidity}。",
            f"风向{wind_dir} 风力{wind_scale}。",
            umbrella_tip,
        ]
        if dress:
            lines.append(f"{dress.get('name')}: {dress.get('level')} {dress.get('content')}")
        if uv:
            lines.append(f"{uv.get('name')}: {uv.get('level')} {uv.get('content')}")
        return " ".join([part for part in lines if part])

    def _umbrella_tip(self, now_text: str, day_text: str) -> str:
        keywords = ["雨", "雪", "雹", "雷"]
        text = f"{now_text}{day_text}"
        if any(word in text for word in keywords):
            return "提示：可能有降水，记得带伞。"
        return "提示：降水概率低，可不带伞。"

    def _pick_index(self, indexes: list, name: str) -> dict:
        for item in indexes:
            if str(item.get("name", "")) == name:
                return item
        return {}

    def _to_f(self, value) -> str:
        try:
            c = float(value)
        except (TypeError, ValueError):
            return str(value or "")
        f = c * 9 / 5 + 32
        return f"{f:.1f}"

    def _get_ai_city(self) -> str:
        try:
            settings = self.context.settings.get_settings()
        except Exception:
            return ""
        return str(settings.get("local_city", "")).strip()

    def _fetch_json(self, params: dict) -> dict | None:
        query = urllib.parse.urlencode(params)
        url = f"{API_URL}?{query}"
        self.context.info(f"request: {url}")
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            self.context.error(f"request failed: HTTP {exc.code}")
            return None
        except Exception as exc:
            self.context.error(f"request failed: {exc}")
            return None

    def _open_readme(self) -> None:
        readme_path = os.path.join(self.context.plugin_dir, "README.md")
        if not os.path.exists(readme_path):
            self._show_info("未找到 README 文档。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(readme_path))


def create_plugin(context):
    return WeatherPlugin(context)
