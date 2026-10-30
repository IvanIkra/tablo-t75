// The panel: last base frame, what is shown, partial update of what changed (§3.2, §3.4).
#pragma once
#include <stdint.h>

namespace screen {

void begin();
void loop();  // powers the panel down when idle

// Compose base frame + firmware zones and refresh the changed rectangle.
// full: full refresh (with flashing) instead of partial.
void present(bool full = false);

void setBase(const uint8_t *payload);  // keep a new base frame; present() shows it
void zonesChanged();                   // after a config with other zones

void showOverlay(const uint8_t *payload, uint16_t ttl_s);  // full-screen frame (§5)
bool overlayActive();
bool overlayExpired();
void endOverlay();

uint16_t partialsSinceFull();

}  // namespace screen
