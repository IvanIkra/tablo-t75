"""Pixel fonts (§6.3): the screen sizes of Inter as hand-fixed bitmaps, drawn without FreeType.

A font is a text file made by tools/pixel_fonts.py and then fixed by hand:

    font Inter-Medium 16
    ascent 16
    descent 4

    glyph 0041 A
    advance 11 left 0 top 4
    ....###....
    ...

"top" is the first row counted from the top of the line (the baseline is row `ascent`), "left" is
where the rows start from the pen. A character the file lacks is drawn by FreeType as before.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PIXEL_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "pixel"


@dataclass
class Glyph:
    advance: int
    left: int
    top: int
    rows: list[str]


@dataclass
class PixelFont:
    name: str
    size: int
    ascent: int
    descent: int
    glyphs: dict[str, Glyph]

    def dumps(self) -> str:
        out = [f"font {self.name} {self.size}", f"ascent {self.ascent}", f"descent {self.descent}", ""]
        for ch, g in self.glyphs.items():
            out += [f"glyph {ord(ch):04X} {ch}", f"advance {g.advance} left {g.left} top {g.top}", *g.rows, ""]
        return "\n".join(out)

    def sheet(self, chars: str, zoom: int = 4) -> Image.Image:
        """All glyphs on their baselines with a grey pen box, for review."""
        line = self.ascent + self.descent
        per_row = 16
        cell = max(g.advance for g in self.glyphs.values()) + 4
        rows = math.ceil(len(chars) / per_row)
        img = Image.new("L", (per_row * cell, rows * (line + 4)), 255)
        d = ImageDraw.Draw(img)
        for i, ch in enumerate(chars):
            g = self.glyphs.get(ch)
            if g is None:
                continue
            x, y = (i % per_row) * cell + 2, (i // per_row) * (line + 4) + 2
            d.rectangle((x, y, x + g.advance - 1, y + line - 1), fill=235)
            d.line((x, y + self.ascent - 1, x + g.advance - 1, y + self.ascent - 1), fill=200)
            _put(d, g, x, y, 0)
        return img.resize((img.width * zoom, img.height * zoom), Image.NEAREST)


def _put(d: ImageDraw.ImageDraw, g: Glyph, x: int, y: int, fill) -> None:
    points = [(x + g.left + cx, y + g.top + cy) for cy, row in enumerate(g.rows) for cx, ch in enumerate(row) if ch == "#"]
    if points:
        d.point(points, fill=fill)


def parse(text: str) -> PixelFont:
    lines = text.splitlines()
    head = {}
    i = 0
    while i < len(lines) and not lines[i].startswith("glyph "):
        parts = lines[i].split()
        if parts:
            head[parts[0]] = parts[1:]
        i += 1
    glyphs: dict[str, Glyph] = {}
    while i < len(lines):
        ch = chr(int(lines[i].split()[1], 16))
        f = lines[i + 1].split()
        vals = dict(zip(f[0::2], map(int, f[1::2])))
        i += 2
        rows = []
        while i < len(lines) and lines[i] and not lines[i].startswith("glyph "):
            rows.append(lines[i])
            i += 1
        glyphs[ch] = Glyph(vals["advance"], vals.get("left", 0), vals.get("top", 0), rows)
        while i < len(lines) and not lines[i]:
            i += 1
    name, size = head["font"]
    return PixelFont(name, int(size), int(head["ascent"][0]), int(head["descent"][0]), glyphs)


def load(path: Path) -> PixelFont:
    return parse(path.read_text(encoding="utf-8"))


def path_for(font: ImageFont.FreeTypeFont) -> Path:
    return PIXEL_DIR / f"{Path(font.path).stem}-{font.size}.txt"


@lru_cache(maxsize=None)
def _cached(path: Path) -> PixelFont | None:
    return load(path) if path.exists() else None


def lookup(font: ImageFont.FreeTypeFont) -> PixelFont | None:
    """The pixel version of a FreeType font, if there is one."""
    return _cached(path_for(font))


def width(pf: PixelFont, font: ImageFont.FreeTypeFont, text: str) -> int:
    return sum(pf.glyphs[ch].advance if ch in pf.glyphs else round(font.getlength(ch, mode="1")) for ch in text)


def draw(d: ImageDraw.ImageDraw, pf: PixelFont, font: ImageFont.FreeTypeFont, xy, text: str, fill, anchor: str) -> None:
    """Like ImageDraw.text with a two-letter anchor; characters without a glyph go through FreeType."""
    h, v = anchor[0], anchor[1]
    w = width(pf, font, text)
    x = xy[0] - {"l": 0, "m": w / 2, "r": w}[h]
    # Where the baseline is for each vertical anchor, the same way PIL counts it.
    baseline = xy[1] + {"a": pf.ascent, "s": 0, "d": -pf.descent,
                        "m": math.ceil(pf.ascent - (pf.ascent + pf.descent) / 2)}[v]
    # Halves round down, as PIL does; the baseline stays put whatever the text (PIL moves it by a pixel).
    pen, top = math.ceil(x - 0.5), math.ceil(baseline - 0.5) - pf.ascent
    for ch in text:
        g = pf.glyphs.get(ch)
        if g is not None:
            _put(d, g, pen, top, fill)
            pen += g.advance
        else:
            d.text((pen, top + pf.ascent), ch, font=font, fill=fill, anchor="ls")
            pen += round(font.getlength(ch, mode="1"))
