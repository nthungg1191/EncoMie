"""Wrapping layout primitives for compact inspector fields."""

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QLabel,
    QLayout,
    QSizePolicy,
    QStyle,
    QWidget,
    QWidgetItem,
)


class FlowLayout(QLayout):
    """Lay items left-to-right and wrap them when the row is full."""

    def __init__(self, parent=None, margin: int = 0, h_spacing: int = 8, v_spacing: int = 6, max_columns: int = 4):
        super().__init__(parent)
        self._items = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._max_columns = max(1, max_columns)
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self):
        while self.takeAt(0) is not None:
            pass

    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, widget):
        self.addItem(QWidgetItem(widget))

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _smart_spacing(self, metric):
        parent = self.parent()
        if parent is None:
            return -1
        if parent.isWidgetType():
            return parent.style().pixelMetric(metric, None, parent)
        return parent.spacing()

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        h_space = self._h_spacing
        if h_space < 0:
            h_space = self._smart_spacing(QStyle.PixelMetric.PM_LayoutHorizontalSpacing)
        v_space = self._v_spacing
        if v_space < 0:
            v_space = self._smart_spacing(QStyle.PixelMetric.PM_LayoutVerticalSpacing)

        col_count = 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + h_space
            if line_height and (next_x - h_space > effective.right() + 1 or col_count >= self._max_columns):
                x = effective.x()
                y += line_height + v_space
                next_x = x + hint.width() + h_space
                line_height = 0
                col_count = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
            col_count += 1
        return y + line_height - rect.y() + margins.bottom()


class FlowWidget(QWidget):
    """A height-for-width host that refreshes its geometry after wrapping."""

    def __init__(self, parent=None, h_spacing: int = 8, v_spacing: int = 6, max_columns: int = 4):
        super().__init__(parent)
        self.flow_layout = FlowLayout(self, h_spacing=h_spacing, v_spacing=v_spacing, max_columns=max_columns)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._max_columns = max_columns
        self._field_width = 80
        self.setMaximumWidth(max(344, max_columns * self._field_width + max(0, max_columns - 1) * h_spacing))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.flow_layout.heightForWidth(min(width, self.maximumWidth()))

    def sizeHint(self):
        width = min(self.maximumWidth(), max(self.minimumWidth(), self.parentWidget().width() if self.parentWidget() else 0))
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self):
        width = min(self.maximumWidth(), max(self._field_width, self.width()))
        return QSize(self._field_width, self.heightForWidth(width))

    def add_field(self, label, control, *, input_width=80):
        field = StackedField(label, control, input_width=input_width, parent=self)
        self.flow_layout.addWidget(field)
        self.setMinimumHeight(self.flow_layout.heightForWidth(self.maximumWidth()))
        return field

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateGeometry()


class StackedField(QWidget):
    """A narrow label-over-control field designed for dense wrapping."""

    @staticmethod
    def _required_control_width(control: QWidget, base_width: int) -> int:
        width = base_width
        if isinstance(control, QAbstractSpinBox):
            le = control.lineEdit()
            fm = le.fontMetrics() if le is not None else control.fontMetrics()
            prefix = control.prefix() if hasattr(control, "prefix") else ""
            suffix = control.suffix() if hasattr(control, "suffix") else ""
            samples = [control.text()]
            if hasattr(control, "textFromValue"):
                samples.append(f"{prefix}{control.textFromValue(control.minimum())}{suffix}")
                samples.append(f"{prefix}{control.textFromValue(control.maximum())}{suffix}")
            max_text_w = max((fm.horizontalAdvance(text) for text in samples), default=0)
            # Reserve 18px up/down button column + borders + left/right padding + cursor breathing room
            width = max(width, max_text_w + 42)
        elif isinstance(control, QComboBox):
            fm = control.fontMetrics()
            samples = [control.itemText(i) for i in range(control.count())]
            max_text_w = max((fm.horizontalAdvance(text) for text in samples), default=0)
            # Reserve 20px drop-down arrow + 7px left/right padding + borders + inner margin
            width = max(width, max_text_w + 40)
        return max(80, min(160, width))

    def __init__(self, label, control, *, input_width=80, parent=None):
        super().__init__(parent)
        self.label = label if isinstance(label, QLabel) else QLabel(str(label), self)
        self.control = control
        self.label.setParent(self)
        self.control.setParent(self)
        width = self._required_control_width(control, input_width)
        self.label.setFixedSize(width, 14)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.label.setStyleSheet("font-size: 11px; color: #636366; border: none; padding: 0;")
        if not self.label.toolTip():
            self.label.setToolTip(self.label.text())

        self.control.setMinimumSize(0, 0)
        self.control.setMaximumSize(width, 28)
        self.control.resize(width, 28)
        self.control.setFixedSize(width, 28)
        self.control.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(width, 44)
        self.label.setGeometry(0, 0, width, 14)
        self.control.setGeometry(0, 16, width, 28)


# Compatibility for code that imported the first implementation by name.
Field = StackedField
