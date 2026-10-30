#include "state.h"

#include <Arduino.h>

Config cfg;
Health health;
State st;

bool localTimeNow(struct tm &t) {
  time_t now = time(nullptr);
  if (now < 1700000000) return false;
  localtime_r(&now, &t);
  return true;
}

bool serviceOffline() {
  return !st.connected && millis() - st.offlineSinceMs > cfg.offlineAfterS * 1000UL;
}

uint32_t frameCrc32(const uint8_t *data, size_t len) {
  static uint32_t table[256];
  if (!table[1]) {
    for (uint32_t n = 0; n < 256; n++) {
      uint32_t c = n;
      for (int k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >> 1) : c >> 1;
      table[n] = c;
    }
  }
  uint32_t c = 0xFFFFFFFF;
  for (size_t i = 0; i < len; i++) c = table[(c ^ data[i]) & 0xFF] ^ (c >> 8);
  return c ^ 0xFFFFFFFF;
}
