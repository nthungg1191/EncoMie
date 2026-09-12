"""
Shared maths for the per-layer Curves control.

Monotone cubic Hermite interpolation (Fritsch-Carlson) through the control
points: passes through every point, never overshoots or wiggles between them -
the behaviour people expect from Premiere's curve, unlike a plain natural cubic
spline. The same sampler feeds the on-screen editor path, the preview LUT and
the point list baked for ffmpeg, so all three agree.
"""

IDENTITY = [[0.0, 0.0], [1.0, 1.0]]


def is_identity(points) -> bool:
    if not points or len(points) != 2:
        return False
    (x0, y0), (x1, y1) = points[0], points[1]
    return abs(x0) < 1e-4 and abs(y0) < 1e-4 and abs(x1 - 1) < 1e-4 and abs(y1 - 1) < 1e-4


def _clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _tangents(xs, ys):
    """Fritsch-Carlson monotone tangents."""
    n = len(xs)
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    m = [0.0] * n
    m[0] = d[0]
    m[-1] = d[-1]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0
        else:
            m[i] = (d[i - 1] + d[i]) / 2.0
    for i in range(n - 1):
        if d[i] == 0.0:
            m[i] = 0.0
            m[i + 1] = 0.0
            continue
        a = m[i] / d[i]
        b = m[i + 1] / d[i]
        s = a * a + b * b
        if s > 9.0:
            t = 3.0 / (s ** 0.5)
            m[i] = t * a * d[i]
            m[i + 1] = t * b * d[i]
    return m


def sample_curve(points, n: int = 256):
    """Return `n` y-values (0..1) for x evenly spaced over [0, 1]."""
    pts = sorted((float(x), float(y)) for x, y in points)
    if len(pts) == 1:
        return [_clamp01(pts[0][1])] * n
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    m = _tangents(xs, ys)

    out = []
    seg = 0
    for i in range(n):
        x = i / (n - 1)
        while seg < len(xs) - 2 and x > xs[seg + 1]:
            seg += 1
        x0, x1 = xs[seg], xs[seg + 1]
        h = x1 - x0
        if h <= 1e-9:
            out.append(_clamp01(ys[seg + 1]))
            continue
        t = (x - x0) / h
        t2 = t * t
        t3 = t2 * t
        h00 = 2 * t3 - 3 * t2 + 1
        h10 = t3 - 2 * t2 + t
        h01 = -2 * t3 + 3 * t2
        h11 = t3 - t2
        y = h00 * ys[seg] + h10 * h * m[seg] + h01 * ys[seg + 1] + h11 * h * m[seg + 1]
        out.append(_clamp01(y))
    return out


def bake_points(points, n: int = 33):
    """Sample the monotone curve at `n` evenly spaced x, as [x, y] pairs - the
    dense list handed to ffmpeg's `curves` so its spline hugs what the editor
    shows instead of re-interpolating the sparse control points its own way."""
    if is_identity(points):
        return [[0.0, 0.0], [1.0, 1.0]]
    ys = sample_curve(points, n)
    return [[i / (n - 1), ys[i]] for i in range(n)]


def format_points(points) -> str:
    """ffmpeg `curves` point list: `x/y x/y ...`, values 0..1."""
    return " ".join(f"{_clamp01(x):.4f}/{_clamp01(y):.4f}" for x, y in points)


def lut256(points) -> list:
    """0..255 -> 0..255 lookup table for a curve (identity fast-path)."""
    if is_identity(points):
        return list(range(256))
    ys = sample_curve(points, 256)
    return [max(0, min(255, int(round(v * 255.0)))) for v in ys]
