// WebSocket link to the service (§3.1, §3.3).
#pragma once

namespace svc {

void begin();
void loop();
void overlayClosed(const char *reason);  // "button" / "ttl"

}  // namespace svc
