#include "canvas.h"

#include <string.h>

void Canvas::resize(int w, int h) {
  w_ = w;
  h_ = h;
  stride_ = (w + 7) / 8;
  bits_.assign(stride_ * h, 0);
}

void Canvas::clear(bool black) { memset(bits_.data(), black ? 0xFF : 0, bits_.size()); }

void Canvas::set(int x, int y, bool black) {
  if (x < 0 || y < 0 || x >= w_ || y >= h_) return;
  uint8_t &b = bits_[y * stride_ + (x >> 3)];
  if (black) b |= 0x80 >> (x & 7);
  else b &= ~(0x80 >> (x & 7));
}

void Canvas::fillRect(int x, int y, int w, int h, bool black) {
  for (int yy = y; yy < y + h; yy++)
    for (int xx = x; xx < x + w; xx++) set(xx, yy, black);
}

const Glyph *findGlyph(const PixFont &f, uint32_t cp) {
  int lo = 0, hi = f.count - 1;
  while (lo <= hi) {
    int mid = (lo + hi) / 2;
    if (f.glyphs[mid].cp == cp) return &f.glyphs[mid];
    if (f.glyphs[mid].cp < cp) lo = mid + 1;
    else hi = mid - 1;
  }
  return nullptr;
}

static uint32_t nextCodePoint(const char *&s) {
  uint8_t c = *s++;
  if (c < 0x80) return c;
  int extra = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : 1;
  uint32_t cp = c & (0x3F >> extra);
  while (extra-- && (*s & 0xC0) == 0x80) cp = (cp << 6) | (*s++ & 0x3F);
  return cp;
}

int Canvas::glyph(const PixFont &f, int x, int baseline, uint32_t cp, bool black) {
  const Glyph *g = findGlyph(f, cp);
  if (!g) g = findGlyph(f, ' ');
  if (!g) return x;
  const uint8_t *bits = f.bits + g->offset;
  int gstride = (g->w + 7) / 8;
  int top = baseline - f.ascent + g->top;
  for (int r = 0; r < g->h; r++)
    for (int c = 0; c < g->w; c++)
      if (bits[r * gstride + (c >> 3)] & (0x80 >> (c & 7))) set(x + g->left + c, top + r, black);
  return x + g->advance;
}

int Canvas::text(const PixFont &f, int x, int baseline, const char *s, bool black) {
  while (*s) x = glyph(f, x, baseline, nextCodePoint(s), black);
  return x;
}

int Canvas::textWidth(const PixFont &f, const char *s) {
  int w = 0;
  while (*s) {
    const Glyph *g = findGlyph(f, nextCodePoint(s));
    if (!g) g = findGlyph(f, ' ');
    if (g) w += g->advance;
  }
  return w;
}
