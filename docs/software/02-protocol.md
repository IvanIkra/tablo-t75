# Tablo — software: protocol, buttons, overlays (§3–5)

> Part of the software design, index in [`docs/README.md`](../README.md). Section numbers §N run through all the parts.

## 3. Board ↔ service protocol

### 3.1 Connection

- One WebSocket connection: `ws://<service>:8765/ws?device=<id>&token=<token>`. The token goes in the query rather than a header because the browser emulator cannot set headers on a WebSocket.
- Text messages are JSON with a `type` field. Binary messages are frames only (§3.2).
- WebSocket-level ping every 20 s. No traffic for 60 s means the connection is dead.
- Reconnects after pauses of 1, 2, 4, 8, 16, 30, 30… s.
- On connect the board sends `hello` with the CRC of its last frame. The service answers with `config`, `health` and, if the CRC does not match, the current frame (after a new firmware version a greeting comes first, §5).

### 3.2 Frame (binary message)

| Offset | Size | Field | Value |
|---|---|---|---|
| 0 | 4 | magic | `TBLF` |
| 4 | 1 | version | `1` |
| 5 | 1 | kind | `0` — base frame, `1` — full-screen (§5) |
| 6 | 2 | ttl_s | For full-screen: how many seconds to show it (LE u16), `0` — until a press (since fw-0.3). 0 for the base frame |
| 8 | 4 | frame_id | Monotonic frame number (LE u32) |
| 12 | 4 | crc32 | CRC32 of the payload |
| 16 | 2 | width | 800 |
| 18 | 2 | height | 480 |
| 20 | 48 000 | payload | Rows top to bottom, 100 bytes per row, the most significant bit is the leftmost pixel, **1 = black** |

- No compression: 48 KB over the local network takes a fraction of a second.
- The board keeps the last base frame, compares the new one with it row by row and does a **partial refresh** of just the rectangle that changed.
- If the display controller needs the opposite polarity, the firmware inverts on output. The protocol stays the same.
- **Dark theme** (`theme: dark` in `config`, the default): frames stay 1 = black, and the board inverts everything it sends to the panel — the frame, its own zones, diagnostics, the update screen; the emulator does the same. A theme change is a full refresh. In the dark theme `/frame.png` returns the picture already inverted, as on the panel.
- The service sends a new frame only if the CRC changed, and at most once every 2 s. The exception is a frame in reply to a button.

### 3.3 Messages

**Board → service**

| type | Fields | When |
|---|---|---|
| `hello` | `fw`, `notes` (what changed in this version, §5), `device`, `last_crc`, `rssi`, `uptime_s` | After connecting |
| `button` | `id` 1–8, `press` `short` / `long`, `seq`, `local` (for 8) | A press. Button 8 is sent too, but as an event: its action is built in |
| `overlay_closed` | `reason`: `button` / `ttl` | A full-screen screen closed |
| `status` | `rssi`, `uptime_s`, `heap`, `partials_since_full`, `ip` | Every 60 s |
| `frame_ack` | `frame_id` | A frame is shown |

**Service → board**

| type | Fields | When |
|---|---|---|
| `config` | `tz` (`MSK-3`), `ntp`, `semester_start`, `zones` (§2), `long_press_ms` (600), `full_refresh` (`at: "04:00"`, `max_partials`, `big_change` — not sent yet, the board and the emulator use 0.3), `offline_after_s` (120), `diag_ttl_s` (30), `theme` (`dark` / `light`, `dark` by default) | After `hello` and when settings change |
| `health` | `ha` (bool), `data` (bool: `false` while infomaster has not answered for over 10 min — the block data is stale, §11), `synced_at` (`HH:MM`) | Every 60 s and on change |
| `button_result` | `seq`, `ok`, `error` | The action succeeded or failed (§4.2) |
| `full_refresh` | — | Forced full refresh (an HA action) |
| `close_overlay` | — | Take the full-screen screen down: sticky messages were cleared from HA (§5). No `overlay_closed` is sent back |
| `ota` | `size`, `md5` | New firmware is uploaded (`PUT /api/firmware`): the board downloads `GET /firmware.bin?token=…` itself and installs it (§5, §10). Boards before fw-0.7 do not know this command |

### 3.4 Screen refresh

- **Partial** (0.44 s for a window, 0.62 s for the whole screen on the live panel): frame changes, the clock once a minute, button tiles.
- **Full** (2.3 s, with flashing): daily at `full_refresh.at` (04:00 by default), after `max_partials` partial refreshes in a row, on button 8, on the `full_refresh` command and on a **big change**: when more than `big_change` (0.3 by default) of the screen's eight-pixel cells change at once. That way a new screen (an overlay, or closing it) leaves no traces of the old one, while small changes go as partial refreshes. After a series of partial refreshes the live panel shows faint traces of the previous header; small updates leave almost nothing. `big_change` and `max_partials` will be tuned by experience.

---

## 4. Buttons

### 4.1 Layout

| Button | Short | Long (≥ 600 ms) | Configured |
|---|---|---|---|
| 1–7 | An action from HA | Its own action from HA | **In HA** (§8.2) |
| 8 | Full refresh and a request for a fresh frame | Diagnostics screen for 30 s | Built in |

