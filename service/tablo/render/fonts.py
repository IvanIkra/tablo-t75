"""Inter text fonts and Material Design Icons glyphs."""

import json
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

ASSETS = Path(__file__).resolve().parents[2] / "assets"
_INTER = {
    "regular": "Inter-Regular.ttf",
    "medium": "Inter-Medium.ttf",
    "semibold": "Inter-SemiBold.ttf",
    "bold": "Inter-Bold.ttf",
}


@lru_cache(maxsize=None)
def inter(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / "fonts" / _INTER[weight]), size)


@lru_cache(maxsize=None)
def mdi_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / "mdi" / "materialdesignicons-webfont.ttf"), size)


@lru_cache(maxsize=1)
def _mdi_map() -> dict[str, int]:
    with open(ASSETS / "mdi" / "mdi-map.json", encoding="utf-8") as f:
        return json.load(f)


def mdi_char(name: str | None) -> str | None:
    """`mdi:lamp` -> the glyph character, or None if unknown."""
    if not name:
        return None
    code = _mdi_map().get(name.removeprefix("mdi:"))
    return chr(code) if code else None
