#include "link.h"

#include <ArduinoJson.h>
#include <WebSocketsClient.h>
#include <WiFi.h>

#include "buttons.h"
#include "screen.h"
#include "secrets.h"
#include "state.h"

// The WebSocket lives in its own task on core 0: on bad Wi-Fi a connect attempt or
// a 48 KB frame holds it for seconds, and the main loop (panel, buttons, clock) must
// not wait for that. Everything that touches the panel or the state still runs in
// the main loop: a received message is handed over in place (the library's buffer,
// no room for a copy) and the network task waits until it is handled; messages to
// the service go the other way through a queue.
static WebSocketsClient ws;
static const uint16_t BACKOFF_S[] = {1, 2, 4, 8, 16, 30};
static uint8_t backoffIdx = 0;
static uint32_t lastStatusMs = 0;
static volatile bool pauseAsked = false, paused = false;

struct Inbound {
  bool binary;
  const uint8_t *data;
  size_t len;
};
static QueueHandle_t inbox, outbox;  // Inbound, char * (malloc'd JSON)

// A frame is received straight into the screen's spare frame buffer
// (tools/patch_websockets.py): on bad Wi-Fi the TCP stack holds out-of-order pieces
// of it, and by the time the library asked for 48 KB the heap had no such block left
// and it dropped the link. Only the network task allocates; a valid base frame then
// becomes the screen's base in place, and the other buffer is the spare.
static SemaphoreHandle_t handled;
static volatile bool linkChanged = false;
static uint8_t *frameRx = nullptr;

void *ws_payload_alloc(size_t size) {
  if (size > 4096 && size <= HEADER + PAYLOAD + 1 && !frameRx) {
    frameRx = screen::receiveBuffer();
    return frameRx;
  }
  return malloc(size);
}

void ws_payload_free(void *p) {
  if (p == frameRx) frameRx = nullptr;
  else free(p);
}

// Network task only.
static bool sendNow(JsonDocument &doc) {
  String s;
  serializeJson(doc, s);
  return ws.sendTXT(s);
}

// Main loop: queued for the network task.
static bool post(JsonDocument &doc) {
  size_t n = measureJson(doc) + 1;
  char *s = (char *)malloc(n);
  if (!s) return false;
  serializeJson(doc, s, n);
  if (xQueueSend(outbox, &s, 0) != pdTRUE) {
    free(s);
    return false;
  }
  return true;
}

static void sendHello() {
  JsonDocument d;
  d["type"] = "hello";
  d["fw"] = FW_VERSION;
  d["notes"] = FW_NOTES;
  d["device"] = DEVICE_ID;
  if (st.haveBase) d["last_crc"] = st.baseCrc;
  else d["last_crc"] = nullptr;
  d["rssi"] = WiFi.RSSI();
  d["uptime_s"] = millis() / 1000;
  sendNow(d);
}

static void sendStatus() {
  JsonDocument d;
  d["type"] = "status";
  d["rssi"] = WiFi.RSSI();
  d["uptime_s"] = millis() / 1000;
  d["heap"] = heapFree();
  d["partials_since_full"] = screen::partialsSinceFull();
  d["ip"] = WiFi.localIP().toString();
  sendNow(d);
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
    buttons::settled(screen::setBase(payload));
    st.haveBase = true;
    st.baseCrc = crc;
    st.baseId = id;
    screen::present();
  }
  JsonDocument d;
  d["type"] = "frame_ack";
  d["frame_id"] = id;
  post(d);
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
  bool dark = c["theme"].is<const char *>() ? strcmp(c["theme"], "light") != 0 : cfg.dark;
  if (dark != cfg.dark) {
    cfg.dark = dark;
    screen::present(true);  // every pixel flips: a full refresh
  }
}

static void onText(const uint8_t *data, size_t len) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, data, len);
  if (err) {
    Serial.printf("link: bad message (%s), %u bytes, heap %u: %.60s\n", err.c_str(), (unsigned)len,
                  (unsigned)heapFree(), (const char *)data);
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
  } else if (!strcmp(type, "close_overlay")) {
    // The service took back what it showed (§5); endOverlay draws the base again.
    if (screen::overlayActive()) screen::endOverlay();
    return;
  } else if (!strcmp(type, "button_result")) {
    if (!(doc["ok"] | true)) Serial.printf("link: button failed: %s\n", doc["error"] | "?");
    buttons::result(doc["seq"] | 0u);
    return;  // buttons::loop redraws the tile
  }
  screen::present();
}

