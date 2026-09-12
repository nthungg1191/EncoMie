"""
Approximate Curves preview for the Qt widgets.

FFmpeg's `curves` filter does the real thing at render time
(video_processor._build_color_filter). This applies the same monotone-cubic
curve LUTs to a QImage the caller has already scaled to preview size (and
should cache). Dependency-free: one pass over the pixel buffer.
"""
from PyQt6.QtGui import QImage


def grade_qimage(src: QImage, cg) -> QImage:
    """Return a NEW curve-adjusted image. Returns `src` unchanged if inactive."""
    if src is None or src.isNull() or cg is None or not getattr(cg, "is_active", lambda: False)():
        return src

    from core.curves import lut256
    lm = lut256(cg.curve_m)
    lr = lut256(cg.curve_r)
    lg = lut256(cg.curve_g)
    lb = lut256(cg.curve_b)
    identity = list(range(256))
    if lm == identity and lr == identity and lg == identity and lb == identity:
        return src

    # .copy() forces a detached, contiguous buffer we own outright: without it
    # convertToFormat can hand back a view that still shares memory with the
    # cached keyed/blurred layer image, and mutating it in place corrupts that
    # shared source (streaky colour garbage that compounds every repaint).
    img = src.convertToFormat(QImage.Format.Format_ARGB32).copy()
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()  # row stride; may exceed w*4 due to alignment padding

    try:
        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())
        buf = memoryview(ptr)
    except Exception:
        return src

    # ARGB32 little-endian byte order per pixel: B, G, R, A.
    # Per-channel curve first, then master on top, matching ffmpeg `curves`.
    for y in range(h):
        row = y * bpl
        for x in range(w):
            i = row + (x << 2)
            buf[i] = lm[lb[buf[i]]]
            buf[i + 1] = lm[lg[buf[i + 1]]]
            buf[i + 2] = lm[lr[buf[i + 2]]]

    return img
