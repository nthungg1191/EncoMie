"""
Compact accordion-style group for the per-layer control panel (see the
"So Sánh Bảng Layer" demo). Click the header to expand/collapse; several
sections can be open at once (matches an Effects-panel-style properties list,
not a strict one-open accordion), and each header can carry a small status
badge + subtitle so a layer's state reads without opening every section.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt

_BADGE_STYLES = {
    "on":   ("#e9f8ee", "#16a34a"),
    "off":  ("#f5f5f7", "#9a98a6"),
    "pro":  ("#f1edff", "#7c5cff"),
    "warn": ("#fdf1e0", "#d97706"),
}


class CollapsibleSection(QWidget):
    def __init__(self, title: str, parent=None, open_: bool = False):
        super().__init__(parent)
        self._open = open_
        self.setStyleSheet(
            "CollapsibleSection { border: 1px solid #e4e4ea; border-radius: 8px; background: #ffffff; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QWidget(self)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setStyleSheet(
            "QWidget { background: transparent; border: none; } "
            "QWidget:hover { background: #fafafa; }"
        )
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(9, 7, 9, 7)
        hl.setSpacing(7)

        self._chevron = QLabel("▸")
        self._chevron.setFixedWidth(11)
        self._chevron.setStyleSheet("font-size: 10px; color: #9a98a6; border: none;")
        hl.addWidget(self._chevron)

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #1c1c1e; border: none;")
        hl.addWidget(self._title_lbl, 1)

        self._sub_lbl = QLabel("")
        self._sub_lbl.setStyleSheet("font-size: 9.5px; color: #9a98a6; border: none;")
        hl.addWidget(self._sub_lbl)

        self._badge_lbl = QLabel("")
        self._badge_lbl.setStyleSheet("border: none;")
        self._badge_lbl.setVisible(False)
        hl.addWidget(self._badge_lbl)

        outer.addWidget(self._header)

        self._body = QWidget(self)
        self.body_layout = QVBoxLayout(self._body)
        self.body_layout.setContentsMargins(11, 3, 11, 11)
        self.body_layout.setSpacing(8)
        outer.addWidget(self._body)

        self._body.setVisible(self._open)
        self._chevron.setText("▾" if self._open else "▸")

        self._header.mousePressEvent = self._on_header_clicked

    def _on_header_clicked(self, _event):
        self.set_open(not self._open)

    def set_open(self, open_: bool):
        self._open = open_
        self._body.setVisible(open_)
        self._chevron.setText("▾" if open_ else "▸")

    def is_open(self) -> bool:
        return self._open

    def set_subtitle(self, text: str):
        self._sub_lbl.setText(text or "")

    def set_badge(self, text: str, kind: str = "off"):
        if not text:
            self._badge_lbl.setVisible(False)
            return
        bg, fg = _BADGE_STYLES.get(kind, _BADGE_STYLES["off"])
        self._badge_lbl.setText(text)
        self._badge_lbl.setStyleSheet(
            f"font-size: 9px; font-weight: 600; padding: 2px 7px; border-radius: 8px; "
            f"background: {bg}; color: {fg}; border: none;"
        )
        self._badge_lbl.setVisible(True)
