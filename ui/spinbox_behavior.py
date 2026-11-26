"""Native spin-box press behavior shared by all inspector panels."""

from datetime import datetime
import os
from pathlib import Path
import sys

from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QAbstractSpinBox, QStyle, QStyleOptionSpinBox


def _debug_log_path():
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    return base / "spinbox_debug.log"


class SpinPressController(QObject):
    """Keep focus stable and repeat spin steps after 400 ms, then every 60 ms."""

    def __init__(self, spinbox: QAbstractSpinBox):
        super().__init__(spinbox)
        self.spinbox = spinbox
        self.line_edit = spinbox.lineEdit()
        self.direction = 0
        self.button_press_active = False
        self._stepping = False
        self.delay = QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.setInterval(400)
        self.delay.timeout.connect(self._begin_repeat)
        self.repeat = QTimer(self)
        self.repeat.setInterval(60)
        self.repeat.timeout.connect(self._step)
        spinbox.installEventFilter(self)
        if self.line_edit is not None:
            self.line_edit.installEventFilter(self)
            self.line_edit.selectionChanged.connect(self._on_selection_changed)
        spinbox.setAccelerated(True)
        self._debug("controller_installed")

    def _on_selection_changed(self):
        if (self._stepping or self.button_press_active) and self.line_edit is not None:
            if self.line_edit.hasSelectedText():
                self.line_edit.deselect()

    def _debug_name(self):
        return self.spinbox.property("spinDebugName") or ""

    def _debug(self, event_name, **details):
        name = self._debug_name()
        if not name or not os.environ.get("ENCOMIE_DEBUG") or os.environ.get("PYTEST_CURRENT_TEST"):
            return
        line_edit = self.spinbox.lineEdit()
        selected = line_edit.selectedText() if line_edit is not None else ""
        fields = {
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "field": name,
            "event": event_name,
            "value": self.spinbox.value(),
            "selected": repr(selected),
            "focus": self.spinbox.hasFocus(),
            "geometry": self.spinbox.geometry().getRect(),
            **details,
        }
        try:
            with _debug_log_path().open("a", encoding="utf-8") as handle:
                handle.write(" | ".join(f"{key}={value}" for key, value in fields.items()) + "\n")
        except OSError:
            pass

    def _subcontrol(self, pos):
        option = QStyleOptionSpinBox()
        self.spinbox.initStyleOption(option)
        return self.spinbox.style().hitTestComplexControl(
            QStyle.ComplexControl.CC_SpinBox, option, pos, self.spinbox
        )

    def _stop(self):
        self.direction = 0
        self.delay.stop()
        self.repeat.stop()

    def _deselect(self):
        line_edit = self.spinbox.lineEdit()
        if line_edit is not None:
            line_edit.deselect()

    def _deselect_after_event(self):
        self._debug("deselect_before")
        self._deselect()
        def finish():
            self._deselect()
            self._debug("deselect_after")
        QTimer.singleShot(0, finish)

    def _step(self):
        if not self.direction or not self.spinbox.isEnabled():
            self._stop()
            return
        before = self.spinbox.value()
        line_edit = self.spinbox.lineEdit()
        # QAbstractSpinBox selects its numeric text inside stepBy(). Prevent an
        # intermediate paint so that selection never flashes on screen.
        self._stepping = True
        self.spinbox.setUpdatesEnabled(False)
        try:
            if line_edit is not None:
                line_edit.deselect()
            self.spinbox.stepBy(self.direction)
            if line_edit is not None:
                line_edit.deselect()
                line_edit.setCursorPosition(len(line_edit.text()))
        finally:
            self._stepping = False
            self.spinbox.setUpdatesEnabled(True)
        self.spinbox.update()
        self._debug("step", direction=self.direction, before=before, after=self.spinbox.value())
        self._deselect_after_event()
        if self.spinbox.value() == before:
            self._stop()

    def _begin_repeat(self):
        self._step()
        if self.direction:
            self.repeat.start()

    def _map_to_spinbox(self, watched, pos):
        if watched is self.spinbox:
            return pos
        return watched.mapTo(self.spinbox, pos)

    def eventFilter(self, watched, event):
        if watched not in (self.spinbox, self.line_edit):
            return False
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            pos = self._map_to_spinbox(watched, event.position().toPoint())
            self._debug(
                "double_press" if event.type() == QEvent.Type.MouseButtonDblClick else "press",
                x=pos.x(), y=pos.y(), right_hit_start=self.spinbox.width() - 28,
            )
            # Keep a 28 px-wide hit column even when the visual arrow column is
            # narrower so suffix text still has enough room.
            if pos.x() >= self.spinbox.width() - 28:
                self.direction = 1 if pos.y() < self.spinbox.height() / 2 else -1
            else:
                control = self._subcontrol(pos)
                if control == QStyle.SubControl.SC_SpinBoxUp:
                    self.direction = 1
                elif control == QStyle.SubControl.SC_SpinBoxDown:
                    self.direction = -1
                else:
                    return False
            self.button_press_active = True
            self.spinbox.setFocus()
            self._step()
            self._deselect_after_event()
            if self.direction:
                self.delay.start()
            return True
        if event.type() == QEvent.Type.MouseMove and self.button_press_active:
            self._deselect()
            return True
        if event.type() == QEvent.Type.MouseButtonRelease and self.button_press_active:
            pos = self._map_to_spinbox(watched, event.position().toPoint())
            self._debug("release", x=pos.x(), y=pos.y())
            self._stop()
            self.button_press_active = False
            self._deselect_after_event()
            return True
        if event.type() == QEvent.Type.Leave and watched is self.spinbox and self.button_press_active:
            self._debug("leave")
            self._stop()
            self.button_press_active = False
            self._deselect_after_event()
            return True
        return False


def install_spinbox_behavior(root):
    for spinbox in root.findChildren(QAbstractSpinBox):
        if spinbox.property("spinDisableButtons"):
            continue
        if getattr(spinbox, "_press_controller", None) is None:
            spinbox._press_controller = SpinPressController(spinbox)

