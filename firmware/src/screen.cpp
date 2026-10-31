#include "screen.h"

#include <Arduino.h>
#include <GxEPD2_BW.h>
#include <SPI.h>
#include <soc/soc.h>

#include "buttons.h"
#include "canvas.h"
#include "state.h"
#include "zones.h"

// ESP32-L(C02) + DESPI-C02 wiring (checked on the panel). SPI: SCK 18, MOSI 23.
// RST is not on GPIO12: the adapter holds it high at reset, the strap then
// sets 1.8 V flash and the board boot-loops with "flash read err".
constexpr int PIN_CS = 27, PIN_DC = 14, PIN_RST = 26, PIN_BUSY = 13;
// The font chip (CS GPIO15) and the SPI flash (CS GPIO2) share the bus and are not used:
// kept deselected, so neither drives MISO (GPIO19), which is a button.
constexpr int PIN_FONT_CS = 15, PIN_FLASH_CS = 2;
constexpr uint32_t POWER_OFF_IDLE_MS = 5000;

static GxEPD2_750_GDEY075T7 epd(PIN_CS, PIN_DC, PIN_RST, PIN_BUSY);

// Two whole messages (header + payload + the library's terminator): the base frame
// is in one, the next frame is received into the other (link.cpp), and a valid new
// base just swaps them. Both are taken at start: one heap block of 48 KB for a frame
// is not always there later on bad Wi-Fi. One is static, two do not fit in .bss.
constexpr size_t FRAME_BUF = HEADER + PAYLOAD + 1;
static uint8_t frame0[FRAME_BUF];
static uint8_t *frames[2] = {frame0, nullptr};
static int baseIdx = 0;  // frame0 is all zero at start: a white base
static const uint8_t *base = frame0 + HEADER;  // last base frame, 1 = black
// What the panel shows now, 1 = black. Most rows sit in IRAM: malloc cannot use it
// (32-bit access only), and with three 48 KB images in the ordinary heap Wi-Fi and the
// WebSocket had a few KB left, so messages and connects failed. Rows are only touched
// as words; the driver, which reads bytes, gets them through a band buffer.
static uint32_t *shownIram, *shownDram;
static int iramRows = 0;
constexpr int ROW_WORDS = ROW / 4;
constexpr int BAND = 16;  // rows per write to the driver
static uint32_t band[BAND * ROW_WORDS];

static uint32_t *shownRow(int y) {
  return y < iramRows ? shownIram + y * ROW_WORDS : shownDram + (y - iramRows) * ROW_WORDS;
}
static Canvas clockZone, statusZone;
// One diagnostics line at a time, its buffer taken at start: a std::vector that cannot
// grow aborts, so with the heap short for a moment long press 8 restarted the board.
static Canvas diagCanvas;

static bool overlay = false, overlayTimed = false, diag = false, notice = false;
static char noticeText[NOTICE_LINES][64];
static uint32_t overlayUntilMs = 0, diagUntilMs = 0;
static uint16_t partials = 0;
static bool powered = false;
static uint32_t lastRefreshMs = 0;

