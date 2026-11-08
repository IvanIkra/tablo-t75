# Tablo — software: Home Assistant integration (§8)

> Part of the software design, index in [`docs/README.md`](../README.md). Section numbers §N run through all the parts.

## 8. Home Assistant integration

A custom integration, [`ha-integration/custom_components/tablo`](../../ha-integration/README.md). HA sets up the panel: buttons, home, screen, the class feed link and the weather. Deadlines, news and grades are set up in infomaster's Mini App (infomaster decision 33); HA has no link to infomaster at all.

### 8.1 Link

- **Connecting:** the service address and the `api_token`. The integration takes the service's current config (`GET /api/config`), so nothing has to be entered again. Secrets (tokens) stay in the service's `.env`.
- **Integration → service:** the HTTP API (§6.4) with the `api_token`. Every "Configure" form sends the full config at once; the service validates it, and an error shows in the form. The config is sent again when HA starts and after the service answers again.
- **Service → HA:** the WebSocket API with a long-lived token: states, `call_service`, presses as the `tablo_button` event (`button`, `press`), changes as the `tablo_changed` event (`kind: status` when the board connects or disconnects and when the university app login changes per infomaster's status, `kind: messages` when the sticky message queue changes), and a sticky message closed with a button as the `tablo_message_dismissed` event (§5).
- **The integration** listens to `tablo_button` (device triggers) and `tablo_changed` (re-reads the state at once). It also polls the service once a minute, which catches missed events and the Wi-Fi signal.
- **The university app login has expired** (§7.2, `hseapp.login_needed` from infomaster's status): an HA notification with a link to the infomaster bot, `https://t.me/<bot>?start=hseapp`, once per change. The bot name is the "infomaster bot" field in the "Sources" form; without it the notification has no link.
- **Entries saved before the move to infomaster** (entry version 1.1) are migrated to 1.2 on load: `grades`, `hseapp`, `news`, `mail`, `subjects` are removed from the config, or the service would reject it for unknown keys.

### 8.2 Buttons 1–7

Settings → Devices → Tablo → "Configure" → pick a button. Separately for the **short** and the **long** press:

| Field | Options |
|---|---|
| Action | Toggle an entity · Run a script or scene · Show the Wi-Fi QR (networks, duration) · Show a message · Event only |
| Entity | A pick from the HA list |
| Icon (one per button) | The standard HA icon picker (`mdi:*`). Empty — the entity's icon |
| Tile highlight (one per button) | By default the state of the same entity. Can be another entity or "never" |

- Changes show on the screen at once.
- **Device triggers** "Tablo: button N, short / long" for any automation. They fire for any configured action, "event only" included. Button 8 publishes events too.

**Initial assignments** (the user changes them in HA):

| # | Icon | Short | Long |
|---|---|---|---|
| 1 | `mdi:power` | Script "all lights on" | Script "all lights off" |
| 2 | `mdi:ceiling-light` | `light.ceiling_light` | Solo: only this light |
| 3 | `mdi:lamp` | `light.desk_lamp` | Brightness cycle 100 → 40 → 10% |
| 4 | `mdi:desk` | `light.desk_light` | Solo |
| 5 | `mdi:led-strip-variant` | `light.desk_backlight` (Tuya, 1 m RGB strip, not addressable) | Colour or brightness cycle |
| 6 | `mdi:hanger` | `light.closet_light` | On, then off after 5 min |
| 7 | `mdi:wifi` | `switch.vpn_ap` | Wi-Fi QR: the main network + VPN, 20 s |
| 8 | `mdi:refresh` | *built in*: full refresh | *built in*: diagnostics for 30 s |

"Solo", "brightness cycle" and the timer are HA scripts. Templates are in [`ha-integration/scripts/tablo.yaml`](../../ha-integration/scripts/tablo.yaml): `all_lights_on`, `all_lights_off`, `leaving_home` (lights and the VPN access point, not on any button now), `solo_ceiling` and `solo_desk` (through a shared `solo_light`), `lamp_brightness_cycle` (100 → 40 → 10%), `backlight_color_cycle` (warm → red → green → blue → purple), `closet_5min`.

### 8.3 Other settings

Lists in the forms are multi-line fields, one entry per line, fields separated by `|`.

- **Wi-Fi networks** for the QR: `SSID | password | WPA | hidden` (WPA, WEP or nopass security; `hidden` only for a hidden network).
- **Sources:** infomaster's class feed link (`…/calendar/<CALENDAR_SECRET>/tablo.ics`), the weather coordinates and the infomaster bot name (for the link in the university app login notification; it is kept in the integration and never goes to the service). When the link or the coordinates change, the service polls the source at once. Everything else — the university app, the student name and the grade sheets, chats, the news lifetime, mail, the subject dictionary — is in infomaster's Mini App.
- **Home:** `label | HA template` rows, one per line, up to 5 rows (as many as the block holds). HA itself computes the value: the service subscribes to each template via `render_template` over the WebSocket and gets a new result whenever the entities inside the template change. An empty result means no row, so a row can show only while something is going on (`{% if … %}…{% endif %}`). Without a label (`| template`) the value starts at the left edge, like "21.4° · 42%". The label is everything up to the first `|` if there is no `{` in it; otherwise the whole line counts as a template. HA checks the template syntax when the form is saved, and a row with an error is not shown on screen. By default there are three rows (temperature and humidity, "lights N of M", the printer), in `service/config.yaml`; the service converts the old sensor, light and printer fields into these rows itself. Running scripts that wait are added above these rows by the service itself, with no setting (§7.6).
- **Screen:** `semester_start`, the time of the nightly full refresh, the font mode, the theme (dark by default, or light), the long-press threshold, the QR and message durations.

An empty button icon means the entity's icon from HA, and if it has none, its domain's icon (`light` → `mdi:lightbulb`).

### 8.4 Actions and entities

| Action | Parameters |
|---|---|
| `tablo.show_qr` | `networks`, `duration` (20 s) |
| `tablo.show_message` | `title`, `text`, `icon`, `duration` (30 s), `sticky` (stays until a press, §5) |
| `tablo.clear_messages` | — (clear the sticky messages) |
| `tablo.full_refresh` | — |
| `tablo.refresh_data` | `sources` (optional): `infomaster`, `ical`, `weather` |

Entities: a "connected" `binary_sensor`, a Wi-Fi signal `sensor`, a last-contact time `sensor` (both keep their value after the board disconnects), and a "Sticky messages" `sensor` — how many sticky messages are waiting, with their titles and times in the `messages` attribute. A "Theme" `select` (`dark` / `light`) — the panel theme for dashboards and automations: it sends the config to the service and saves it in the entry's options, like the "Screen" form.

The "Tablo · Study" / "Tablo · Personal" to-do lists and the LLM sensors are gone (infomaster decisions 34 and 40): own and hidden deadlines are in infomaster's Mini App, LLM usage is on its "LLM usage" screen. Entities left from them are removed in HA by hand after the integration update.
