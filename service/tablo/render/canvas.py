"""Drawing helpers shared by the main screen and overlays, plus 1-bit packing."""

from PIL import Image, ImageDraw, ImageFont

from .. import protocol
from . import fonts, pixelfont, pixels

BLACK = 0
WHITE = 255


class Canvas:
    """Greyscale canvas that ends up as a pure black/white frame.

    Sizes with a pixel font (§6.3) are drawn from it. For the rest, font_mode "aliased" draws text
    with FreeType's monochrome rasteriser; "threshold" draws antialiased text and cuts it at 50% at the end.
    """

    def __init__(self, font_mode: str = "aliased"):
        self.image = Image.new("L", (protocol.WIDTH, protocol.HEIGHT), WHITE)
        self.draw = ImageDraw.Draw(self.image)
        if font_mode == "aliased":
            self.draw.fontmode = "1"

    def text(self, xy, text, font, fill=BLACK, anchor="la"):
        pf = pixelfont.lookup(font)
        if pf is not None:
            pixelfont.draw(self.draw, pf, font, xy, text, fill, anchor)
        else:
            self.draw.text(xy, text, font=font, fill=fill, anchor=anchor)

    def width(self, text: str, font: ImageFont.FreeTypeFont) -> float:
        pf = pixelfont.lookup(font)
        if pf is not None:
            return pixelfont.width(pf, font, text)
        return self.draw.textlength(text, font=font)

    def fit(self, text: str, font, max_width: float) -> str:
        """Cut text with an ellipsis so it fits max_width."""
        if self.width(text, font) <= max_width:
            return text
        while text and self.width(text + "…", font) > max_width:
            text = text[:-1]
        return text.rstrip() + "…"

    def wrap(self, text: str, font, max_width: float, max_lines: int) -> list[str]:
        """Word-wrap into at most max_lines; the last line gets "…" if text was cut."""
        lines, line = [], ""
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if line and self.width(candidate, font) > max_width:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        if len(lines) > max_lines:
            # Append the next line's text so fit() is forced to cut and add the ellipsis.
            lines = lines[: max_lines - 1] + [lines[max_lines - 1] + " " + lines[max_lines] + " …"]
        return [self.fit(l, font, max_width) for l in lines]

    def icon(self, name: str | None, cx: float, cy: float, size: int, fill=BLACK) -> None:
        """A hand-drawn pixel icon if there is one at this size, else the MDI glyph."""
        if size == pixels.ICON and pixels.icon(self.draw, name, cx, cy, fill):
            return
        char = fonts.mdi_char(name)
        if char:
            self.draw.text((cx, cy), char, font=fonts.mdi_font(size), fill=fill, anchor="mm")

    def rect(self, x, y, w, h, fill=None, outline=None, width=1):
        self.draw.rectangle((x, y, x + w - 1, y + h - 1), fill=fill, outline=outline, width=width)

    def hline(self, x0, x1, y, width=2):
        self.draw.rectangle((x0, y, x1 - 1, y + width - 1), fill=BLACK)

    def vline(self, x, y0, y1, width=2):
        self.draw.rectangle((x, y0, x + width - 1, y1 - 1), fill=BLACK)

    def clear(self, rect) -> None:
        x, y, w, h = rect
        self.rect(x, y, w, h, fill=WHITE)

    def to_bw(self) -> Image.Image:
        """Pure black/white image (mode "1"), no dithering."""
        bw = self.image.point(lambda v: WHITE if v >= 128 else BLACK)
        return bw.convert("1", dither=Image.Dither.NONE)


def pack(bw: Image.Image) -> bytes:
    """Mode "1" image -> frame payload: MSB = leftmost pixel, 1 = black (§3.2)."""
    if bw.mode != "1" or bw.size != (protocol.WIDTH, protocol.HEIGHT):
        raise ValueError("expected an 800x480 mode '1' image")
    # Pillow packs 1 = white; the protocol wants 1 = black.
    raw = bw.tobytes()
    return (int.from_bytes(raw, "big") ^ ((1 << (8 * len(raw))) - 1)).to_bytes(len(raw), "big")


def unpack(payload: bytes) -> Image.Image:
    """Frame payload -> mode "1" image; used by /frame.png and tests."""
    inverted = (int.from_bytes(payload, "big") ^ ((1 << (8 * len(payload))) - 1)).to_bytes(len(payload), "big")
    return Image.frombytes("1", (protocol.WIDTH, protocol.HEIGHT), inverted)