static void onEvent(WStype_t type, uint8_t *payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.printf("link: connected, heap %u, largest block %u, stack free: net %u, loop %u\n",
                    (unsigned)heapFree(), (unsigned)heapLargest(),
                    (unsigned)uxTaskGetStackHighWaterMark(nullptr),
                    (unsigned)uxTaskGetStackHighWaterMark(xTaskGetHandle("loopTask")));
      st.connected = true;
      backoffIdx = 0;
      ws.setReconnectInterval(BACKOFF_S[0] * 1000UL);
      sendHello();
      lastStatusMs = millis();
      linkChanged = true;
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
      linkChanged = true;
      break;
    }
    case WStype_TEXT:
    case WStype_BIN: {
      // The payload is only valid inside this callback: wait for the main loop.
      Inbound in{type == WStype_BIN, payload, len};
      xQueueSend(inbox, &in, portMAX_DELAY);
      xSemaphoreTake(handled, portMAX_DELAY);
      break;
    }
    default:
      break;
  }
}

static void netTask(void *) {
  for (;;) {
    if (pauseAsked) {
      if (!paused) {
        ws.disconnect();
        paused = true;
      }
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }
    ws.loop();
    char *s;
    while (xQueueReceive(outbox, &s, 0) == pdTRUE) {
      if (st.connected) ws.sendTXT(s);
      free(s);
    }
    if (millis() - lastStatusMs >= 60000) {
      lastStatusMs = millis();
      if (st.connected) sendStatus();
      Serial.printf("link: %s, heap %u, lowest %u, largest block %u, net stack free %u\n",
                    st.connected ? "up" : "down", (unsigned)heapFree(), (unsigned)heapLowest(),
                    (unsigned)heapLargest(), (unsigned)uxTaskGetStackHighWaterMark(nullptr));
    }
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

namespace svc {

void begin() {
  inbox = xQueueCreate(1, sizeof(Inbound));
  outbox = xQueueCreate(8, sizeof(char *));
  handled = xSemaphoreCreateBinary();
  // Token in the query: the browser emulator cannot set WebSocket headers (§3.1).
  // No subprotocol: the service offers none.
  ws.begin(SERVICE_HOST, SERVICE_PORT, "/ws?device=" DEVICE_ID "&token=" DEVICE_TOKEN, "");
  ws.onEvent(onEvent);
  ws.setReconnectInterval(BACKOFF_S[0] * 1000UL);
  // Ping every 20 s; three missed pongs (about a minute) and the link is dead.
  ws.enableHeartbeat(20000, 10000, 3);
  // Core 0 with the Wi-Fi stack; the Arduino loop runs on core 1.
  xTaskCreatePinnedToCore(netTask, "net", 7168, nullptr, 1, nullptr, 0);
}

void pause() {
  // Its TCP buffers go back to the heap, and no 48 KB frame comes in during the upload.
  // A message already on its way still needs the main loop, so keep handling them.
  pauseAsked = true;
  for (uint32_t t = millis(); !paused && millis() - t < 2000;) {
    loop();
    delay(5);
  }
}

void loop() {
  Inbound in;
  if (xQueueReceive(inbox, &in, 0) == pdTRUE) {
    if (in.binary) onFrame(in.data, in.len);
    else onText(in.data, in.len);
    xSemaphoreGive(handled);
  }
  if (linkChanged) {
    linkChanged = false;
    screen::present();
  }
}

bool sendButton(int id, const char *press, uint32_t seq, bool local) {
  if (!st.connected) return false;
  JsonDocument d;
  d["type"] = "button";
  d["id"] = id;
  d["press"] = press;
  d["seq"] = seq;
  if (local) d["local"] = true;
  return post(d);
}

void overlayClosed(const char *reason) {
  JsonDocument d;
  d["type"] = "overlay_closed";
  d["reason"] = reason;
  post(d);
}

}  // namespace svc