- Once the long-press threshold passes, the board changes the tile at once (a frame instead of a fill), so it is clear a long press counted even before release.
- Debounce is 20 ms.

### 4.2 Instant feedback

1. Press → the board **at once** inverts the tile over the base frame (a local mark) and sends `button`.
2. The service runs the action in HA and waits for `state_changed` of the right entity. The timeout is 10 s: cloud Tuya can be slow.
3. Success → the service sends a new base frame with the real tile state, then `button_result ok`.
4. On `button_result` (or after 12 s with no answer) the board removes the local mark and redraws the tile from the base frame. If the command failed, the tile goes back to how it was.
5. Service unreachable → the board inverts the tile and turns it back after 1.5 s: you can see the press did not go through.
6. A second press before the answer flips the tile back at once, a third flips it again, and so on. Each new base frame that changes the tile takes one flip back, so the tile keeps showing the state the presses ask for; `button_result` for the last press removes the mark. The service runs toggles of one entity one after another, so two quick presses turn it on and off again instead of racing on the same old state.

---

## 5. Full-screen screens

A frame with `kind = 1` covers the whole screen. The board does not draw the clock, status or tiles over it.

- After `ttl_s` the board returns to the base frame **by itself**. So the screen never gets stuck, even if the service goes down mid-show. The exception is `ttl_s = 0` (a sticky message): only a button or `close_overlay` closes it.
- A new base frame that arrives while a full-screen screen is up is kept and shown afterwards.
- **Any press** closes the screen and does **not** run the button's action.
- There is enough memory: the base frame (48 KB) is kept apart from the screen buffer (48 KB).

| Screen | Drawn by | Triggered by | Default duration |
|---|---|---|---|
| **Wi-Fi QR** | Service | A button action, `tablo.show_qr` | 20 s, configurable |
| **Message** | Service | `tablo.show_message` | 30 s, configurable |
| **Sticky message** | Service | `tablo.show_message` with `sticky: true` | Until a press |
| **Diagnostics** | **Firmware** | Long press on 8 | 30 s |
| **Firmware update** | **Firmware** | OTA started / failed | Until restart |
| **Greeting after an update** | Service | The version number in `hello` changed | Until a press |

- **Wi-Fi QR:** one or more networks side by side (for two, ~360×360 px each), each with its name below. A string like `WIFI:T:WPA;S:<ssid>;P:<password>;;`. Networks are set in HA (§8.3).
- **Message:** a title, wrapped text, an optional MDI icon.
- **Sticky message** — for things that must be noticed: an urgent status, a note for the household. It looks different from a normal one: a black bar with the title and icon, a border around the edge, and at the bottom the time it was sent ("14:32", or "Oct 30, 14:32" if not today: no clock is drawn over a full-screen frame), "1 of 3" if several are waiting, and "Press any button to close".
  - The service keeps a **queue** (up to 20, in SQLite) and shows the oldest. A press closes it, and the service sends the next one at once. The sender is not shown: only the owner sends them.
  - A board restart, a dropped link or a service restart do not lose the message: after `hello` the service sends it again. A QR or a normal message is shown over a sticky one, and once it closes the sticky one comes back.
  - Closed with a button → the HA event `tablo_message_dismissed` (`title`, `text`, `sent_at`, `waiting`), which can drive a "read" mark. `tablo.clear_messages` clears the queue and takes the screen down (`close_overlay`).
  - Boards before fw-0.3 close a frame with `ttl_s = 0` at once (`overlay_closed` `ttl`). The service then does not send it again, to avoid a loop, and the message stays in the queue.
- **Firmware update (OTA):** two paths — `ota` from the service, where the board downloads the image itself (the main one, since fw-0.7), and espota from the dev machine (the fallback when there is no link to the service). When the upload starts, the board closes the WebSocket and stops the network task (the TCP buffers go back to the heap, and no 48 KB frame arrives mid-upload) and draws "Updating firmware..." with the current version — always as a partial refresh (0.8 s): espota waits only 10 s for the board to connect, and a full refresh after `max_partials` took 5.5 s of them. Success means a restart. An error shows "Update failed" with the reason and restarts after 10 s: the link is stopped, and the restart brings everything back. A wrong OTA password starts nothing and leaves the screen alone.
- **Greeting after an update:** the service remembers each board's version (`device.fw:<id>` in SQLite). When the number changes (the part before `+`; a rebuild of the same number from another commit does not count), right after `config` and `health`, before the base frame and sticky messages, comes a window with `ttl_s = 0` (a frame that arrives under the window is kept by the board and shown after it, so the greeting does not wait for an extra refresh): a large "Hello!" and "Tablo is on fw-0.5", and small "What's new" in the bottom left — `notes` from `hello` and "old → new". The new version is saved only once the window is closed with a button: after a restart or a dropped link it shows again. The note is `FW_NOTES` next to `FW_NUMBER` in `firmware/src/state.h`, written together with a new number.
- **Diagnostics:** IP, Wi-Fi signal, uptime, firmware version, free memory, link to the service, HA and infomaster (`data` from `health`), the time of the last frame and of the last sync (`synced_at` from `health`). LLM usage is not shown here: it lives in infomaster's Mini App. The board draws this screen because the information is needed exactly when the service does not answer.
