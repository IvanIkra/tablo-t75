// Tablo T75 firmware (docs/software §10): shows frames from the service,
// draws the clock, date and status bar itself, keeps going without the service.
#include <Arduino.h>
#include <ArduinoOTA.h>
#include <Update.h>
#include <WiFi.h>

#include "buttons.h"
#include "link.h"
#include "screen.h"
#include "secrets.h"
#include "state.h"

// The loop needs about 3 KB; the rest of the default 8 KB is heap for the 48 KB frame block.
SET_LOOP_TASK_STACK_SIZE(6 * 1024);

static bool otaRunning = false;
static uint32_t restartAtMs = 0;
// A download from the service gives up after this long without a byte.
static const uint32_t OTA_STALL_MS = 30000;
static const uint32_t WIFI_RETRY_MS = 30000;
static uint32_t wifiTryMs = 0;  // when Wi-Fi went down or was last started over
static uint8_t wifiTries = 0;

static const char *otaError(ota_error_t e) {
  switch (e) {
    case OTA_AUTH_ERROR: return "auth";
    case OTA_BEGIN_ERROR: return "no room for it";
    case OTA_CONNECT_ERROR: return "no connection to the computer";
    case OTA_RECEIVE_ERROR: return "upload broke off";
    case OTA_END_ERROR: return "image check failed";
    default: return "unknown";
  }
}

static void otaBegan() {
  otaRunning = true;
  svc::pause();
  screen::showNotice("Updating firmware...", "Now " FW_VERSION, "The panel restarts by itself when it is done");
}

static void otaFailed(const char *why) {
  char line[64];
  snprintf(line, sizeof line, "Error: %s. Restarting in 10 s", why);
  screen::showNotice("Update failed", line, "Still " FW_VERSION);
  // The link is stopped and the frames wait: a restart brings everything back.
  restartAtMs = millis() + 10000;
}

static void startOta() {
  ArduinoOTA.setHostname("tablo");
  ArduinoOTA.setPassword(OTA_PASSWORD);
  // The default 1 s for each piece broke an upload off (error 3) on a Wi-Fi stall
  // or while a 48 KB frame came in over the WebSocket.
  ArduinoOTA.setTimeout(10000);
  ArduinoOTA.onStart([] {
    Serial.println("ota: start");
    otaBegan();
  });
  ArduinoOTA.onError([](ota_error_t e) {
    Serial.printf("ota: error %u\n", e);
    if (!otaRunning) return;  // a wrong password: nothing started, nothing to undo
    otaFailed(otaError(e));
  });
  ArduinoOTA.begin();
}

// §3.3: the service offered an image and the board downloads it itself. One TCP stream
// rides out the Wi-Fi stalls that broke espota off: it waits 10 s for each 1 KB piece.
// nullptr when the image is written and checked.
static const char *downloadFirmware(uint32_t size, const char *md5) {
  // A bare GET over WiFiClient: HTTPClient put 3 KB more code into IRAM, and the panel's
  // shown rows that no longer fit there took 4 KB of the heap.
  WiFiClient in;
  in.setTimeout(10000);  // for the status line and the headers
  if (!in.connect(SERVICE_HOST, SERVICE_PORT, 10000)) return "no connection to the service";
  in.print("GET /firmware.bin?token=" DEVICE_TOKEN " HTTP/1.0\r\nHost: " SERVICE_HOST "\r\n\r\n");
  String line = in.readStringUntil('\n');
  if (!line.startsWith("HTTP/1.1 200") && !line.startsWith("HTTP/1.0 200")) {
    Serial.printf("ota: GET /firmware.bin: %s\n", line.c_str());
    return line.length() ? "the service has no firmware" : "no connection to the service";
  }
  long length = -1;
  while ((line = in.readStringUntil('\n')).length() > 1) {
    line.toLowerCase();
    if (line.startsWith("content-length:")) length = line.substring(15).toInt();
  }
  if (length != (long)size) return "wrong size";
  if (!Update.begin(size)) return "no room for it";
  Update.setMD5(md5);
  uint8_t *buf = screen::receiveBuffer();  // the link is stopped: its frame buffer is free
  uint32_t got = 0, lastDataMs = millis(), lastLogMs = millis();
  while (got < size) {
    int n = in.available() ? in.read(buf, min<uint32_t>(4096, size - got)) : 0;
    if (n > 0) {
      if (Update.write(buf, n) != (size_t)n) break;
      got += n;
      lastDataMs = millis();
      if (millis() - lastLogMs >= 5000) {
        lastLogMs = millis();
        Serial.printf("ota: %lu of %lu\n", (unsigned long)got, (unsigned long)size);
      }
    } else if (!in.connected() || millis() - lastDataMs > OTA_STALL_MS) {
      break;
    } else {
      delay(2);
    }
  }
  in.stop();
  if (got < size) {
    bool flash = Update.hasError();
    Update.abort();
    return flash ? "flash write failed" : "download broke off";
  }
  if (!Update.end()) return "image check failed";
  return nullptr;
}

static void updateFromService() {
  uint32_t size = st.otaSize;
  st.otaSize = 0;
  Serial.printf("ota: from the service, %lu bytes\n", (unsigned long)size);
  otaBegan();
  uint32_t t = millis();
  const char *err = downloadFirmware(size, st.otaMd5);
  if (!err) {
    Serial.printf("ota: done in %lu s, restarting\n", (unsigned long)(millis() - t) / 1000);
    delay(100);
    ESP.restart();
  }
  Serial.printf("ota: failed: %s\n", err);
  otaFailed(err);
}

static void wifiStart() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname("tablo");
  WiFi.setSleep(false);  // USB power; a sleeping radio adds latency to every press
  // With a repeater or mesh under one name: join the loudest, not the first found.
  WiFi.setScanMethod(WIFI_ALL_CHANNEL_SCAN);
  WiFi.setSortMethod(WIFI_CONNECT_AP_BY_SIGNAL);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
}

// The core's own reconnect stalled now and then at -79 dBm and the panel stayed offline
// until a restart. Start over every 30 s, and every 5th time with the radio off and on.
// No restart: it would clear the shown frame while the router is simply off.
static void keepWifi() {
  if (millis() - wifiTryMs < WIFI_RETRY_MS) return;
  wifiTryMs = millis();
  wifiTries++;
  Serial.printf("wifi: still down, try %u\n", wifiTries);
  if (wifiTries % 5 == 0) {
    WiFi.mode(WIFI_OFF);
    delay(100);
    wifiStart();
  } else {
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
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

  wifiStart();
  wifiTryMs = millis();
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
    if (!wifi) {
      st.wifiDrops++;
      wifiTryMs = millis();
      wifiTries = 0;
    }
    Serial.printf("wifi: %s %s\n", wifi ? "up" : "down", wifi ? WiFi.localIP().toString().c_str() : "");
    if (wifi && !otaStarted) {
      startOta();
      otaStarted = true;
    }
    screen::present();
  }
  if (!wifi) keepWifi();
  if (otaStarted) ArduinoOTA.handle();
  if (st.otaSize && !otaRunning) updateFromService();
  if (restartAtMs && (int32_t)(millis() - restartAtMs) >= 0) ESP.restart();
  buttons::loop();
  svc::loop();
  if (millis() - lastTickMs >= 1000) {
    lastTickMs = millis();
    tick();
  }
  screen::loop();
}
