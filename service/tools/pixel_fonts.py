"""Pixel versions of the screen fonts (§6.3): Inter rasterised by FreeType in 1 bit, saved as text to fix by hand.

    python tools/pixel_fonts.py            # write the fonts that do not exist yet
    python tools/pixel_fonts.py --add      # add glyphs missing from existing files, keep the rest
    python tools/pixel_fonts.py --sheet    # PNG sheets of every font at 4x into captures/
    python tools/pixel_fonts.py --align    # put every letter and digit on the common lines, in place

Also the clock digits of the firmware zone (§2): Inter Bold 64 narrowed to one width, so "HH:MM"
fits the 184 px zone and the time does not change width every minute.

A file is assets/fonts/pixel/<font file>-<size>.txt. Hand edits live in the files, so a font is never
regenerated over them: delete a file (or a glyph) to have it made again.
"""

from __future__ import annotations

import argparse
import string
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tablo.render import fonts, pixelfont  # noqa: E402

# The fonts of the main screen; the overlays use larger sizes, where FreeType alone draws well.
SCREEN_FONTS = [(15, "medium"), (16, "medium"), (16, "semibold"), (30, "semibold")]

CHARS = "".join(chr(c) for c in range(32, 127)) + "°·—–…’‘“”«»•×→€±é"


def _draw(font, ch: str, mono: bool) -> Image.Image:
    ascent, descent = font.getmetrics()
    pad = font.size
    img = Image.new("L", (font.size * 3, ascent + descent + 2 * pad), 255)
    d = ImageDraw.Draw(img)
    if mono:
        d.fontmode = "1"
    d.text((pad, pad + ascent), ch, font=font, fill=0, anchor="ls")
    return img


def thicken_stems(ink: list[list[bool]], grey: Image.Image, min_run: int) -> None:
    """Make 1 px vertical stems 2 px wide, on the side where the antialiased glyph has more ink.

    FreeType's monochrome hinting rounds Inter's ~1.6 px stems to 2 px on one side of n, h, u, m
    and to 1 px on the other, which reads as uneven type.
    """
    h, w = len(ink), len(ink[0])
    on = lambda x, y: 0 <= x < w and ink[y][x]
    for x in range(w):
        y = 0
        while y < h:
            if not (on(x, y) and not on(x - 1, y) and not on(x + 1, y)):
                y += 1
                continue
            start = y
            while y < h and on(x, y) and not on(x - 1, y) and not on(x + 1, y):
                y += 1
            if y - start >= min_run:
                cover = {s: sum(255 - grey.getpixel((x + s, r)) for r in range(start, y)) for s in (-1, 1) if 0 <= x + s < w}
                side = max(cover, key=cover.get)
                for r in range(start, y):
                    ink[r][x + side] = True


def rasterise(font, ch: str) -> pixelfont.Glyph:
    pad = font.size
    mono, grey = _draw(font, ch, True), _draw(font, ch, False)
    advance = round(font.getlength(ch, mode="1"))
    if mono.point(lambda v: 255 - v).getbbox() is None:
        return pixelfont.Glyph(advance, 0, 0, [])
    ink = [[mono.getpixel((x, y)) < 128 for x in range(mono.width)] for y in range(mono.height)]
    if font.size < 20:
        thicken_stems(ink, grey, min_run=4)
    xs = [x for row in ink for x, v in enumerate(row) if v]
    ys = [y for y, row in enumerate(ink) if any(row)]
    x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    rows = ["".join("#" if ink[y][x] else "." for x in range(x0, x1)) for y in range(y0, y1)]
    return pixelfont.Glyph(advance, x0 - pad, y0 - pad, rows)


CLOCK_PATH = pixelfont.PIXEL_DIR / "clock-64.txt"
CLOCK_ADVANCE, CLOCK_INK, COLON_ADVANCE = 40, 34, 14  # 4 x 40 + 14 = 174 px


