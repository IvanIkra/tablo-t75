#include "buttons.h"

#include <Arduino.h>
#include <esp_timer.h>

#include "link.h"
#include "screen.h"
#include "state.h"

// GPIO of buttons 1–8 from the left, each switch to GND, internal pull-ups (§10).
// No external resistors: 0 is BOOT with R8 on the board (held at reset, the board
// waits for a flash), 19 is the bus MISO (the chips on it are kept deselected,
// see screen.cpp), 4 lights the board LED while pressed. GPIO12 is not used: on
// this board it is shorted to the display DC (14), a press there garbled the panel.
static const uint8_t PINS[8] = {0, 4, 19, 33, 32, 25, 22, 21};
constexpr uint32_t POLL_MS = 5, DEBOUNCE_MS = 20;
constexpr uint32_t RESULT_WAIT_MS = 12000;  // no button_result: drop the mark anyway (§4.2)
constexpr uint32_t OFFLINE_FLASH_MS = 1500;  // service down: flip the tile and back

// Polling runs on a system timer while the main loop is stuck in a panel refresh;
// edges keep their own time, so the press length is right however late it is handled.
// A timer, not a task of its own: a task's stack would come out of the heap that
// must keep one 48 KB block free for a frame.
struct Edge {
  uint8_t tile;
  bool down;
  uint32_t ms;
};
static QueueHandle_t edges;

struct Held {
  int8_t tile = -1;
  uint32_t downMs;
  bool armed;    // long press threshold passed: tile framed before release (§4.1)
  bool swallow;  // pressed over an overlay or diagnostics: only closes it (§5)
};
static Held held;

// A press waiting for the service. Each press before the answer flips the tile once
// more, and each new base frame that changes the tile takes one flip back (§4.2).
struct Pending {
  bool on = false;
  uint8_t flips = 0;
  uint32_t seq, untilMs;
};
static Pending pending[8];
static uint32_t seq = 0;
static bool dirty = false;

static void poll(void *) {
  static bool raw[8], state[8];
  static uint32_t since[8];
  uint32_t now = millis();
  for (int i = 0; i < 8; i++) {
    bool down = digitalRead(PINS[i]) == LOW;
    if (down != raw[i]) {
      raw[i] = down;
      since[i] = now;
    } else if (down != state[i] && now - since[i] >= DEBOUNCE_MS) {
      state[i] = down;
      Edge e{(uint8_t)i, down, since[i]};
      xQueueSend(edges, &e, 0);
    }
  }
}

static void release(uint8_t tile, uint32_t ms) {
  const char *press = ms - held.downMs >= cfg.longPressMs ? "long" : "short";
  bool swallow = held.swallow;
  held.tile = -1;
  int id = tile + 1;
  Serial.printf("button: %d %s, %lu ms\n", id, press, (unsigned long)(ms - held.downMs));

  if (swallow) {
    // Any button closes a full-screen screen and does nothing else (§5).
    if (screen::overlayActive()) {
      svc::overlayClosed("button");
      screen::endOverlay();
    } else {
      screen::endDiag();
    }
    return;
  }
  if (id == 8) {
    // Wired into the firmware; the service still hears it, and a short press asks it for a fresh frame.
    svc::sendButton(id, press, ++seq, true);
    if (press[0] == 's') screen::present(true);
    else screen::showDiag();
    return;
  }
  dirty = true;
  Pending &p = pending[tile];
  p.flips = p.on ? p.flips + 1 : 1;
  p.on = true;
  p.seq = ++seq;
  p.untilMs = millis() + (svc::sendButton(id, press, p.seq, false) ? RESULT_WAIT_MS : OFFLINE_FLASH_MS);
}

namespace buttons {

void begin() {
  for (uint8_t pin : PINS) pinMode(pin, INPUT_PULLUP);
  edges = xQueueCreate(16, sizeof(Edge));
  esp_timer_create_args_t args = {};
  args.callback = poll;
  args.name = "buttons";
  esp_timer_handle_t timer;
  esp_timer_create(&args, &timer);
  esp_timer_start_periodic(timer, POLL_MS * 1000);
}

void loop() {
  Edge e;
  while (xQueueReceive(edges, &e, 0) == pdTRUE) {
    if (e.down) {
      Serial.printf("button: GPIO %u down\n", PINS[e.tile]);
      if (held.tile >= 0) continue;  // one at a time
      held = {(int8_t)e.tile, e.ms, false, screen::overlayActive() || screen::diagActive()};
      // Draw the press now: when the loop was busy, the release is already queued and
      // would send first, so the tile would flip only together with the service's answer.
      if (!held.swallow) screen::present();
    } else if (e.tile == held.tile) {
      release(e.tile, e.ms);
    }
  }
  uint32_t now = millis();
  if (held.tile >= 0 && !held.armed && now - held.downMs >= cfg.longPressMs) {
    held.armed = true;
    dirty = !held.swallow;
  }
  for (Pending &p : pending) {
    if (p.on && (int32_t)(now - p.untilMs) >= 0) {
      p.on = false;
      dirty = true;
    }
  }
  if (dirty) {
    dirty = false;
    screen::present();
  }
}

void result(uint32_t s) {
  for (Pending &p : pending) {
    if (p.on && p.seq == s) {
      p.on = false;
      dirty = true;
    }
  }
}

void settled(uint8_t tileMask) {
  for (int i = 0; i < 8; i++) {
    Pending &p = pending[i];
    if (p.on && (tileMask & 1 << i)) {
      if (--p.flips == 0) p.on = false;
      dirty = true;
    }
  }
}

Mark mark(int tile) {
  bool flipped = pending[tile].on && pending[tile].flips % 2;
  if (held.tile == tile && !held.swallow) {
    if (held.armed) return FRAMED;
    return flipped ? NONE : INVERTED;
  }
  return flipped ? INVERTED : NONE;
}

}  // namespace buttons
