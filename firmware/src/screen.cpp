#include "screen.h"

#include <Arduino.h>
#include <GxEPD2_BW.h>

#include "canvas.h"
#include "state.h"
#include "zones.h"

// ESP32-L(C02) + DESPI-C02 wiring (checked on the panel). SPI: SCK 18, MOSI 23.
constexpr int PIN_CS = 27, PIN_DC = 14, PIN_RST = 12, PIN_BUSY = 13;
constexpr uint32_t POWER_OFF_IDLE_MS = 5000;

static GxEPD2_750_GDEY075T7 epd(PIN_CS, PIN_DC, PIN_RST, PIN_BUSY);

static uint8_t *base;   // last base frame, 1 = black
static uint8_t *shown;  // what the panel shows now
static Canvas clockZone, statusZone;

static bool overlay = false;
static uint32_t overlayUntilMs = 0;
static uint16_t partials = 0;
static bool powered = false;
static uint32_t lastRefreshMs = 0;

namespace screen {

void begin() {
  base = (uint8_t *)calloc(PAYLOAD, 1);
  shown = (uint8_t *)calloc(PAYLOAD, 1);
  if (!base || !shown) {
    Serial.println("screen: no memory for frame buffers");
    for (;;) delay(1000);
  }
  // 2 ms reset pulse for the DESPI-C02 reset circuit; no driver diagnostics on Serial.
  epd.init(0, true, 2, false);
  zonesChanged();
}

void zonesChanged() {
  clockZone.resize(cfg.clock.w, cfg.clock.h);
  statusZone.resize(cfg.status.w, cfg.status.h);
}

// The driver takes 1 = white; frames are 1 = black, hence invert = true.
static void refreshFull() {
  uint32_t t = millis();
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

void present(bool full) {
  if (overlay) {
    // Nothing is drawn over a full-screen frame; a full refresh just cleans it.
    if (full) refreshFull();
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
    d.row(y, row);
  }
  d.commit(full);
}

void setBase(const uint8_t *payload) { memcpy(base, payload, PAYLOAD); }

void showOverlay(const uint8_t *payload, uint16_t ttl_s) {
  overlay = true;
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

uint16_t partialsSinceFull() { return partials; }

void loop() {
  if (powered && millis() - lastRefreshMs > POWER_OFF_IDLE_MS) {
    epd.powerOff();
    powered = false;
  }
}

}  // namespace screen
