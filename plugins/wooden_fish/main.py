from __future__ import annotations

import json
import os
import random
from typing import Any

from PySide6.QtCore import (
    QTimer,
    Qt,
    QSize,
    QPoint,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QEasingCurve,
    QAbstractAnimation,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QCheckBox,
)


class Plugin:
    def __init__(self, context) -> None:
        self.context = context
        self.panel: QWidget | None = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._auto_tick)
        self.count = 0
        self.auto_enabled = False
        self.auto_interval_ms = 1000
        self._hit_restore_timer = QTimer()
        self._hit_restore_timer.setSingleShot(True)
        self._hit_restore_timer.timeout.connect(self._restore_hit_icon)
        self._float_timer = QTimer()
        self._float_timer.setSingleShot(True)
        self._float_timer.timeout.connect(self._hide_float_text)
        self._float_label: QLabel | None = None
        self._float_anim: QParallelAnimationGroup | None = None
        self._load_config()

    def on_unload(self) -> None:
        self.timer.stop()

    def get_panel(self, parent=None):
        if self.panel is not None:
            return self.panel

        root = QWidget(parent)
        root.setStyleSheet(
            "QWidget { background: #0b0d12; color: #eef2ff; }"
            "QLabel { color: #eef2ff; }"
            "QPushButton { color: #eef2ff; background: #1f2937; border: 1px solid #334155; border-radius: 6px; padding: 4px 10px; }"
            "QPushButton:hover { background: #263445; }"
            "QSpinBox { color: #eef2ff; background: #111827; border: 1px solid #334155; border-radius: 6px; padding: 2px 6px; }"
            "QCheckBox { color: #eef2ff; }"
        )
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("电子木鱼")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)

        self.count_label = QLabel()
        self.count_label.setAlignment(Qt.AlignCenter)
        self.count_label.setStyleSheet("font-size: 20px; color: #f8fafc;")
        layout.addWidget(self.count_label)

        self.hit_btn = QPushButton()
        fish_pixmap = self._wooden_fish_pixmap()
        self._default_icon_size = fish_pixmap.size()
        self.hit_btn.setIcon(QIcon(fish_pixmap))
        self.hit_btn.setIconSize(self._default_icon_size)
        self.hit_btn.setFixedSize(180, 180)
        self.hit_btn.setFlat(True)
        self.hit_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            "QPushButton:pressed { background: transparent; border: none; }"
            "QPushButton:focus { outline: none; border: none; }"
        )
        self.hit_btn.setToolTip("点击木鱼 +1 功德")
        layout.addWidget(self.hit_btn, alignment=Qt.AlignCenter)

        btn_row = QHBoxLayout()
        self.reset_btn = QPushButton("清零")
        btn_row.addStretch(1)
        btn_row.addWidget(self.reset_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        auto_row = QHBoxLayout()
        self.auto_check = QCheckBox("自动敲击")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(200, 5000)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.setSuffix(" ms")
        auto_row.addWidget(self.auto_check)
        auto_row.addWidget(QLabel("间隔"))
        auto_row.addWidget(self.interval_spin)
        layout.addLayout(auto_row)

        self.hit_btn.clicked.connect(self._hit)
        self.reset_btn.clicked.connect(self._reset)
        self.auto_check.toggled.connect(self._toggle_auto)
        self.interval_spin.valueChanged.connect(self._change_interval)

        self._sync_ui()
        self.panel = root
        return root

    def _hit(self) -> None:
        self.count += 1
        self._save_config()
        self._sync_ui()
        self._play_hit_animation()
        self._show_hit_floating()
        self._beep()

    def _reset(self) -> None:
        self.count = 0
        self._save_config()
        self._sync_ui()

    def _toggle_auto(self, checked: bool) -> None:
        self.auto_enabled = bool(checked)
        if self.auto_enabled:
            self.timer.start(self.auto_interval_ms)
        else:
            self.timer.stop()
        self._save_config()

    def _change_interval(self, value: int) -> None:
        self.auto_interval_ms = int(value)
        if self.auto_enabled:
            self.timer.start(self.auto_interval_ms)
        self._save_config()

    def _auto_tick(self) -> None:
        self._hit()

    def _sync_ui(self) -> None:
        if hasattr(self, "count_label"):
            self.count_label.setText(f"功德 +{self.count}")
        if hasattr(self, "auto_check"):
            self.auto_check.setChecked(self.auto_enabled)
        if hasattr(self, "interval_spin"):
            self.interval_spin.setValue(self.auto_interval_ms)

    def _config_path(self) -> str:
        return self.context.get_data_path("config.json")

    def _load_config(self) -> None:
        path = self._config_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
            self.count = int(data.get("count", 0))
            self.auto_enabled = bool(data.get("auto_enabled", False))
            self.auto_interval_ms = int(data.get("auto_interval_ms", 1000))
            if self.auto_enabled:
                self.timer.start(self.auto_interval_ms)
        except Exception as exc:
            self.context.warn(f"config load failed: {exc}")

    def _save_config(self) -> None:
        path = self._config_path()
        data = {
            "count": self.count,
            "auto_enabled": self.auto_enabled,
            "auto_interval_ms": self.auto_interval_ms,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.context.warn(f"config save failed: {exc}")

    def _beep(self) -> None:
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_OK)
        except Exception:
            try:
                from PySide6.QtWidgets import QApplication

                QApplication.beep()
            except Exception:
                pass

    def _wooden_fish_pixmap(self) -> QPixmap:
        image_path = os.path.join(self.context.plugin_dir, "png", "unnamed.webp")
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            return pixmap.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.context.warn(f"wooden fish image not found: {image_path}")
        return self._svg_pixmap()

    def _play_hit_animation(self) -> None:
        if not hasattr(self, "hit_btn"):
            return
        start_size = getattr(self, "_default_icon_size", self.hit_btn.iconSize())
        down_size = QSize(max(80, int(start_size.width() * 0.88)), max(80, int(start_size.height() * 0.88)))
        self._hit_restore_timer.stop()
        self.hit_btn.setIconSize(down_size)
        self._hit_restore_timer.start(120)

    def _restore_hit_icon(self) -> None:
        if not hasattr(self, "hit_btn"):
            return
        start_size = getattr(self, "_default_icon_size", self.hit_btn.iconSize())
        self.hit_btn.setIconSize(start_size)

    def _show_hit_floating(self) -> None:
        if self.panel is None or not hasattr(self, "hit_btn"):
            return
        if self._float_label is None:
            label = QLabel(self.panel)
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            label.setStyleSheet(
                "QLabel { color: #ffffff; font-size: 18px; font-weight: 800; "
                "text-shadow: 0 1px 2px rgba(0,0,0,0.5); }"
            )
            label.hide()
            self._float_label = label
        text = random.choice(["+1", "+1", "+1"])
        self._float_label.setText(text)
        self._float_label.adjustSize()
        btn_rect = self.hit_btn.geometry()
        max_x = max(btn_rect.x(), btn_rect.x() + btn_rect.width() - self._float_label.width())
        min_x = btn_rect.x()
        max_y = max(0, btn_rect.y() + btn_rect.height() // 2)
        min_y = max(0, btn_rect.y() - self._float_label.height())
        x = random.randint(min_x, max_x) if max_x >= min_x else btn_rect.x()
        y = random.randint(min_y, max_y) if max_y >= min_y else btn_rect.y()
        self._float_label.move(x, y)
        if self._float_label.graphicsEffect() is None:
            self._float_label.setGraphicsEffect(QGraphicsOpacityEffect(self._float_label))
        effect = self._float_label.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(1.0)
        self._float_label.raise_()
        self._float_label.show()
        self._play_float_animation(QPoint(x, y))

    def _hide_float_text(self) -> None:
        if self._float_label is not None:
            self._float_label.hide()

    def _play_float_animation(self, start_pos: QPoint) -> None:
        if self._float_label is None:
            return
        if self._float_anim is not None and self._float_anim.state() == QAbstractAnimation.Running:
            self._float_anim.stop()
        end_pos = QPoint(start_pos.x(), max(0, start_pos.y() - 24))
        move_anim = QPropertyAnimation(self._float_label, b"pos")
        move_anim.setDuration(800)
        move_anim.setStartValue(start_pos)
        move_anim.setEndValue(end_pos)
        move_anim.setEasingCurve(QEasingCurve.OutQuad)
        fade_anim = QPropertyAnimation(self._float_label.graphicsEffect(), b"opacity")
        fade_anim.setDuration(800)
        fade_anim.setStartValue(1.0)
        fade_anim.setEndValue(0.0)
        group = QParallelAnimationGroup(self._float_label)
        group.addAnimation(move_anim)
        group.addAnimation(fade_anim)
        group.finished.connect(self._hide_float_text)
        self._float_anim = group
        group.start()

    def _svg_pixmap(self) -> QPixmap:
        svg = """
        <svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" viewBox="0 0 240 240">
          <defs>
            <radialGradient id="body" cx="0.35" cy="0.35" r="0.75">
              <stop offset="0" stop-color="#f8dfb6"/>
              <stop offset="0.6" stop-color="#d8a868"/>
              <stop offset="1" stop-color="#b07a3c"/>
            </radialGradient>
            <linearGradient id="rim" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="#8a5b28"/>
              <stop offset="1" stop-color="#6a3f1a"/>
            </linearGradient>
            <linearGradient id="slit" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stop-color="#2b1b0f"/>
              <stop offset="1" stop-color="#1a100a"/>
            </linearGradient>
          </defs>

          <!-- body -->
          <ellipse cx="132" cy="132" rx="92" ry="64" fill="url(#body)" stroke="url(#rim)" stroke-width="6"/>
          <!-- tail -->
          <path d="M52 140 L28 132 L52 124 Q46 132 52 140" fill="url(#body)" stroke="url(#rim)" stroke-width="4" stroke-linejoin="round"/>
          <!-- top ridge -->
          <path d="M70 110 Q130 68 196 112" fill="none" stroke="#6f4a25" stroke-width="10" stroke-linecap="round" opacity="0.8"/>
          <path d="M78 116 Q132 80 188 118" fill="none" stroke="#e6c08a" stroke-width="6" stroke-linecap="round" opacity="0.6"/>
          <!-- slit -->
          <path d="M96 120 Q142 106 184 128" fill="none" stroke="url(#slit)" stroke-width="18" stroke-linecap="round"/>
          <path d="M96 120 Q142 106 184 128" fill="none" stroke="#0f0a06" stroke-width="6" stroke-linecap="round" opacity="0.7"/>
          <!-- highlight -->
          <ellipse cx="112" cy="118" rx="28" ry="16" fill="#fff5e1" opacity="0.35"/>
        </svg>
        """.strip()
        renderer = QSvgRenderer(bytearray(svg, "utf-8"))
        pixmap = QPixmap(180, 180)
        pixmap.fill(Qt.transparent)
        painter = None
        try:
            from PySide6.QtGui import QPainter

            painter = QPainter(pixmap)
            renderer.render(painter)
        finally:
            if painter is not None:
                painter.end()
        return pixmap
