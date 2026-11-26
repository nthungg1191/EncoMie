"""Reusable PyQt6 colour picker popup, swatch button, hue wheel, and SV canvas."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.theme import (
    C_ACCENT,
    C_ACCENT_DIM,
    C_BG,
    C_BORDER,
    C_ELEVATED_BG,
    C_HOVER,
    C_SECTION_BG,
    C_TEXT,
    C_TEXT_MUTED,
    spinbox_arrows_qss,
)


class ColorPickerPopup(QDialog):
    """
    Professional-grade color picker popup — Photoshop/Premiere/DaVinci Resolve style.
    Features: hue wheel, SV area, live preview, HEX/RGB/alpha inputs,
    preset swatches, recent colors, real-time subtitle preview feedback.
    """

    # Singleton recent-colors store (shared across all picker instances)
    _recent: list[str] = []
    _MAX_RECENT = 10

    # Preset swatches
    _PRESETS = [
        "#FFFFFF", "#000000", "#FFFF00", "#FF0000",
        "#0000FF", "#00FF00", "#FF8800",
    ]

    def __init__(self, initial_hex: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Color Picker")
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)
        self.setMinimumWidth(460)
        self._setup_style()

        self._prev_hex = initial_hex
        self._current_hex = initial_hex.upper()

        # HSV state (0-360 hue, 0-100 sat, 0-100 val)
        qc = QColor(initial_hex)
        self._h = qc.hsvHue() if qc.hsvHue() >= 0 else 0
        self._s = qc.hsvSaturation()
        self._v = qc.value()
        self._parent_button = None  # assigned in show_at() before first use

        self._build_ui()
        self._apply_initial_color()

    # ---- Public API ----

    def selected_color(self) -> str:
        return self._current_hex

    # ---- UI construction ----

    def _setup_style(self):
        self.setMinimumWidth(460)
        self._pad = 14
        self._corner = 8
        self.setStyleSheet(f"""
            QDialog {{ background: transparent; }}
            * {{ color: {C_TEXT}; font-size: 12px;
                font-family: "Segoe UI", sans-serif; }}
            QWidget {{ background: transparent; }}
        """)

    def _outer_frame(self) -> QFrame:
        """Dark card shell that gives the WA_TranslucentBackground appearance."""
        f = QFrame(self)
        f.setObjectName("card")
        f.setStyleSheet(f"""
            QFrame#card {{
                background: {C_BG};
                border: 1px solid {C_BORDER};
                border-radius: {self._corner}px;
            }}
            QLabel {{ color: {C_TEXT}; background: transparent;
                      font-size: 11px; qproperty-alignment:
                      AlignCenter; }}
            QLineEdit {{
                background: {C_ELEVATED_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                color: {C_TEXT};
                font-family: monospace;
                font-size: 12px;
                padding: 3px 6px;
            }}
            QLineEdit:focus {{ border-color: {C_ACCENT}; }}
            QSpinBox {{
                background: {C_ELEVATED_BG};
                border: 1px solid {C_BORDER};
                border-radius: 4px;
                color: {C_TEXT};
                font-size: 12px;
                padding: 2px 4px 2px 6px;
            }}
            QSpinBox:focus {{ border-color: {C_ACCENT}; }}
            {spinbox_arrows_qss(
                button_width=15,
                button_height=11,
                button_bg=C_ELEVATED_BG,
                border_color=C_BORDER,
                divider_color=C_BORDER,
                hover_bg=None,
                radius=4,
                include_double=False,
            )}
            QSlider::groove:horizontal {{
                border-radius: 3px; height: 6px;
                background: {C_SECTION_BG};
            }}
            QSlider::handle:horizontal {{
                background: {C_ACCENT};
                width: 14px; height: 14px;
                border-radius: 7px; margin: -4px 0;
            }}
            QSlider::sub-page:horizontal {{
                background: {C_ACCENT}; border-radius: 3px;
            }}
        """)
        return f

    def _build_ui(self):
        outer = self._outer_frame()
        root = QVBoxLayout(outer)
        root.setContentsMargins(self._pad, self._pad, self._pad, self._pad)
        root.setSpacing(10)

        # ── Top row: SV canvas + Hue wheel ──────────────────────────────
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        # Saturation/Value canvas
        self._sv_canvas = SVCanvas(self)
        self._sv_canvas.setFixedSize(200, 170)
        self._sv_canvas.hsv_changed.connect(self._on_sv_changed)
        top_row.addWidget(self._sv_canvas, alignment=Qt.AlignmentFlag.AlignTop)

        # Hue wheel + current/prev previews stacked
        right_col = QVBoxLayout()
        right_col.setSpacing(6)

        self._hue_wheel = HueWheel(self)
        self._hue_wheel.setFixedSize(72, 72)
        self._hue_wheel.hue_changed.connect(self._on_hue_changed)
        right_col.addWidget(self._hue_wheel)

        for label_text, is_current in (("Hiện tại", True), ("Trước đó", False)):
            preview_frame = self._make_preview(label_text, is_current)
            right_col.addWidget(preview_frame)

        right_col.addStretch()
        top_row.addLayout(right_col)
        root.addLayout(top_row)

        # ── Hex + RGB row ─────────────────────────────────────────────────
        hex_rgb = QGridLayout()
        hex_rgb.setHorizontalSpacing(8)
        hex_rgb.setVerticalSpacing(6)

        lbl_hex = QLabel("HEX")
        lbl_hex.setMinimumWidth(40)
        lbl_hex.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        hex_rgb.addWidget(lbl_hex, 0, 0)

        self._le_hex = QLineEdit()
        self._le_hex.setFixedHeight(26)
        self._le_hex.setMaxLength(7)
        self._le_hex.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._le_hex.textEdited.connect(self._on_hex_edited)
        hex_rgb.addWidget(self._le_hex, 0, 1, 1, 5)

        lbl_r, lbl_g, lbl_b = QLabel("R"), QLabel("G"), QLabel("B")
        for column, lbl in enumerate((lbl_r, lbl_g, lbl_b)):
            lbl.setMinimumWidth(18)
            lbl.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
            hex_rgb.addWidget(lbl, 1, column * 2)

        for column, (channel, attr) in enumerate([("r", "_spn_r"), ("g", "_spn_g"), ("b", "_spn_b")]):
            spn = QSpinBox()
            spn.setRange(0, 255)
            spn.setMinimumWidth(84)
            spn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            spn.setAlignment(Qt.AlignmentFlag.AlignRight)
            spn.setFixedHeight(26)
            spn.valueChanged.connect(self._on_rgb_changed)
            setattr(self, attr, spn)
            hex_rgb.addWidget(spn, 1, column * 2 + 1)

        root.addLayout(hex_rgb)

        # ── Opacity / Alpha slider ────────────────────────────────────────
        alpha_row = QHBoxLayout()
        alpha_row.setSpacing(6)

        lbl_a = QLabel("Độ mờ")
        lbl_a.setFixedWidth(64)
        lbl_a.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        alpha_row.addWidget(lbl_a)

        self._alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self._alpha_slider.setRange(0, 100)
        self._alpha_slider.setValue(100)
        self._alpha_slider.setFixedHeight(20)
        self._alpha_slider.valueChanged.connect(self._on_alpha_changed)
        alpha_row.addWidget(self._alpha_slider, 1)

        self._alpha_val = QLabel("100%")
        self._alpha_val.setFixedWidth(48)
        self._alpha_val.setStyleSheet(f"color: {C_TEXT}; font-size: 11px;")
        alpha_row.addWidget(self._alpha_val)

        root.addLayout(alpha_row)

        # ── Preset swatches ──────────────────────────────────────────────
        swatch_lbl = QLabel("Màu mẫu")
        swatch_lbl.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 10px; font-weight: 600;")
        swatch_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        root.addWidget(swatch_lbl)

        presets_grid = QGridLayout()
        presets_grid.setHorizontalSpacing(6)
        presets_grid.setVerticalSpacing(6)
        for i, hex_c in enumerate(self._PRESETS):
            btn = SwatchButton(hex_c, self)
            btn.clicked.connect(lambda _, h=hex_c: self._apply_hex(h))
            presets_grid.addWidget(btn, 0, i)
        self._recent_btns: list[SwatchButton] = []
        if self._recent:
            for i, hex_c in enumerate(self._recent):
                btn = SwatchButton(hex_c, self)
                btn.clicked.connect(lambda _, h=hex_c: self._apply_hex(h))
                presets_grid.addWidget(btn, 1, i)
                self._recent_btns.append(btn)
        root.addLayout(presets_grid)

        # ── Action buttons ───────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel = QPushButton("Hủy")
        cancel.setMinimumSize(84, 28)
        cancel.setStyleSheet(self._btn_dark())
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        ok = QPushButton("OK")
        ok.setMinimumSize(84, 28)
        ok.setStyleSheet(self._btn_accent())
        ok.clicked.connect(self._on_ok)
        btn_row.addWidget(ok)

        root.addLayout(btn_row)

        # Wrap in translucent container
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.addWidget(outer)

    def _make_preview(self, label: str, is_current: bool) -> QFrame:
        f = QFrame()
        f.setFixedHeight(30)
        f.setMinimumWidth(130)
        f.setStyleSheet(f"""
            QFrame {{ background: {C_SECTION_BG};
                      border: 1px solid {C_BORDER};
                      border-radius: 4px; }}
        """)
        lay = QHBoxLayout(f)
        lay.setContentsMargins(6, 2, 6, 2)
        lbl = QLabel(label)
        lbl.setMinimumWidth(lbl.sizeHint().width() + 4)
        lbl.setStyleSheet(f"color: {C_TEXT_MUTED}; font-size: 10px;")
        lay.addWidget(lbl)
        color_sw = QLabel()
        color_sw.setFixedSize(50, 18)
        color_sw.setStyleSheet(f"""
            background: {self._current_hex if is_current else self._prev_hex};
            border-radius: 3px;
            border: 1px solid {C_BORDER};
        """)
        lay.addWidget(color_sw)
        if is_current:
            self._preview_cur = color_sw
        else:
            self._preview_prv = color_sw
        return f

    def _btn_dark(self) -> str:
        return (
            f"QPushButton {{ background: {C_SECTION_BG}; color: {C_TEXT}; "
            f"border: 1px solid {C_BORDER}; border-radius: 5px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {C_HOVER}; }}"
        )

    def _btn_accent(self) -> str:
        return (
            f"QPushButton {{ background: {C_ACCENT}; color: #fff; "
            f"border: none; border-radius: 5px; font-size: 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {C_ACCENT_DIM}; }}"
        )

    # ---- Color sync helpers ----

    def _qc(self) -> QColor:
        return QColor.fromHsv(self._h, self._s, self._v)

    def _apply_initial_color(self):
        self._le_hex.setText(self._current_hex)
        r, g, b = self._qc().red(), self._qc().green(), self._qc().blue()
        self._spn_r.setValue(r)
        self._spn_g.setValue(g)
        self._spn_b.setValue(b)
        self._hue_wheel.set_hue(self._h)
        self._sv_canvas.set_hsv(self._h, self._s, self._v)
        self._update_previews()

    def _refresh_all(self):
        qc = self._qc()
        hex_s = qc.name(QColor.NameFormat.HexRgb).upper()
        r, g, b = qc.red(), qc.green(), qc.blue()
        self._current_hex = hex_s
        self._le_hex.blockSignals(True)
        self._le_hex.setText(hex_s)
        self._le_hex.blockSignals(False)
        self._spn_r.blockSignals(True); self._spn_r.setValue(r); self._spn_r.blockSignals(False)
        self._spn_g.blockSignals(True); self._spn_g.setValue(g); self._spn_g.blockSignals(False)
        self._spn_b.blockSignals(True); self._spn_b.setValue(b); self._spn_b.blockSignals(False)
        self._sv_canvas.set_hsv(self._h, self._s, self._v)
        self._update_previews()

    def _update_previews(self):
        qc = self._qc()
        hex_s = qc.name(QColor.NameFormat.HexRgb).upper()
        if hasattr(self, "_preview_cur"):
            self._preview_cur.setStyleSheet(
                f"background: {hex_s}; border-radius: 3px; border: 1px solid {C_BORDER};"
            )
        # Live update parent button swatch
        if self._parent_button:
            self._parent_button._hex = hex_s
            self._parent_button.update()

    def _apply_hex(self, hex_s: str):
        hex_s = hex_s.strip().upper()
        if not hex_s.startswith("#"):
            hex_s = "#" + hex_s
        qc = QColor(hex_s)
        if qc.isValid():
            self._h = qc.hsvHue() if qc.hsvHue() >= 0 else 0
            self._s = qc.hsvSaturation()
            self._v = qc.value()
            self._refresh_all()

    # ---- Signal handlers ----

    def _on_sv_changed(self, h: int, s: int, v: int):
        self._h, self._s, self._v = h, s, v
        self._hue_wheel.set_hue(h)
        self._refresh_all()

    def _on_hue_changed(self, hue: int):
        self._h = hue
        self._sv_canvas.set_hsv(hue, self._s, self._v)
        self._refresh_all()

    def _on_hex_edited(self, text: str):
        raw = text.strip()
        if raw.startswith("#"):
            raw = raw[1:]
        if len(raw) == 6:
            try:
                int(raw, 16)
                qc = QColor(f"#{raw.upper()}")
                if qc.isValid():
                    self._h = qc.hsvHue() if qc.hsvHue() >= 0 else 0
                    self._s = qc.hsvSaturation()
                    self._v = qc.value()
                    self._spn_r.setValue(qc.red())
                    self._spn_g.setValue(qc.green())
                    self._spn_b.setValue(qc.blue())
                    self._hue_wheel.set_hue(self._h)
                    self._sv_canvas.set_hsv(self._h, self._s, self._v)
                    self._current_hex = f"#{raw.upper()}"
                    self._update_previews()
            except ValueError:
                pass

    def _on_rgb_changed(self):
        r = self._spn_r.value()
        g = self._spn_g.value()
        b = self._spn_b.value()
        qc = QColor(r, g, b)
        if qc.isValid():
            self._h = qc.hsvHue() if qc.hsvHue() >= 0 else 0
            self._s = qc.hsvSaturation()
            self._v = qc.value()
            self._hue_wheel.set_hue(self._h)
            self._sv_canvas.set_hsv(self._h, self._s, self._v)
            self._current_hex = qc.name(QColor.NameFormat.HexRgb).upper()
            self._le_hex.blockSignals(True)
            self._le_hex.setText(self._current_hex)
            self._le_hex.blockSignals(False)
            self._update_previews()

    def _on_alpha_changed(self, val: int):
        self._alpha_val.setText(f"{val}%")

    def _on_ok(self):
        # Add to recent
        hex_s = self._current_hex
        if hex_s in self._recent:
            self._recent.remove(hex_s)
        self._recent.insert(0, hex_s)
        if len(self._recent) > self._MAX_RECENT:
            self._recent = self._recent[: self._MAX_RECENT]
        self.accept()

    # ---- Popup positioning ----

    def show_at(self, button: QWidget):
        btn = button
        self._parent_button = button
        pos = btn.mapToGlobal(btn.rect().bottomLeft())
        screen = btn.screen().availableGeometry()
        x = max(screen.left(), min(pos.x(), screen.right() - self.width()))
        y = pos.y()
        if y + self.height() > screen.bottom():
            y = btn.mapToGlobal(btn.rect().topLeft()).y() - self.height()
        self.move(x, y)
        self._apply_initial_color()
        self.show()
        self.activateWindow()

    def reject(self):
        self._current_hex = self._prev_hex
        super().reject()


class ColorPickerButton(QPushButton):
    """
    A button that shows a colour swatch + hex text.
    Clicking it opens the professional ColorPickerPopup.
    """

    color_changed = pyqtSignal(str)  # emits hex colour string

    def __init__(self, hex_color: str = "#FFFFFF", parent=None):
        super().__init__(parent)
        self._hex = hex_color.upper()
        self._popup: ColorPickerPopup | None = None
        self.setFixedHeight(28)
        self.setMinimumWidth(92)
        self.setText(self._hex)
        self.setAccessibleName(f"Chọn màu {self._hex}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._button_style())
        self.clicked.connect(self._open_picker)

    def set_color(self, hex_color: str):
        self._hex = hex_color.upper()
        self.setText(self._hex)
        self.setAccessibleName(f"Chọn màu {self._hex}")
        self.setStyleSheet(self._button_style())
        self.update()

    def color(self) -> str:
        return self._hex

    def _button_style(self) -> str:
        return (
            f"QPushButton {{ background: {C_ELEVATED_BG}; border: 1px solid {C_BORDER}; "
            f"border-radius: 5px; padding: 2px 4px 2px 36px; text-align: left; color: {C_TEXT}; "
            f"font-family: monospace; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {C_HOVER}; border-color: {C_ACCENT}; }}"
            f"QPushButton:pressed {{ background: {C_ACCENT_DIM}; }}"
            f"QPushButton:focus {{ border: 2px solid {C_ACCENT}; }}"
            f"QPushButton:disabled {{ color: #777b86; background: #191c26; border-color: #343845; }}"
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor(self._hex)
        rect = QRect(6, 3, 24, 22)
        p.setPen(QPen(QColor("#555555"), 1))
        p.setBrush(col)
        p.drawRoundedRect(rect, 3, 3)

    def _open_picker(self):
        self._popup = ColorPickerPopup(self._hex, self)
        self._popup.setStyleSheet("""
            ColorPickerPopup { background: transparent; }
        """)
        self._popup.finished.connect(self._on_picker_closed)
        self._popup.show_at(self)

    def _on_picker_closed(self, result: int):
        if result == QDialog.DialogCode.Accepted and self._popup:
            color = self._popup.selected_color()
            if color:
                self.set_color(color)
                self.color_changed.emit(color)


class SwatchButton(QPushButton):
    def __init__(self, hex_color: str, parent=None):
        super().__init__(parent)
        self._hex = hex_color.upper()
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{ background: {hex_color};
                          border: 1px solid {C_BORDER};
                          border-radius: 4px; }}
            QPushButton:hover {{ border-color: {C_ACCENT}; }}
        """)
        self.setToolTip(hex_color)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        p.setPen(QPen(QColor("#555555"), 1))
        p.setBrush(QColor(self._hex))
        p.drawRoundedRect(rect, 3, 3)


