"""
Compact tone-curve editor (one channel at a time).

Click the curve to add a point, drag a point to move it, drag a point well
outside the box (or right-click it) to delete it. The two end points stay on
the left/right edges but move vertically.
"""
from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtCore import Qt, QPointF, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath, QImage

from core.curves import sample_curve

# Light theme to match the app.
_BG = "#ffffff"
_GRID = "#ececef"
_DIAG = "#d1d1d6"
_BORDER = "#c7c7cc"
_CH_COLOR = {"m": "#2c2c2e", "r": "#e5484d", "g": "#30a46c", "b": "#3b82f6"}


def _identity():
    return [[0.0, 0.0], [1.0, 1.0]]


class CurveEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._curves = {c: _identity() for c in ("m", "r", "g", "b")}
        self._channel = "m"
        self._drag = None            # index of point being dragged
        self._locked = False
        self._hist = {}              # channel -> list[256] normalised 0..1
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    def sizeHint(self):
        return QSize(220, 190)

    def minimumSizeHint(self):
        return QSize(120, 150)

    # -- data ------------------------------------------------------------
    def curves(self) -> dict:
        return {c: [list(p) for p in pts] for c, pts in self._curves.items()}

    def set_curves(self, data: dict):
        if not isinstance(data, dict):
            return
        for c in ("m", "r", "g", "b"):
            pts = data.get(c)
            if isinstance(pts, list) and len(pts) >= 2:
                self._curves[c] = [[float(p[0]), float(p[1])] for p in pts]
            else:
                self._curves[c] = _identity()
        self.update()

    def set_channel(self, ch: str):
        if ch in self._curves:
            self._channel = ch
            self.update()

    def set_histogram_image(self, img):
        """Compute luma + per-channel histograms from a preview frame."""
        self._hist = {}
        if isinstance(img, QImage) and not img.isNull():
            small = img.scaled(QSize(160, 160), Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.FastTransformation).convertToFormat(
                QImage.Format.Format_ARGB32)
            w, h = small.width(), small.height()
            bpl = small.bytesPerLine()
            bins = {c: [0] * 256 for c in ("m", "r", "g", "b")}
            try:
                ptr = small.bits()
                ptr.setsize(small.sizeInBytes())
                buf = memoryview(ptr)
                for y in range(h):
                    row = y * bpl
                    for x in range(w):
                        i = row + (x << 2)
                        b, g, r = buf[i], buf[i + 1], buf[i + 2]
                        bins["b"][b] += 1
                        bins["g"][g] += 1
                        bins["r"][r] += 1
                        bins["m"][(r * 299 + g * 587 + b * 114) // 1000] += 1
            except Exception:
                self._hist = {}
                self.update()
                return
            for c, arr in bins.items():
                peak = max(arr[1:255]) if any(arr[1:255]) else 1
                self._hist[c] = [min(1.0, v / peak) for v in arr]
        self.update()

    def set_locked(self, locked: bool):
        self._locked = locked
        self.setEnabled(not locked)

    def reset_channel(self):
        self._curves[self._channel] = _identity()
        self.update()
        self.changed.emit()

    def reset_all(self):
        self._curves = {c: _identity() for c in ("m", "r", "g", "b")}
        self.update()
        self.changed.emit()

    # -- geometry ------------------------------------------------------
    def _box(self):
        m = 8
        s = min(self.width(), self.height()) - 2 * m
        s = max(40, s)
        x0 = (self.width() - s) / 2
        y0 = (self.height() - s) / 2
        return x0, y0, s

    def _to_px(self, x, y):
        x0, y0, s = self._box()
        return QPointF(x0 + x * s, y0 + (1.0 - y) * s)

    def _to_val(self, px, py):
        x0, y0, s = self._box()
        return (px - x0) / s, 1.0 - (py - y0) / s

    # -- mouse -------------------------------------------------------
    def mousePressEvent(self, e):
        if self._locked:
            return
        pts = self._curves[self._channel]
        vx, vy = self._to_val(e.position().x(), e.position().y())
        for i, (x, y) in enumerate(pts):
            if (self._to_px(x, y) - e.position()).manhattanLength() < 12:
                if e.button() == Qt.MouseButton.RightButton and 0 < i < len(pts) - 1:
                    del pts[i]
                    self.update()
                    self.changed.emit()
                    return
                self._drag = i
                return
        if e.button() != Qt.MouseButton.LeftButton:
            return
        vx = max(0.0, min(1.0, vx))
        vy = max(0.0, min(1.0, vy))
        idx = 0
        while idx < len(pts) and pts[idx][0] < vx:
            idx += 1
        pts.insert(idx, [vx, vy])
        self._drag = idx
        self.update()
        self.changed.emit()

    def mouseMoveEvent(self, e):
        if self._locked or self._drag is None:
            return
        pts = self._curves[self._channel]
        i = self._drag
        vx, vy = self._to_val(e.position().x(), e.position().y())
        vy = max(0.0, min(1.0, vy))
        if i == 0:
            pts[0] = [0.0, vy]
        elif i == len(pts) - 1:
            pts[-1] = [1.0, vy]
        else:
            lo = pts[i - 1][0] + 0.02
            hi = pts[i + 1][0] - 0.02
            pts[i] = [max(lo, min(hi, vx)), vy]
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, e):
        if self._drag is not None and 0 < self._drag < len(self._curves[self._channel]) - 1:
            y = e.position().y()
            x0, y0, s = self._box()
            if y < y0 - 24 or y > y0 + s + 24:
                del self._curves[self._channel][self._drag]
                self.update()
                self.changed.emit()
        self._drag = None

    # -- paint -----------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x0, y0, s = self._box()
        box = QRectF(x0, y0, s, s)

        p.fillRect(self.rect(), QColor(_BG))
        p.fillRect(box, QColor(_BG))

        hist = self._hist.get(self._channel)
        if hist:
            hc = QColor(_CH_COLOR[self._channel])
            hc.setAlpha(38)
            hp = QPainterPath()
            hp.moveTo(x0, y0 + s)
            for k in range(256):
                hp.lineTo(x0 + s * k / 255.0, y0 + s - s * 0.42 * hist[k])
            hp.lineTo(x0 + s, y0 + s)
            hp.closeSubpath()
            p.fillPath(hp, hc)

        p.setPen(QPen(QColor(_GRID), 1))
        for k in range(1, 4):
            gx = x0 + s * k / 4
            gy = y0 + s * k / 4
            p.drawLine(QPointF(gx, y0), QPointF(gx, y0 + s))
            p.drawLine(QPointF(x0, gy), QPointF(x0 + s, gy))
        p.setPen(QPen(QColor(_DIAG), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x0, y0 + s), QPointF(x0 + s, y0))

        for ch in ("m", "r", "g", "b"):
            if ch != self._channel:
                self._draw_curve(p, ch, 55, 1)
        self._draw_curve(p, self._channel, 255, 2, handles=True)

        p.setPen(QPen(QColor(_BORDER), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(box)

    def _draw_curve(self, p, ch, alpha, width, handles=False):
        pts = self._curves[ch]
        ys = sample_curve(pts, 96)
        path = QPainterPath()
        for i, y in enumerate(ys):
            pt = self._to_px(i / (len(ys) - 1), y)
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        c = QColor(_CH_COLOR[ch])
        c.setAlpha(alpha)
        p.setPen(QPen(c, width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        if handles:
            p.setBrush(QColor("#ffffff"))
            p.setPen(QPen(QColor(_CH_COLOR[ch]), 1.4))
            for x, y in pts:
                p.drawEllipse(self._to_px(x, y), 4.0, 4.0)