namespace screen {

void begin() {
  // These caps also match D/IRAM, which is ordinary DRAM seen from the I-bus: the heap
  // tries pure IRAM first, so shrink until the block lands below the D/IRAM alias.
  for (iramRows = H; iramRows > 0; iramRows -= 8) {
    shownIram = (uint32_t *)heap_caps_malloc(iramRows * ROW, MALLOC_CAP_32BIT | MALLOC_CAP_EXEC);
    if (shownIram && (uintptr_t)shownIram < SOC_DIRAM_IRAM_LOW) break;
    heap_caps_free(shownIram);
    shownIram = nullptr;
  }
  for (int i = 0; i < iramRows * ROW_WORDS; i++) shownIram[i] = 0;
  shownDram = (uint32_t *)calloc((H - iramRows) * ROW + 4, 1);  // +4: never a zero-size block
  Serial.printf("screen: %d of %d shown rows in IRAM\n", iramRows, H);
  frames[1] = (uint8_t *)malloc(FRAME_BUF);
  diagCanvas.resize(W, DIAG_LINE_MAX_H);  // the tallest line; smaller ones reuse the buffer
  if (!shownDram || !frames[1]) {
    Serial.println("screen: no memory for frame buffers");
    for (;;) delay(1000);
  }
  pinMode(PIN_FONT_CS, OUTPUT);
  digitalWrite(PIN_FONT_CS, HIGH);
  pinMode(PIN_FLASH_CS, OUTPUT);
  digitalWrite(PIN_FLASH_CS, HIGH);
  // No MISO: the panel is write-only. GxEPD2's own SPI.begin() is a no-op after this one.
  SPI.begin(18, -1, 23, -1);
  // 2 ms reset pulse for the DESPI-C02 reset circuit; no driver diagnostics on Serial.
  epd.init(0, true, 2, false);
  zonesChanged();
}

void zonesChanged() {
  clockZone.resize(cfg.clock.w, cfg.clock.h);
  statusZone.resize(cfg.status.w, cfg.status.h);
}

// Rows y.. of what is shown into the band buffer, which the driver can read by bytes.
static int fillBand(int y, int n) {
  for (int r = 0; r < n; r++) {
    const uint32_t *s = shownRow(y + r);
    for (int i = 0; i < ROW_WORDS; i++) band[r * ROW_WORDS + i] = s[i];
  }
  return n;
}

// The driver takes 1 = white; frames are 1 = black, hence invert = true, and false in
// the dark theme, where the panel shows the frame inverted.
// clean: the whole screen goes black, then white, then the image. The driver's fast
// full update alone leaves traces on black areas, but the cycle takes 5 s instead of 2:
// only for a full refresh asked for (button 8, night, HA, start) and after maxPartials.
static void refreshFull(bool clean) {
  uint32_t t = millis();
  if (clean) {
    epd.writeScreenBuffer(0x00);
    epd.refresh(false);
    epd.writeScreenBuffer(0xFF);
    epd.refresh(false);
  }
  for (int y = 0; y < H; y += BAND) {
    int n = fillBand(y, min(BAND, H - y));
    epd.writeImageForFullRefresh((const uint8_t *)band, 0, y, W, n, !cfg.dark);
  }
  epd.refresh(false);
  epd.powerOff();  // writeImageAgain is a no-op in this driver
  powered = false;
  partials = 0;
  lastRefreshMs = millis();
  Serial.printf("screen: full refresh%s %lu ms\n", clean ? ", clean" : "", lastRefreshMs - t);
}

static void refreshPart(int x, int y, int w, int h) {
  uint32_t t = millis();
  for (int by = y; by < y + h; by += BAND) {
    int n = fillBand(by, min(BAND, y + h - by));
    epd.writeImagePart((const uint8_t *)band, x, 0, W, n, x, by, w, n, !cfg.dark);
  }
  epd.refresh(x, y, w, h);  // writeImagePartAgain is a no-op in this driver
  powered = true;
  partials++;
  lastRefreshMs = millis();
  Serial.printf("screen: partial %d,%d %dx%d %lu ms\n", x, y, w, h, lastRefreshMs - t);
}

// Rows of a new image are compared with what is shown byte by byte (read as words):
// the bounding box of changed bytes gets a partial update, a big change a full one.
struct Diff {
  int b0 = ROW, b1 = -1, y0 = H, y1 = -1;
  uint32_t cells = 0;

  void row(int y, const uint8_t *next) {
    uint32_t *s = shownRow(y);
    for (int i = 0; i < ROW_WORDS; i++) {
      uint32_t n;
      memcpy(&n, next + 4 * i, 4);
      uint32_t diff = n ^ s[i];
      if (!diff) continue;
      for (int k = 0; k < 4; k++) {
        if (!(diff >> (8 * k) & 0xFF)) continue;  // little endian: byte k of the word is next[4i + k]
        int b = 4 * i + k;
        cells++;
        if (b < b0) b0 = b;
        if (b > b1) b1 = b;
      }
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
      s[i] = n;
    }
  }

