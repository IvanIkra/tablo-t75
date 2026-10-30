// A 1-bit drawing surface, 1 = black, rows MSB-first: the frame payload format (§3.2).
#pragma once
#include <stdint.h>
#include <vector>

#include "pixfont.h"

class Canvas {
 public:
  Canvas() = default;
  Canvas(int w, int h) { resize(w, h); }
  void resize(int w, int h);

  int width() const { return w_; }
  int height() const { return h_; }
  int stride() const { return stride_; }
  const uint8_t *row(int y) const { return &bits_[y * stride_]; }
  bool get(int x, int y) const { return bits_[y * stride_ + (x >> 3)] & (0x80 >> (x & 7)); }

  void clear(bool black = false);
  void set(int x, int y, bool black);
  void fillRect(int x, int y, int w, int h, bool black);

  // UTF-8 text; x is the pen, baseline the y of the baseline. Returns the pen after the text.
  int text(const PixFont &f, int x, int baseline, const char *s, bool black = true);
  static int textWidth(const PixFont &f, const char *s);
  // One glyph by code point (icons). Returns the pen after it.
  int glyph(const PixFont &f, int x, int baseline, uint32_t cp, bool black = true);

 private:
  int w_ = 0, h_ = 0, stride_ = 0;
  std::vector<uint8_t> bits_;
};

const Glyph *findGlyph(const PixFont &f, uint32_t cp);
