#include "screen.h"

#include <Arduino.h>
#include <GxEPD2_BW.h>
#include <SPI.h>

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
static uint8_t *shown;                            // what the panel shows now
static Canvas clockZone, statusZone;

static bool overlay = false, diag = false;
static uint32_t overlayUntilMs = 0, diagUntilMs = 0;
static uint16_t partials = 0;
static bool powered = false;
static uint32_t lastRefreshMs = 0;

namespace screen {

void begin() {
  shown = (uint8_t *)calloc(PAYLOAD, 1);
  frames[1] = (uint8_t *)malloc(FRAME_BUF);
  if (!shown || !frames[1]) {
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

// The driver takes 1 = white; frames are 1 = black, hence invert = true.
// The whole screen goes black, then white, then the image: the driver's fast full
// update alone leaves traces of the old image on black areas.
static void refreshFull() {
  uint32_t t = millis();
  epd.writeScreenBuffer(0x00);
  epd.refresh(false);
  epd.writeScreenBuffer(0xFF);
  epd.refresh(false);
  epd.writeImageForFullRefresh(shown, 0, 0, W, H, true);
  epd.refresh(false);
  epd.writeImageAgain(shown, 0, 0, W, H, true);
  epd.powerOff();
  powered = false;
  partials = 0;
  lastRefreshMs = millis();
  Serial.printf("screen: full refresh %lu ms\n", lastRefreshMs - t);
}

static void refreshPart(int x, int y, int w, int h) {
  uint32_t t = millis();
  epd.writeImagePart(shown, x, y, W, H, x, y, w, h, true);
  epd.refresh(x, y, w, h);
  epd.writeImagePartAgain(shown, x, y, W, H, x, y, w, h, true);
  powered = true;
  partials++;
  lastRefreshMs = millis();
  Serial.printf("screen: partial %d,%d %dx%d %lu ms\n", x, y, w, h, lastRefreshMs - t);
}

// Rows of a new image are compared with what is shown byte by byte:
// the bounding box of changed bytes gets a partial update, a big change a full one.
struct Diff {
  int b0 = ROW, b1 = -1, y0 = H, y1 = -1;
  uint32_t cells = 0;

  void row(int y, const uint8_t *next) {
    uint8_t *s = shown + y * ROW;
    for (int b = 0; b < ROW; b++) {
      if (next[b] == s[b]) continue;
      cells++;
      if (b < b0) b0 = b;
      if (b > b1) b1 = b;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
    memcpy(s, next, ROW);
  }

  void commit(bool full) {
    if (!full && b1 < 0) return;
    if (!full && cells > cfg.bigChange * PAYLOAD) {
      Serial.printf("screen: big change, %lu of %d cells\n", (unsigned long)cells, PAYLOAD);
      full = true;
    }
    if (!full && partials >= cfg.maxPartials) full = true;
    if (full) refreshFull();
    else refreshPart(b0 * 8, y0, (b1 - b0 + 1) * 8, y1 - y0 + 1);
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

// Line by line: a whole-screen canvas would need another 48 KB block.
static void presentDiag(bool full) {
  Canvas line;
  int li = -1;
  Rect r{0, 0, 0, 0};
  Diff d;
  uint8_t row[ROW];
  for (int y = 0; y < H; y++) {
    while (li < DIAG_LINES && (li < 0 || y >= r.y + r.h)) {
      if (++li == DIAG_LINES) break;
      r = diagLine(li);
      line.resize(r.w, r.h);
      drawDiagLine(line, li);
    }
    memset(row, 0, ROW);
    if (li < DIAG_LINES) blitRow(row, line, r, y);
    d.row(y, row);
  }
  d.commit(full);
}

void present(bool full) {
  if (overlay) {
    // Nothing is drawn over a full-screen frame; a full refresh just cleans it.
    if (full) refreshFull();
    return;
  }
  if (diag) {
    presentDiag(full);
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
  overlayUntilMs = millis() + ttl_s * 1000UL;
  Diff d;
  for (int y = 0; y < H; y++) d.row(y, payload + y * ROW);
  d.commit(false);
}

bool overlayActive() { return overlay; }
bool overlayExpired() { return overlay && (int32_t)(millis() - overlayUntilMs) >= 0; }

void endOverlay() {
  overlay = false;
  present();
}

void showDiag() {
  diag = true;
  diagUntilMs = millis() + cfg.diagTtlS * 1000UL;
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
