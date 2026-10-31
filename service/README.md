# Tablo service

The Tablo T75 service: it takes data from infomaster and Open-Meteo, draws an 800×480 1-bit frame and keeps a WebSocket to the board. The design and the protocol are in [`../docs/README.md`](../docs/README.md).

Demo data for the blocks (`tablo/stub.py`) is switched on with toggles in the emulator; without it the blocks show only real data.

## Running

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

```bash
.venv/bin/python -m tablo --config config.yaml
```

The emulator: <http://localhost:8765/emu>. Buttons work with the mouse or keys 1–8, holding ≥ 600 ms is a long press. The board token can be passed in the address: `/emu?token=…`.

Tests:

```bash
.venv/bin/python -m pytest -q
```

## Sources

Personal settings go in `config.local.yaml` (not in git, layered over `config.yaml`), secrets in `.env` (see [`.env.example`](.env.example)). State lives in `data/tablo.db`.

- **Deadlines, news, grades** come from infomaster (§7.1): `infomaster.url` (`http://infomaster:8081` by default, the `infomaster` docker network), the token is infomaster's `API_TOKEN`, in `.env` as `TABLO_INFOMASTER_TOKEN`. The settings of these blocks (the university app, sheets, chats, mail, the dictionary, own deadlines) are in infomaster's Mini App.
- **Classes** come from infomaster's feed `http://infomaster:8081/calendar/<CALENDAR_SECRET>/tablo.ics`: `ical.url` in `config.local.yaml` or in the HA "Sources" form.
- **Weather:** Open-Meteo, no key, the `weather` section.
- **Home:** a long-lived HA token (Profile → Security → "Long-lived access tokens") in `.env` as `TABLO_HA_TOKEN`, the address in `ha.url` or `TABLO_HA_URL`. The Home block is HA template rows in the `home.rows` section (§8.3), edited in the integration's form; check the Moonraker entity names after installing that integration. Untick *fake HA* in the emulator to see the real home. Scripts for long presses are in [`../ha-integration/scripts/tablo.yaml`](../ha-integration/scripts/tablo.yaml), to paste into HA's `scripts.yaml`.

On the dev machine infomaster is not reachable by the name `infomaster`: for the emulator with live data, point `infomaster.url` and `ical.url` in `config.local.yaml` at an address where its API is reachable (for example through `ssh -L`).

## What is where

| File | What |
|---|---|
| `tablo/protocol.py` | The frame format (§3.2) and the firmware zones |
| `tablo/config.py` | The config schema: `config.yaml` or `PUT /api/config` from the HA integration; `to_dict` for `GET /api/config` |
| `tablo/hub.py` | The WebSocket to the board, frames, button actions, full-screen screens |
| `tablo/app.py` | The HTTP API (§6.4), serving the emulator |
| `tablo/model.py`, `tablo/builder.py` | The screen model and building it from the sources |
| `tablo/render/` | Layout (Pillow), pixel icons (`pixels.py`) and fonts (`pixelfont.py`), QR and messages, packing into 1 bit |
| `tablo/ha.py` | The HA WebSocket client (states, `call_service`, `tablo_button`) and an in-memory fake HA: 5 lights, a VPN access point, a sensor, a printer; Tuya answers with a 2 s delay |
| `tablo/sources/` | Sources: `infomaster.py` (deadlines, news, grades and status from infomaster), `ical.py` (classes from `tablo.ics`), `weather.py` (Open-Meteo) |
| `tablo/store.py` | SQLite: the sources' last good answers |
| `tablo/stub.py` | Demo data for the blocks |
| `emulator/` | The board emulator: the same logic as the firmware |
| `assets/` | Inter fonts (OFL) and Material Design Icons (Pictogrammers Free License); `fonts/pixel/` — pixel versions of Inter for the screen, edited by hand |
| `tools/pixel_fonts.py` | Makes the pixel fonts from Inter (only the missing ones, without overwriting edits) and sheets for review |

## HTTP API

Requests that change state need the `Authorization: Bearer <api_token>` header (`dev-api-token` in `config.yaml`).

```bash
curl -X POST localhost:8765/api/overlay/message -H 'Authorization: Bearer dev-api-token' -d '{"title":"Hi","text":"Hello from curl","duration_s":10}'
# stays until a press, queued; DELETE /api/messages takes them all down
curl -X POST localhost:8765/api/overlay/message -H 'Authorization: Bearer dev-api-token' -d '{"title":"Back at 9","sticky":true}'
```

`GET /frame.png` is the current frame, `GET /api/status` the state of the board and the frame, and the sticky messages. The rest is for the HA integration, listed in §6.4.

## Font mode

`display.font_mode` in the config: `aliased` (FreeType's monochrome rasteriser) or `threshold` (antialiasing with a 50% threshold). To be chosen on the live panel.