class HueWheel(QWidget):
    hue_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0
        self.setFixedSize(72, 72)
        self._cache: QImage | None = None

    def set_hue(self, hue: int):
        self._hue = hue
        self.update()

    def _build_image(self) -> QImage:
        size = self.width()
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = size // 2
        outer_r = center - 1
        inner_r = outer_r - 18
        for angle in range(360):
            rad = math.radians(angle - 90)
            x1 = center + outer_r * math.cos(rad)
            y1 = center + outer_r * math.sin(rad)
            x2 = center + inner_r * math.cos(rad)
            y2 = center + inner_r * math.sin(rad)
            pen = QPen(QColor.fromHsv(angle, 255, 255), 2)
            p.setPen(pen)
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
        # Selector ring
        rad_sel = math.radians(self._hue - 90)
        rx = center + (outer_r - 9) * math.cos(rad_sel)
        ry = center + (outer_r - 9) * math.sin(rad_sel)
        p.setPen(QPen(Qt.GlobalColor.white, 2))
        p.setBrush(Qt.GlobalColor.transparent)
        p.drawEllipse(int(rx) - 5, int(ry) - 5, 10, 10)
        p.end()
        return img

    def paintEvent(self, event):
        if self._cache is None:
            self._cache = self._build_image()
        p = QPainter(self)
        p.drawImage(self.rect(), self._cache)
        # Center fill preview
        cx = self.width() // 2
        cy = self.height() // 2
        r = cx - 18
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#555555"), 1))
        p.setBrush(QColor.fromHsv(self._hue, 255, 200))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

    def mousePressEvent(self, event):
        self._drag(event.pos())

    def mouseMoveEvent(self, event):
        if event.buttons():
            self._drag(event.pos())

    def _drag(self, pos: QPoint):
        cx = self.width() // 2
        cy = self.height() // 2
        dx = pos.x() - cx
        dy = pos.y() - cy
        angle = math.degrees(math.atan2(dy, dx)) + 90
        if angle < 0:
            angle += 360
        hue = int(angle) % 360
        if hue != self._hue:
            self._hue = hue
            self._cache = None
            self.update()
            self.hue_changed.emit(hue)


