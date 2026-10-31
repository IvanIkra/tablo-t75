# Tablo T75

A 7.5″ e-ink wall panel (800×480, black & white) that shows the time, weather,
deadlines, news, grades and class schedule, with eight physical buttons wired to
Home Assistant. USB-C powered, meant to run around the clock.

The design principle is **smart server, dumb device**. A Python service renders
every frame with Pillow and streams it to the board over WebSocket; the ESP32
just displays the frame, draws its own clock and status line, and reports button
presses. All the data gathering, layout and logic live on the server, so the
firmware stays tiny and the panel never has to think.

![panel](presentation/r3/tablo-hero-en.png)

## How it works

```
data sources ──► Python service ──► 48 000-byte 1-bit frame ──► WebSocket ──► ESP32 ──► e-ink panel
  (weather,        (asyncio,            (TBLF header,                              (partial refresh
   Home Assistant,  Pillow, SQLite)      1 = black)                                 by diff, own clock)
   infomaster)
```

- **Frame** — 800×480, 1 bit per pixel, 48 000 bytes, `TBLF` header. The board
  does a partial refresh by diffing against the frame it already shows.
- **Buttons** — 1–7 are configured in Home Assistant (toggle a light, run a
  script, show a Wi-Fi QR…); button 8 is fixed to full refresh / diagnostics.
- **Full-screen overlays** — Wi-Fi QR, one-off and sticky messages (a queue that
  waits for a button), and a "what's new" greeting after a firmware update.
- **Dark theme** by default: frames stay `1 = black` and the board inverts the
  whole picture, its own clock and status included.

## Repository layout

| Path | What |
|---|---|
| [`service/`](service/) | The Python service — app, hub, protocol, config, store, renderer and data sources — plus a browser emulator of the board and the test suite. |
| [`firmware/`](firmware/) | ESP32 firmware (PlatformIO + Arduino): frame buffers and diffing, the on-board clock/status/diagnostics, buttons, and over-the-air updates. |
| [`ha-integration/`](ha-integration/) | A Home Assistant custom component: config forms for buttons, Wi-Fi, sources and screen, device triggers, `tablo.*` services and entities. |
| [`cad/`](cad/) | The enclosure, modelled in OpenSCAD, with exported STLs and preview renders. |
| [`docs/`](docs/) | The software design contract, split by area (architecture, protocol, service, sources, HA, firmware, deploy, plan), and the [product and hardware](docs/hardware.md) description. |
| [`presentation/`](presentation/) | Product renders and the project presentation. |

## Tech stack

- **Service** — Python 3.12, a single asyncio process, `aiohttp`, `Pillow`, SQLite.
- **Firmware** — ESP32, PlatformIO + Arduino, WebSocket link in its own task,
  partial e-ink refresh, OTA.
- **Home Assistant** — a custom integration that configures the panel and feeds
  it live home state.

External data (deadlines, news, grades, the class feed) comes from a companion
service over its own API and an iCal feed; weather comes from Open-Meteo. Secrets
live only in `.env` and in Home Assistant, never in the repository.

## Running the service

```bash
cd service
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m tablo --config config.yaml
```

Then open <http://localhost:8765/emu>: the emulator renders the board in a
browser, buttons included (mouse or keys 1–8), so the whole panel can be developed
without the hardware. Without a Home Assistant token the service uses a built-in
fake home. See [`service/README.md`](service/README.md) for details.

## Status

The hardware is built and running: a live panel in a 3D-printed enclosure shows
frames, clock, status and the eight buttons, with diagnostics, OTA updates and a
post-update greeting. Firmware is at fw-0.7.

## License

[MIT](LICENSE).
