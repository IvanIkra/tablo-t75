// Shared state: the config from the service (§3.3), its health, the link.
#pragma once
#include <esp_heap_caps.h>
#include <stdint.h>
#include <time.h>

// Raise FW_NUMBER for each change worth naming; the commit is added at build time
// (tools/fw_version.py), so two builds of one number still differ.
#define FW_NUMBER "0.8"
// What FW_NUMBER changed, a line or two in English: the service shows it on the panel
// after an update (§5). Write it together with a new FW_NUMBER.
#define FW_NOTES "Wi-Fi comes back by itself on a weak signal; diagnostics count the drops."
#ifndef FW_COMMIT
#define FW_COMMIT "nogit"
#endif
#define FW_VERSION "fw-" FW_NUMBER "+" FW_COMMIT

constexpr int W = 800, H = 480, ROW = W / 8;
constexpr int PAYLOAD = ROW * H;  // 48 000
constexpr int HEADER = 20;

// The heap malloc can use. ESP.getFreeHeap() also counts IRAM, which takes only 32-bit
// access: it showed 40 KB more than there was while malloc already failed.
inline uint32_t heapFree() { return heap_caps_get_free_size(MALLOC_CAP_8BIT); }
inline uint32_t heapLowest() { return heap_caps_get_minimum_free_size(MALLOC_CAP_8BIT); }
inline uint32_t heapLargest() { return heap_caps_get_largest_free_block(MALLOC_CAP_8BIT); }

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
  // White on black: frames stay 1 = black, only what goes to the panel is inverted,
  // so the board's own zones and screens follow without drawing anything else.
  bool dark = true;
};

struct Health {
  bool ha = false;
  bool data = true;
  char syncedAt[6] = "";
};

struct State {
  bool wifiUp = false;
  uint16_t wifiDrops = 0;  // since the start, for the diagnostics
  bool connected = false;
  uint32_t offlineSinceMs = 0;
  bool haveBase = false;
  uint32_t baseCrc = 0;
  uint32_t baseId = 0;
  uint32_t lastFrameMs = 0;
  // An `ota` from the service, for the main loop: the image is at /firmware.bin (§3.3).
  uint32_t otaSize = 0;
  char otaMd5[33] = "";
};

extern Config cfg;
extern Health health;
extern State st;

bool localTimeNow(struct tm &t);  // false until NTP has set the clock
bool serviceOffline();
uint32_t frameCrc32(const uint8_t *data, size_t len);  // same as zlib.crc32
