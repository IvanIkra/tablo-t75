// Tablo T75 firmware (tablo-software.md §10): shows frames from the service,
// draws the clock, date and status bar itself, keeps going without the service.
#include <Arduino.h>
#include <ArduinoOTA.h>
#include <WiFi.h>

#include "buttons.h"
#include "link.h"
#include "screen.h"
#include "secrets.h"
#include "state.h"

// The loop needs about 3 KB; the rest of the default 8 KB is heap for the 48 KB frame block.
SET_LOOP_TASK_STACK_SIZE(6 * 1024);

static void startOta() {
  ArduinoOTA.setHostname("tablo");
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([] { Serial.println("ota: start"); });
  ArduinoOTA.onError([](ota_error_t e) { Serial.printf("ota: error %u\n", e); });
  ArduinoOTA.begin();
}

// Once a second: the clock minute, the offline bar, overlay ttl, the nightly full refresh.
static void tick() {
  static int lastMinute = -2;
  static int lastFullYday = -1;
  static bool lastOffline = false;

  if (screen::overlayExpired()) {
    svc::overlayClosed("ttl");
    screen::endOverlay();
    return;
  }
  if (screen::diagExpired()) {
    screen::endDiag();
    return;
  }
  struct tm t;
  bool known = localTimeNow(t);
  int minute = known ? t.tm_hour * 60 + t.tm_min : -1;
  bool offline = serviceOffline();
  if (minute != lastMinute) {
    lastMinute = minute;
    char hhmm[6] = "";
    if (known) snprintf(hhmm, sizeof hhmm, "%02d:%02d", t.tm_hour, t.tm_min);
    if (known && !strcmp(hhmm, cfg.fullAt) && t.tm_yday != lastFullYday) {
      lastFullYday = t.tm_yday;
      screen::present(true);
    } else {
      screen::present();
    }
  } else if (offline != lastOffline) {
    screen::present();
  }
  lastOffline = offline;
}

void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.printf("\nTablo %s\n", FW_VERSION);
  st.offlineSinceMs = millis();

  screen::begin();
  screen::present(true);
  buttons::begin();

  WiFi.mode(WIFI_STA);
  WiFi.setHostname("tablo");
  WiFi.setSleep(false);  // USB power; a sleeping radio adds latency to every press
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTzTime(cfg.tz, cfg.ntp);
  svc::begin();
  Serial.printf("heap after start: %lu, largest block %lu\n", (unsigned long)heapFree(),
                (unsigned long)heapLargest());
}

void loop() {
  static bool otaStarted = false;
  static uint32_t lastTickMs = 0;

  bool wifi = WiFi.status() == WL_CONNECTED;
  if (wifi != st.wifiUp) {
    st.wifiUp = wifi;
    Serial.printf("wifi: %s %s\n", wifi ? "up" : "down", wifi ? WiFi.localIP().toString().c_str() : "");
    if (wifi && !otaStarted) {
      startOta();
      otaStarted = true;
    }
    screen::present();
  }
  if (otaStarted) ArduinoOTA.handle();
  buttons::loop();
  svc::loop();
  if (millis() - lastTickMs >= 1000) {
    lastTickMs = millis();
    tick();
  }
  screen::loop();
}
