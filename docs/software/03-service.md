# Tablo — software: the service (§6)

> Part of the software design, index in [`docs/README.md`](../README.md). Section numbers §N run through all the parts.

## 6. The service

### 6.1 Stack

- **Python 3.12, a single asyncio process.**
- `aiohttp` — the web server, the WebSocket to the board, the HTTP client, the WebSocket to HA. One library for everything, rather than FastAPI + uvicorn + httpx.
- `Pillow` — layout, no browser.
- `icalendar`, `segno` (QR), `jinja2` (home templates in the fake HA).
- There is no LLM in Tablo: infomaster calls Haiku.
- **SQLite** (`data/tablo.db`) — a single `kv` table: infomaster's last good answers, the class feed, the weather. The old tables (grades, news, own deadlines, the subject dictionary, LLM runs) are unused since the move to infomaster: they stay in an existing database for a rollback, and the database can be started fresh. The service deletes the keys of the old sources (`hseapp.auth` — the university app token, sheet layouts, university labels) at startup.

### 6.2 Internal structure

```
sources ──▶ store (SQLite + memory) ──▶ screen model ──▶ renderer (Pillow) ──▶ frame ──▶ board
   ▲ each on its own schedule              (plain data)                         1 bit, CRC
   └ HA events (instant)
```

- **Sources** are independent modules with a "fetch data, return typed records" interface: infomaster (every minute), the `tablo.ics` feed (every 10 min), weather (every 15 min). Each has its own schedule, cache and "last success" flag. A failure in one does not break the others: the block shows the last known data.
- The **screen model** is plain data without pixels: "3 deadlines", "an 8-hour forecast", "tile 3 is on". It can be compared and tested.
- The **renderer** turns the model into a picture. The layout is coordinates in one file.
- The model changed → render after 2 s → if the CRC differs, the frame goes to the board.

### 6.3 Layout

- The main screen text (Inter 15 and 16 medium, 16 and 30 semibold) uses pixel fonts: text files in `assets/fonts/pixel/`, one block of `#`/`.` per glyph. `tools/pixel_fonts.py` made them from a monochrome FreeType render, thickening 1 px vertical stems to 2 px. Letters and digits sit on shared lines (cap height, digit height, x-height, baseline), the one-pixel overshoot of round shapes is cut, `--align`. The rest was fixed by hand: hyphen, quotes, m, e, w, r. A line has a single baseline, whereas PIL shifted the line by a pixel depending on the letters. A glyph missing from the file is drawn with FreeType. Overlays (20–34 px) are drawn by FreeType: `fontmode="1"` or a greyscale render with a threshold (`font_mode`). The final choice is made on the live panel. The same bitmap fonts serve the firmware for the clock and the status line (§10).
- Text that does not fit is cut with "…".
- The weather icons are custom, single-line, as in the mockup: sun, moon, cloud, cloud with 1–3 strokes, snow, thunderstorm, fog. They are drawn pixel by pixel (`render/pixels.py`): 44 px for the current weather with a 3 px line and 22 px for the hourly row with a 2 px line. Vector lines break up in 1 bit at these sizes. All the icons with precipitation share one cloud, so the clouds in the row line up.
- The fixed 15 px block icons (book, person, cap, envelope, paper plane, calendar, house, exclamation mark) are pixel art too, shaped after the MDI icons. Icons without a pixel version come from the MDI font.
- **Button icons are Material Design Icons** from the MDI font file. A name like `mdi:lamp` is mapped to a font glyph via `meta.json`, at 32 px. These are the same names HA uses.
- An urgent deadline is highlighted by inversion.

### 6.4 HTTP API

For the HA integration and debugging, on the same port 8765. Requests that change state, and `GET /api/config`, need `Authorization: Bearer <api_token>`.

| Method and path | What it does |
|---|---|
| `GET /api/config` | The current config without secrets: the integration reads it when it connects (§8.1) |
| `PUT /api/config` | The integration sends the full config (§8) |
| `POST /api/overlay/qr` | `{networks: [...], duration_s}` |
| `POST /api/overlay/message` | `{title, text, icon, duration_s, sticky}`: `sticky: true` queues a sticky message, `duration_s` is not needed (§5) |
| `DELETE /api/messages` | Clear the sticky messages and take the screen off the board; answers `{cleared: N}` |
| `POST /api/refresh` | `{full: bool, refetch: bool, sources: [...]}`: `refetch` polls the sources now (`infomaster`, `ical`, `weather`; all of them without `sources`). infomaster has no "refresh now": Tablo just reads its API again |
| `GET /api/status` | The state of the board, the sources, HA; `firmware` — the uploaded firmware (`size`, `md5`) or `null`; `messages` — sticky messages (`title`, `sent_at`, oldest first); `infomaster` — `ok_at`, `error`, `down`; `hseapp` — the university app status from infomaster and `login_needed` for the HA notification (§8.4) |
| `GET /frame.png` | The current frame as a picture |
| `PUT /api/firmware` | The body is `firmware.bin` (up to 1.9 MB, first byte `0xE9`). The service keeps the image in memory and sends `ota` to the connected board (§3.3); with no board, 409. Answers `{size, devices}`. From the dev machine: `pio run -e service -t upload` (§10) |
| `GET /firmware.bin?token=<device_token>` | The board downloads the uploaded image with its token; 404 if none is uploaded |
| `GET /emu` | The emulator (§9) |

### 6.5 Configuration

- **Secrets** live in the service's `.env`: the HA token, the infomaster token (`TABLO_INFOMASTER_TOKEN`), the board and API tokens (§13).
- **Content settings** (buttons, the class feed link, weather, home, screen) live in HA. The deadline, news and grade settings live in infomaster's Mini App. The integration sends them via `PUT /api/config`.
- The service keeps the last config it received on disk and runs on it even when HA is unreachable.
- Without the integration (stages 1–6) the same config is read from `config.yaml`. The schema is the same.

### 6.6 LLM runs

Removed together with Haiku: infomaster counts and shows LLM usage (the "LLM usage" screen in its Mini App). Neither Tablo nor HA has it.