def clock_font() -> pixelfont.PixelFont:
    """Digits and colon: drawn 8x larger, narrowed to CLOCK_INK, cut at 50%, centred in a fixed advance."""
    z = 8
    font = ImageFont.truetype(str(fonts.ASSETS / "fonts" / "Inter-Bold.ttf"), 64)
    big = ImageFont.truetype(str(fonts.ASSETS / "fonts" / "Inter-Bold.ttf"), 64 * z)
    ascent, descent = font.getmetrics()
    drawn = {}
    for ch in "0123456789:":
        im = Image.new("L", (100 * z, 100 * z), 255)
        ImageDraw.Draw(im).text((10 * z, 80 * z), ch, font=big, fill=0, anchor="ls")
        box = im.point(lambda v: 255 - v).getbbox()
        drawn[ch] = box, im.crop(box)
    widest = max(drawn[d][1].width for d in "0123456789") / z
    glyphs = {}
    for ch, (box, crop) in drawn.items():
        w = round(crop.width / z * (1 if ch == ":" else CLOCK_INK / widest))
        small = crop.resize((w, round(crop.height / z)), Image.LANCZOS)
        rows = ["".join("#" if small.getpixel((x, y)) < 128 else "." for x in range(small.width)) for y in range(small.height)]
        advance = COLON_ADVANCE if ch == ":" else CLOCK_ADVANCE
        glyphs[ch] = pixelfont.Glyph(advance, (advance - w) // 2, ascent + round((box[1] - 80 * z) / z), rows)
    return pixelfont.PixelFont("Inter-Bold-clock", 64, ascent, descent, glyphs)


def _merge(a: str, b: str) -> str:
    return "".join("#" if "#" in (x, y) else "." for x, y in zip(a.ljust(len(b), "."), b.ljust(len(a), ".")))


def align_heights(pf: pixelfont.PixelFont) -> list[str]:
    """Letters and digits on common lines: cap height, digit height, x-height, ascender, baseline.

    Fonts let round shapes overshoot the lines a little; at these sizes that is a whole pixel and
    reads as letters jumping. A row past the line is merged into its neighbour (the outline stays
    closed); a glyph shifted by a whole row is moved back.
    """
    def top(ch):
        g = pf.glyphs.get(ch)
        return g.top if g and g.rows else None

    base = pf.ascent - 1
    refs = {}
    for chars, ref in ((string.ascii_uppercase, top("H")), (string.digits, top("1") or top("4")),
                       ("acemnorsuvwxzgpqy", top("x")), ("bdfhkl", top("l"))):
        for ch in chars:
            if ref is not None:
                refs[ch] = ref
    no_baseline = set("gjpqyQ")
    fixed = []
    for ch, want in refs.items():
        g = pf.glyphs.get(ch)
        if g is None or not g.rows:
            continue
        before = (g.top, list(g.rows))
        bottom = g.top + len(g.rows) - 1
        if g.top == want - 1 and bottom == base - 1 and ch not in no_baseline:
            g.top += 1  # the whole glyph a row too high
        else:
            if g.top == want - 1 and len(g.rows) > 2:
                g.rows = [_merge(g.rows[0], g.rows[1])] + g.rows[2:]
                g.top += 1
            if ch not in no_baseline and g.top + len(g.rows) - 1 == base + 1 and len(g.rows) > 2:
                g.rows = g.rows[:-2] + [_merge(g.rows[-2], g.rows[-1])]
        if (g.top, g.rows) != before:
            fixed.append(ch)
    return fixed


def path_for(size: int, weight: str) -> Path:
    return pixelfont.path_for(fonts.inter(size, weight))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", action="store_true", help="add missing glyphs to existing files")
    ap.add_argument("--sheet", action="store_true", help="write PNG sheets into captures/")
    ap.add_argument("--align", action="store_true", help="put letters and digits on the common lines")
    args = ap.parse_args()
    if args.align:
        for path in sorted(pixelfont.PIXEL_DIR.glob("*.txt")):
            pf = pixelfont.load(path)
            fixed = align_heights(pf)
            path.write_text(pf.dumps(), encoding="utf-8")
            print(f"{path.name}: {''.join(fixed) or 'nothing to fix'}")
        return
    if not args.sheet and not CLOCK_PATH.exists():
        clock = clock_font()
        align_heights(clock)
        CLOCK_PATH.write_text(clock.dumps(), encoding="utf-8")
        print(f"{CLOCK_PATH.name}: written")
    for size, weight in SCREEN_FONTS:
        font = fonts.inter(size, weight)
        path = path_for(size, weight)
        if args.sheet:
            out = Path(__file__).resolve().parents[1] / "captures" / f"{path.stem}.png"
            out.parent.mkdir(exist_ok=True)
            pixelfont.load(path).sheet(CHARS).save(out)
            print(out)
            continue
        if path.exists() and not args.add:
            print(f"{path.name}: exists, skipped")
            continue
        ascent, descent = font.getmetrics()
        pf = pixelfont.load(path) if path.exists() else pixelfont.PixelFont(Path(font.path).stem, size, ascent, descent, {})
        added = [ch for ch in CHARS if ch not in pf.glyphs]
        for ch in added:
            pf.glyphs[ch] = rasterise(font, ch)
        align_heights(pf)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pf.dumps(), encoding="utf-8")
        print(f"{path.name}: {len(added)} glyphs added")


if __name__ == "__main__":
    main()