  void commit(bool full) {
    if (!full && b1 < 0) return;
    if (!full && partials >= cfg.maxPartials) full = true;
    if (full) {
      refreshFull(true);
    } else if (cells > cfg.bigChange * PAYLOAD) {
      Serial.printf("screen: big change, %lu of %d cells\n", (unsigned long)cells, PAYLOAD);
      refreshFull(false);
    } else {
      refreshPart(b0 * 8, y0, (b1 - b0 + 1) * 8, y1 - y0 + 1);
    }
  }
};

static void blitRow(uint8_t *row, const Canvas &c, const Rect &r, int y) {
  if (y < r.y || y >= r.y + r.h) return;
  int cy = y - r.y;
  for (int cx = 0; cx < r.w; cx++) {
    int x = r.x + cx;
    if (x < 0 || x >= W) continue;
    uint8_t m = 0x80 >> (x & 7);
    if (c.get(cx, cy)) row[x >> 3] |= m;
    else row[x >> 3] &= ~m;
  }
}

static Rect tileRect(int i) {
  const Rect &b = cfg.buttons;
  return {(int16_t)(b.x + i * cfg.tileWidth), (int16_t)(b.y + 2), cfg.tileWidth, (int16_t)(b.h - 2)};
}

static void spanRow(uint8_t *row, int x0, int x1, bool invert) {
  for (int x = max(x0, 0); x < min(x1, W); x++) {
    uint8_t m = 0x80 >> (x & 7);
    if (invert) row[x >> 3] ^= m;
    else row[x >> 3] |= m;
  }
}

// A pressed tile is inverted; once the long press threshold passes, it is a 4 px
// black frame around the base picture instead (§4.1, as the emulator draws it).
static void markRow(uint8_t *row, int y) {
  for (int i = 0; i < 8; i++) {
    buttons::Mark m = buttons::mark(i);
    if (m == buttons::NONE) continue;
    Rect r = tileRect(i);
    if (y < r.y || y >= r.y + r.h) continue;
    if (m == buttons::INVERTED) {
      spanRow(row, r.x, r.x + r.w, true);
    } else if (y < r.y + 4 || y >= r.y + r.h - 4) {
      spanRow(row, r.x, r.x + r.w, false);
    } else {
      spanRow(row, r.x, r.x + 4, false);
      spanRow(row, r.x + r.w - 4, r.x + r.w, false);
    }
  }
}

static void drawNotice(Canvas &c, int i) { drawNoticeLine(c, i, noticeText[i]); }

// Diagnostics and notices, line by line: a whole-screen canvas would need another 48 KB block.
static void presentLines(int lines, void (*draw)(Canvas &, int), bool full) {
  Canvas &line = diagCanvas;
  int li = -1;
  Rect r{0, 0, 0, 0};
  Diff d;
  uint8_t row[ROW];
  for (int y = 0; y < H; y++) {
    while (li < lines && (li < 0 || y >= r.y + r.h)) {
      if (++li == lines) break;
      r = diagLine(li);
      line.resize(r.w, r.h);
      draw(line, li);
    }
    memset(row, 0, ROW);
    if (li < lines) blitRow(row, line, r, y);
    d.row(y, row);
  }
  d.commit(full);
}

void present(bool full) {
  if (notice) {
    presentLines(NOTICE_LINES, drawNotice, full);
    return;
  }
  if (overlay) {
    // Nothing is drawn over a full-screen frame; a full refresh just cleans it.
    if (full) refreshFull(true);
    return;
  }
  if (diag) {
    presentLines(DIAG_LINES, drawDiagLine, full);
    return;
  }
  drawClockZone(clockZone);
  drawStatusZone(statusZone);
  Diff d;
  uint8_t row[ROW];
  for (int y = 0; y < H; y++) {
    memcpy(row, base + y * ROW, ROW);
    blitRow(row, clockZone, cfg.clock, y);
    blitRow(row, statusZone, cfg.status, y);
    markRow(row, y);
    d.row(y, row);
  }
  d.commit(full);
}

uint8_t setBase(const uint8_t *payload) {
  uint8_t changed = 0;
  for (int i = 0; i < 8; i++) {
    Rect r = tileRect(i);
    int b0 = max(r.x, (int16_t)0) >> 3, b1 = (min(r.x + r.w, W) + 7) >> 3;
    for (int y = max(r.y, (int16_t)0); y < min(r.y + r.h, H) && !(changed & 1 << i); y++) {
      if (memcmp(base + y * ROW + b0, payload + y * ROW + b0, b1 - b0)) changed |= 1 << i;
    }
  }
  uint8_t *spare = frames[1 - baseIdx];
  if (payload != spare + HEADER) memcpy(spare + HEADER, payload, PAYLOAD);
  baseIdx = 1 - baseIdx;
  base = spare + HEADER;
  return changed;
}

uint8_t *receiveBuffer() { return frames[1 - baseIdx]; }

void showOverlay(const uint8_t *payload, uint16_t ttl_s) {
  overlay = true;
  diag = false;  // a screen from the service replaces the local one
  overlayTimed = ttl_s != 0;  // 0: stays until a button closes it (§5)
  overlayUntilMs = millis() + ttl_s * 1000UL;
  Diff d;
  for (int y = 0; y < H; y++) d.row(y, payload + y * ROW);
  d.commit(false);
}

bool overlayActive() { return overlay; }
bool overlayExpired() { return overlay && overlayTimed && (int32_t)(millis() - overlayUntilMs) >= 0; }

void endOverlay() {
  overlay = false;
  present();
}

void showDiag() {
  diag = true;
  diagUntilMs = millis() + cfg.diagTtlS * 1000UL;
  present();
}

void showNotice(const char *title, const char *line1, const char *line2) {
  notice = true;
  overlay = diag = false;
  strlcpy(noticeText[0], title, sizeof noticeText[0]);
  strlcpy(noticeText[1], line1, sizeof noticeText[1]);
  strlcpy(noticeText[2], line2, sizeof noticeText[2]);
  present();
}

bool diagActive() { return diag; }
bool diagExpired() { return diag && (int32_t)(millis() - diagUntilMs) >= 0; }

void endDiag() {
  diag = false;
  present();
}

uint16_t partialsSinceFull() { return partials; }

void loop() {
  if (powered && millis() - lastRefreshMs > POWER_OFF_IDLE_MS) {
    epd.powerOff();
    powered = false;
  }
}

}  // namespace screen