def _hsv_to_rgb(h: int, s: int, v: int) -> tuple[int, int, int]:
    """Convert HSV (0-360, 0-255, 0-255) to RGB (0-255, 0-255, 0-255).
    Rounds to match QColor.fromHsv() behaviour."""
    h = h % 360
    hi = (h // 60) % 6
    f = (h / 60.0) - (h // 60)
    s255 = s / 255.0
    v255 = v / 255.0
    p = v255 * (1.0 - s255)
    q = v255 * (1.0 - f * s255)
    t = v255 * (1.0 - (1.0 - f) * s255)
    vi = round(v255 * 255)
    pi = round(p * 255)
    qi = round(q * 255)
    ti = round(t * 255)
    if hi == 0: return (vi, ti, pi)
    if hi == 1: return (qi, vi, pi)
    if hi == 2: return (pi, vi, ti)
    if hi == 3: return (pi, qi, vi)
    if hi == 4: return (ti, pi, vi)
    return (vi, pi, qi)


class SVCanvas(QWidget):
    """
    2D canvas: horizontal = saturation (0→100 left→right),
               vertical   = value     (0→100 top→bottom).
    White corner = top-left,  Full hue+sat = bottom-right.
    """
    hsv_changed = pyqtSignal(int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._h = 0
        self._s = 255  # 0-255 scale (matching _move / set_hsv)
        self._v = 255
        self.setMinimumSize(180, 150)
        self._sv_cursor_x = 1.0  # 0..1
        self._sv_cursor_y = 0.0  # 0..1
        self._dragging = False
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_hsv(self, h: int, s: int, v: int):
        self._h = h
        self._s = s
        self._v = v
        self._sv_cursor_x = s / 255.0
        self._sv_cursor_y = 1.0 - v / 255.0
        self.update()

    def _build_image(self) -> QImage:
        w = self.width()
        h_img = self.height()
        img = QImage(w, h_img, QImage.Format.Format_ARGB32_Premultiplied)
        h = self._h
        for py in range(h_img):
            t = py / h_img  # 0 top → 1 bottom (spec: val = 1 - y/height)
            val = int((1.0 - t) * 255)  # 255 top (bright), 0 bottom (black)
            for px in range(w):
                s = int((px / w) * 255)  # 0 left (white), 255 right (pure hue)
                r, g, b = _hsv_to_rgb(h, s, val)
                img.setPixelColor(px, py, QColor(r, g, b, 255))
        return img

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        img = self._build_image()
        p.drawImage(self.rect(), img)
        # Cursor crosshair
        cx = int(self._sv_cursor_x * self.width())
        cy = int(self._sv_cursor_y * self.height())
        r = 5
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(Qt.GlobalColor.white, 2))
        p.drawLine(cx - r, cy, cx + r, cy)
        p.drawLine(cx, cy - r, cx, cy + r)
        p.setPen(QPen(Qt.GlobalColor.black, 1.5))
        p.drawEllipse(cx - 4, cy - 4, 8, 8)

    def mousePressEvent(self, event: QMouseEvent):
        self._dragging = True
        self._move(event.pos())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self._move(event.pos())

    def mouseReleaseEvent(self, _):
        self._dragging = False

    def _move(self, pos: QPoint):
        w = self.width()
        h = self.height()
        x = max(0, min(w - 1, pos.x()))
        y = max(0, min(h - 1, pos.y()))
        self._sv_cursor_x = x / w
        self._sv_cursor_y = y / h
        s = int(x / w * 255) if w > 0 else 0
        v = int((1.0 - y / h) * 255) if h > 0 else 0
        if s != self._s or v != self._v:
            self._s = s
            self._v = v
            self.update()
            self.hsv_changed.emit(self._h, self._s, self._v)
