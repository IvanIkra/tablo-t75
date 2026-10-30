#include "link.h"

#include <ArduinoJson.h>
#include <WebSocketsClient.h>
#include <WiFi.h>

#include "screen.h"
#include "secrets.h"
#include "state.h"

static WebSocketsClient ws;
static const uint16_t BACKOFF_S[] = {1, 2, 4, 8, 16, 30};
static uint8_t backoffIdx = 0;
static uint32_t lastStatusMs = 0;

static void send(JsonDocument &doc) {
  String s;
  serializeJson(doc, s);
  ws.sendTXT(s);
}

static void sendHello() {
  JsonDocument d;
  d["type"] = "hello";
  d["fw"] = FW_VERSION;
  d["device"] = DEVICE_ID;
  if (st.haveBase) d["last_crc"] = st.baseCrc;
  else d["last_crc"] = nullptr;
  d["rssi"] = WiFi.RSSI();
  d["uptime_s"] = millis() / 1000;
  send(d);
}

static void sendStatus() {
  JsonDocument d;
  d["type"] = "status";
  d["rssi"] = WiFi.RSSI();
  d["uptime_s"] = millis() / 1000;
  d["heap"] = ESP.getFreeHeap();
  d["partials_since_full"] = screen::partialsSinceFull();
  d["ip"] = WiFi.localIP().toString();
  send(d);
}

static uint32_t le32(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
static uint16_t le16(const uint8_t *p) { return p[0] | p[1] << 8; }

static void onFrame(const uint8_t *data, size_t len) {
  if (len != HEADER + PAYLOAD || memcmp(data, "TBLF", 4) != 0 || data[4] != 1 ||
      le16(data + 16) != W || le16(data + 18) != H) {
    Serial.printf("link: bad frame, %u bytes\n", (unsigned)len);
    return;
  }
  uint8_t kind = data[5];
  uint16_t ttl = le16(data + 6);
  uint32_t id = le32(data + 8), crc = le32(data + 12);
  const uint8_t *payload = data + HEADER;
  if (frameCrc32(payload, PAYLOAD) != crc) {
    Serial.printf("link: frame %lu crc mismatch\n", (unsigned long)id);
    return;
  }
  Serial.printf("link: frame #%lu %s\n", (unsigned long)id, kind ? "overlay" : "base");
  st.lastFrameMs = millis();
  if (kind == 1) {
    screen::showOverlay(payload, ttl);
  } else {
    // During an overlay the new base waits and is shown when it closes (§5).
    screen::setBase(payload);
    st.haveBase = true;
    st.baseCrc = crc;
    st.baseId = id;
    screen::present();
  }
  JsonDocument d;
  d["type"] = "frame_ack";
  d["frame_id"] = id;
  send(d);
}

static void readRect(JsonVariantConst v, Rect &r) {
  JsonArrayConst a = v.as<JsonArrayConst>();
  if (a.size() == 4) r = {a[0].as<int16_t>(), a[1].as<int16_t>(), a[2].as<int16_t>(), a[3].as<int16_t>()};
}

static void applyConfig(JsonObjectConst c) {
  bool tzChanged = false;
  if (c["tz"].is<const char *>() && strcmp(cfg.tz, c["tz"]) != 0) {
    strlcpy(cfg.tz, c["tz"], sizeof cfg.tz);
    tzChanged = true;
  }
  if (c["ntp"].is<const char *>() && strcmp(cfg.ntp, c["ntp"]) != 0) {
    strlcpy(cfg.ntp, c["ntp"], sizeof cfg.ntp);
    tzChanged = true;
  }
  if (tzChanged) configTzTime(cfg.tz, cfg.ntp);
  if (c["semester_start"].is<const char *>()) {
    int y, m, d;
    if (sscanf(c["semester_start"], "%d-%d-%d", &y, &m, &d) == 3) {
      cfg.semYear = y;
      cfg.semMonth = m;
      cfg.semDay = d;
    }
  }
  JsonObjectConst z = c["zones"];
  if (z) {
    readRect(z["clock"], cfg.clock);
    readRect(z["status"], cfg.status);
    readRect(z["buttons"], cfg.buttons);
    cfg.tileWidth = z["tile_width"] | cfg.tileWidth;
  }
  cfg.longPressMs = c["long_press_ms"] | cfg.longPressMs;
  JsonObjectConst fr = c["full_refresh"];
  if (fr) {
    if (fr["at"].is<const char *>()) strlcpy(cfg.fullAt, fr["at"], sizeof cfg.fullAt);
    cfg.maxPartials = fr["max_partials"] | cfg.maxPartials;
    cfg.bigChange = fr["big_change"] | cfg.bigChange;
  }
  cfg.offlineAfterS = c["offline_after_s"] | cfg.offlineAfterS;
  cfg.diagTtlS = c["diag_ttl_s"] | cfg.diagTtlS;
  screen::zonesChanged();
}

static void onText(const uint8_t *data, size_t len) {
  JsonDocument doc;
  if (deserializeJson(doc, data, len)) {
    Serial.println("link: bad message");
    return;
  }
  const char *type = doc["type"] | "";
  Serial.printf("link: <- %s\n", type);
  if (!strcmp(type, "config")) {
    applyConfig(doc.as<JsonObjectConst>());
  } else if (!strcmp(type, "health")) {
    health.ha = doc["ha"] | false;
    health.data = doc["data"] | true;
    strlcpy(health.syncedAt, doc["synced_at"] | "", sizeof health.syncedAt);
  } else if (!strcmp(type, "full_refresh")) {
    screen::present(true);
    return;
  }
  // button_result: with the buttons, next step.
  screen::present();
}

static void onEvent(WStype_t type, uint8_t *payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.println("link: connected");
      st.connected = true;
      backoffIdx = 0;
      ws.setReconnectInterval(BACKOFF_S[0] * 1000UL);
      sendHello();
      lastStatusMs = millis();
      screen::present();
      break;
    case WStype_DISCONNECTED: {
      if (st.connected) {
        Serial.println("link: disconnected");
        st.offlineSinceMs = millis();
      }
      st.connected = false;
      // Reconnect after 1, 2, 4, 8, 16, 30, 30… s (§3.1).
      uint16_t delayS = BACKOFF_S[min<int>(backoffIdx, sizeof BACKOFF_S / sizeof *BACKOFF_S - 1)];
      if (backoffIdx < 255) backoffIdx++;
      ws.setReconnectInterval(delayS * 1000UL);
      screen::present();
      break;
    }
    case WStype_TEXT:
      onText(payload, len);
      break;
    case WStype_BIN:
      onFrame(payload, len);
      break;
    default:
      break;
  }
}

namespace svc {

void begin() {
  // Token in the query: the browser emulator cannot set WebSocket headers (§3.1).
  // No subprotocol: the service offers none.
  ws.begin(SERVICE_HOST, SERVICE_PORT, "/ws?device=" DEVICE_ID "&token=" DEVICE_TOKEN, "");
  ws.onEvent(onEvent);
  ws.setReconnectInterval(BACKOFF_S[0] * 1000UL);
  // Ping every 20 s; three missed pongs (about a minute) and the link is dead.
  ws.enableHeartbeat(20000, 10000, 3);
}

void loop() {
  ws.loop();
  if (st.connected && millis() - lastStatusMs >= 60000) {
    lastStatusMs = millis();
    sendStatus();
  }
}

void overlayClosed(const char *reason) {
  JsonDocument d;
  d["type"] = "overlay_closed";
  d["reason"] = reason;
  send(d);
}

}  // namespace svc
