// Pixel fonts and icons as tables (generated into assets.cpp by tools/gen_assets.py).
#pragma once
#include <stdint.h>

struct Glyph {
  uint32_t cp;      // Unicode code point
  uint32_t offset;  // into the font's bits; rows of (w + 7) / 8 bytes, MSB is the left pixel
  uint8_t w, h;
  int8_t left;      // from the pen
  int8_t top;       // from baseline - ascent
  uint8_t advance;
};

struct PixFont {
  int8_t ascent, descent;
  uint16_t count;
  const Glyph *glyphs;  // sorted by cp
  const uint8_t *bits;
};
