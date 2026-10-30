// Shared state: the config from the service (§3.3), its health, the link.
#pragma once
#include <stdint.h>
#include <time.h>

#define FW_VERSION "fw-0.1"

constexpr int W = 800, H = 480, ROW = W / 8;
constexpr int PAYLOAD = ROW * H;  // 48 000
constexpr int HEADER = 20;

struct Rect {
  int16_t x, y, w, h;
};

// Defaults until the first `config` arrives; the same as the emulator's.
struct Config {
  char tz[48] = "MSK-3";
  char ntp[64] = "pool.ntp.org";
  int16_t semYear = 2026, semMonth = 9, semDay = 1;
  Rect clock{0, 0, 184, 100};
  Rect status{600, 0, 200, 24};
  Rect buttons{0, 428, 800, 52};
  int16_t tileWidth = 100;
  uint16_t longPressMs = 600;
  char fullAt[6] = "04:00";
  uint16_t maxPartials = 200;
  // Full refresh instead of partial when this share of 8-pixel cells changes at once:
  // a new screen leaves ghosts after a partial update, small changes do not.
  float bigChange = 0.30f;
  uint16_t offlineAfterS = 120;
  uint16_t diagTtlS = 30;
};

struct Health {
  bool ha = false;
  bool data = true;
  char syncedAt[6] = "";
};

struct State {
  bool wifiUp = false;
  bool connected = false;
  uint32_t offlineSinceMs = 0;
  bool haveBase = false;
  uint32_t baseCrc = 0;
  uint32_t baseId = 0;
  uint32_t lastFrameMs = 0;
};

extern Config cfg;
extern Health health;
extern State st;

bool localTimeNow(struct tm &t);  // false until NTP has set the clock
bool serviceOffline();
uint32_t frameCrc32(const uint8_t *data, size_t len);  // same as zlib.crc32
