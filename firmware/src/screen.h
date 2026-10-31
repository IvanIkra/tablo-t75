// The panel: last base frame, what is shown, partial update of what changed (§3.2, §3.4).
#pragma once
#include <stdint.h>

namespace screen {

void begin();
void loop();  // powers the panel down when idle

// Compose base frame + firmware zones and refresh the changed rectangle.
// full: full refresh (with flashing) instead of partial.
void present(bool full = false);

// Keep a new base frame; present() shows it. Returns the button tiles it changed, bit per tile.
uint8_t setBase(const uint8_t *payload);
// Where the next frame is received: the frame buffer that is not the base,
// HEADER + PAYLOAD + 1 bytes. setBase on a payload in it takes it over without a copy.
uint8_t *receiveBuffer();
void zonesChanged();                   // after a config with other zones

void showOverlay(const uint8_t *payload, uint16_t ttl_s);  // full-screen frame, ttl 0 = until a button (§5)
bool overlayActive();
bool overlayExpired();
void endOverlay();

void showDiag();  // the firmware's own diagnostics screen, diag_ttl_s (§5)
bool diagActive();
bool diagExpired();
void endDiag();

// Until the board restarts: nothing else is drawn, frames from the service wait.
// Always a partial update, never a full one (see present).
void showNotice(const char *title, const char *line1, const char *line2);

uint16_t partialsSinceFull();

}  // namespace screen
