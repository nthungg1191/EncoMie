"""Shared QImage layer effects and hit-testing utilities for preview canvases."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene


def hit_test_handle(pos: QPointF, handle_pos: QPointF, radius: float = 10.0) -> bool:
    """Return True if pointer `pos` is within `radius` pixels of `handle_pos`."""
    return (pos - handle_pos).manhattanLength() <= radius


def apply_blur(img: QImage, sigma: float) -> QImage:
    """Apply edge-clamped Gaussian blur matching FFmpeg gblur without enlarging bounds."""
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(img))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(sigma * 2.0)
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    target = QImage(img.width(), img.height(), QImage.Format.Format_ARGB32)
    target.fill(Qt.GlobalColor.transparent)
    painter = QPainter(target)
    scene.render(
        painter,
        QRectF(0, 0, img.width(), img.height()),
        QRectF(0, 0, img.width(), img.height()),
    )
    painter.end()
    return target


def apply_luma_key(img: QImage, threshold: float, tolerance: float, softness: float) -> QImage:
    """Approximate FFmpeg's lumakey filter for interactive layer previews."""
    if img.isNull():
        return img

    scaled_img = img.scaled(
        QSize(400, 400),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    scaled_img = scaled_img.convertToFormat(QImage.Format.Format_ARGB32)

    w, h = scaled_img.width(), scaled_img.height()
    bpl = scaled_img.bytesPerLine()
    try:
        ptr = scaled_img.bits()
        ptr.setsize(scaled_img.sizeInBytes())
        buf = memoryview(ptr)
    except Exception:
        return scaled_img

    soft = max(1e-4, softness)

    for y in range(h):
        row = y * bpl
        for x in range(w):
            i = row + (x << 2)
            b, g, r, a = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]
            luma = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            dist = abs(luma - threshold)
            if dist <= tolerance:
                buf[i + 3] = 0
            elif dist <= tolerance + soft:
                buf[i + 3] = int(a * (dist - tolerance) / soft)
    return scaled_img


def apply_chroma_key(
    img: QImage,
    similarity: float,
    blend: float,
    color: str,
    spill: float = 0.0,
) -> QImage:
    """Downscale and apply chroma-key + despill for interactive layer previews."""
    if img.isNull():
        return img

    scaled_img = img.scaled(
        QSize(400, 400),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )
    scaled_img = scaled_img.convertToFormat(QImage.Format.Format_ARGB32)

    width = scaled_img.width()
    height = scaled_img.height()

    ptr = scaled_img.bits()
    ptr.setsize(height * width * 4)
    buf = memoryview(ptr)

    hex_val = color.lstrip("#")
    if len(hex_val) == 6:
        tr = int(hex_val[0:2], 16) / 255.0
        tg = int(hex_val[2:4], 16) / 255.0
        tb = int(hex_val[4:6], 16) / 255.0
    else:
        tr, tg, tb = 0.0, 1.0, 0.0

    # In Format_ARGB32: bytes are ordered B, G, R, A on little-endian
    if tg >= tr and tg >= tb:
        max_c = "g"
    elif tb >= tr and tb >= tg:
        max_c = "b"
    else:
        max_c = "r"

    for i in range(0, len(buf), 4):
        b = buf[i]
        g = buf[i + 1]
        r = buf[i + 2]

        rn = r / 255.0
        gn = g / 255.0
        bn = b / 255.0

        cd_sq = (rn - tr) * (rn - tr) + (gn - tg) * (gn - tg) + (bn - tb) * (bn - tb)
        cd = cd_sq ** 0.5

        if cd < similarity:
            buf[i + 3] = 0
        elif blend > 0.001 and cd < similarity + blend:
            alpha = int(255 * (cd - similarity) / blend)
            buf[i + 3] = max(0, min(255, alpha))

        # Apply despill if configured and pixel is not fully transparent
        if spill > 0.001 and buf[i + 3] > 0:
            if max_c == "g":
                tg_spill = (r + b) // 2
                if g > tg_spill:
                    buf[i + 1] = int(g - (g - tg_spill) * spill)
            elif max_c == "b":
                tb_spill = (r + g) // 2
                if b > tb_spill:
                    buf[i] = int(b - (b - tb_spill) * spill)
            elif max_c == "r":
                tr_spill = (g + b) // 2
                if r > tr_spill:
                    buf[i + 2] = int(r - (r - tr_spill) * spill)

    return scaled_img
