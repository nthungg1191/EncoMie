"""
Compact per-layer Curves panel (Pro).

Header toggle collapses the body. One tone-curve editor with M / R / G / B
channel buttons.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton, QButtonGroup
)
from PyQt6.QtCore import pyqtSignal

from core.video_processor import ColorGrade
from ui.curve_editor import CurveEditor

_CHANNELS = [("m", "Master"), ("r", "R"), ("g", "G"), ("b", "B")]


class ColorGradePanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._locked = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.chk_enabled = QCheckBox("Bật Curves")
        self.chk_enabled.setStyleSheet("font-size: 11px; font-weight: bold;")
        self.chk_enabled.toggled.connect(self._on_toggle)
        head.addWidget(self.chk_enabled)
        head.addStretch(1)
        self.btn_reset = QPushButton("Đặt lại")
        self.btn_reset.setFixedHeight(20)
        self.btn_reset.setStyleSheet("font-size: 10px; padding: 0 8px;")
        self.btn_reset.clicked.connect(self._reset_all)
        head.addWidget(self.btn_reset)
        root.addLayout(head)

        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)

        ch_row = QHBoxLayout()
        ch_row.setSpacing(3)
        self._ch_group = QButtonGroup(self)
        self._ch_group.setExclusive(True)
        for key, label in _CHANNELS:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedHeight(20)
            b.setStyleSheet(
                "QPushButton { font-size: 10px; padding: 0 6px; border: 1px solid #48484a;"
                " border-radius: 3px; background: #2c2c2e; color: #aeaeb2; }"
                "QPushButton:checked { background: #0a84ff; color: #fff; border-color: #0a84ff; }"
            )
            b.clicked.connect(lambda _c, k=key: self._editor.set_channel(k))
            self._ch_group.addButton(b)
            ch_row.addWidget(b)
            if key == "m":
                b.setChecked(True)
        ch_row.addStretch(1)
        self._btn_reset_ch = QPushButton("Xóa kênh")
        self._btn_reset_ch.setFixedHeight(20)
        self._btn_reset_ch.setStyleSheet("font-size: 10px; padding: 0 6px;")
        self._btn_reset_ch.clicked.connect(self._reset_channel)
        ch_row.addWidget(self._btn_reset_ch)
        body.addLayout(ch_row)

        self._editor = CurveEditor()
        self._editor.changed.connect(self.changed)
        body.addWidget(self._editor)

        hint = QLabel("Chạm đường cong để thêm điểm · kéo ra ngoài để xóa")
        hint.setStyleSheet("font-size: 9px; color: #8e8e93;")
        body.addWidget(hint)

        root.addWidget(self._body)
        self._body.setVisible(False)

    # -- events ---------------------------------------------------------
    def _on_toggle(self, on: bool):
        self._body.setVisible(on and not self._locked)
        self.changed.emit()

    def _reset_all(self):
        self._editor.reset_all()

    def _reset_channel(self):
        self._editor.reset_channel()

    # -- public API --------------------------------------------------
    def is_locked(self) -> bool:
        return self._locked

    def set_histogram_image(self, img):
        self._editor.set_histogram_image(img)

    def set_locked(self, locked: bool):
        self._locked = locked
        self.chk_enabled.setEnabled(not locked)
        self._body.setEnabled(not locked)
        self._editor.set_locked(locked)
        if locked:
            self.chk_enabled.setChecked(False)
            self._body.setVisible(False)
            self.setToolTip("Curves chỉ có ở gói Pro")
        else:
            self.setToolTip("")
            self._body.setVisible(self.chk_enabled.isChecked())

    def get_config(self) -> ColorGrade:
        c = self._editor.curves()
        return ColorGrade(
            enabled=self.chk_enabled.isChecked() and not self._locked,
            curve_m=c["m"], curve_r=c["r"], curve_g=c["g"], curve_b=c["b"],
        )

    def set_config(self, cg):
        if cg is None:
            return
        if not isinstance(cg, ColorGrade):
            cg = ColorGrade.from_dict(cg)
        self.chk_enabled.setChecked(bool(cg.enabled))
        self._editor.set_curves({
            "m": cg.curve_m, "r": cg.curve_r, "g": cg.curve_g, "b": cg.curve_b,
        })
        self._body.setVisible(self.chk_enabled.isChecked() and not self._locked)
