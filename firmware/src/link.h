// WebSocket link to the service (§3.1, §3.3).
#pragma once
#include <stdint.h>

namespace svc {

void begin();
void loop();
void overlayClosed(const char *reason);  // "button" / "ttl"
// false when the service is not connected: the press did not go anywhere.
bool sendButton(int id, const char *press, uint32_t seq, bool local);

}  // namespace svc
