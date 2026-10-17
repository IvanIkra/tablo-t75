"""Line-drawn weather icons (§6.3, §7.4): sun, moon, cloud, rain 1-3, snow, storm, fog."""

import math

from PIL import ImageDraw

BLACK = 0
WHITE = 255


def draw(d: ImageDraw.ImageDraw, kind: str, cx: float, cy: float, size: float) -> None:
    lw = max(2, round(size / 14))
    if kind == "sun":
        _sun(d, cx, cy, size, lw)
    elif kind == "moon":
        _moon(d, cx, cy, size)
    elif kind == "cloud":
        _cloud(d, cx, cy, size, lw)
    else:
        # Precipitation icons: cloud moved up, marks below it.
        _cloud(d, cx, cy - size * 0.14, size, lw)
        top, bottom = cy + size * 0.18, cy + size * 0.42
        if kind.startswith("rain"):
            _rain(d, cx, top, bottom, size, int(kind[-1]), lw)
        elif kind == "snow":
            for dx in (-0.2, 0, 0.2):
                r = max(1.5, size * 0.04)
                x, y = cx + dx * size, (top + bottom) / 2
                d.ellipse((x - r, y - r, x + r, y + r), fill=BLACK)
        elif kind == "storm":
            s = size
            pts = [(cx + 0.04 * s, top - 0.02 * s), (cx - 0.08 * s, cy + 0.3 * s),
                   (cx + 0.04 * s, cy + 0.3 * s), (cx - 0.06 * s, bottom + 0.04 * s)]
            d.line(pts, fill=BLACK, width=lw, joint="curve")
        elif kind == "fog":
            for y in (top + 0.02 * size, bottom - 0.04 * size):
                d.line((cx - 0.34 * size, y, cx + 0.34 * size, y), fill=BLACK, width=lw)


def _sun(d, cx, cy, size, lw):
    r = size * 0.2
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=BLACK, width=lw)
    for i in range(8):
        a = math.pi / 4 * i
        r1, r2 = size * 0.3, size * 0.42
        d.line((cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                cx + r2 * math.cos(a), cy + r2 * math.sin(a)), fill=BLACK, width=lw)


def _moon(d, cx, cy, size):
    r = size * 0.3
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=BLACK)
    ox, oy, r2 = cx + r * 0.55, cy - r * 0.35, r * 0.85
    d.ellipse((ox - r2, oy - r2, ox + r2, oy + r2), fill=WHITE)


def _cloud_shapes(cx, cy, size, inset):
    s = size
    rect = (cx - 0.42 * s + inset, cy - 0.02 * s + inset, cx + 0.42 * s - inset, cy + 0.22 * s - inset)
    circles = ((cx - 0.16 * s, cy - 0.02 * s, 0.19 * s - inset), (cx + 0.1 * s, cy - 0.08 * s, 0.25 * s - inset))
    return rect, circles, max(1, 0.12 * s - inset)


def _cloud(d, cx, cy, size, lw):
    # Outline of a union of shapes: fill black, then fill the same shapes shrunk by the line width in white.
    for color, inset in ((BLACK, 0), (WHITE, lw)):
        rect, circles, radius = _cloud_shapes(cx, cy, size, inset)
        d.rounded_rectangle(rect, radius=radius, fill=color)
        for x, y, r in circles:
            d.ellipse((x - r, y - r, x + r, y + r), fill=color)


def _rain(d, cx, top, bottom, size, strokes, lw):
    xs = {1: (0,), 2: (-0.11, 0.11), 3: (-0.2, 0, 0.2)}[max(1, min(3, strokes))]
    for dx in xs:
        x = cx + dx * size
        d.line((x + 0.05 * size, top, x - 0.05 * size, bottom), fill=BLACK, width=lw)
