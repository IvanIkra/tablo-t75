# Tablo — software: repository layout, plan, open questions (§14–16)

> Part of the software design, index in [`docs/README.md`](../README.md). Section numbers §N run through all the parts.

## 14. Repository layout

```
tablo-t75/
├── README.md
├── docs/
│   ├── README.md             software design index (this design)
│   ├── hardware.md           product and hardware
│   └── software/             the design, part by part
├── cad/                      enclosure (OpenSCAD, STL, previews)
├── presentation/             presentation and renders
├── service/                  the service
│   ├── tablo/
│   │   ├── app.py            startup, scheduling, HTTP and WebSocket
│   │   ├── protocol.py       messages and the frame format
│   │   ├── config.py         config schema (YAML or HA)
│   │   ├── store.py          SQLite
│   │   ├── model.py          screen model
│   │   ├── render/           layout, fonts, icons, full-screen screens
│   │   ├── sources/          infomaster (deadlines, news, grades, status), ical (the tablo.ics feed), weather
│   │   └── ha.py             WebSocket to HA and the fake HA
│   ├── emulator/             the emulator page (HTML + JS)
│   ├── assets/               Inter, MDI, weather icons
│   ├── tests/                fictional fixtures and reference frames
│   ├── Dockerfile
│   ├── compose.yaml
│   └── .env.example
├── ha-integration/
│   └── custom_components/tablo/
└── firmware/                 PlatformIO
```

---

## 15. Work plan

| # | Stage | Result | Needed from the owner |
|---|---|---|---|
| 1 | **Skeleton and emulator** — done 18.10, [`service/`](../../service/README.md) | Protocol, frame, rendering on stubs, an emulator with buttons; buttons from `config.yaml` | — |
| 2 | **Grades** — done 18.10 | Sheets → Haiku layout → log → the Grades block | Anthropic key |
| 3 | **Deadlines** — done 18.10 | The university app module: token refresh, short English titles from Haiku, *HSE login needed*, a `/hseapp` login page | — |
| 4 | **Classes** — done 18.10 | Timetable iCal with ETag, a shared subject dictionary (classes and deadlines), the "today or the nearest day" rule, *Midterm* from iCal into deadlines with duplicates merged | — |
| 5 | **News** — done 18.10 | t.me/s, IMAP, Haiku parsing, study deadlines (the timetable is left alone) | A mail app password |
| 6 | **Weather and home** — done 18.10, tested live with HA | Open-Meteo, the HA subscription, tile states, button actions, the Moonraker integration in HA for the printer, HA scripts for long presses | A long-lived HA token, Moonraker via HACS, scripts in HA |
| 7 | **HA integration** — done 18.10, tested live (HA 2026.4.4, the service still on the dev machine), [`ha-integration/`](../../ha-integration/README.md) | Button and source settings, triggers, `tablo.*`, QR and messages, the "Tablo · Study" and "Tablo · Personal" to-do lists | Create scripts in HA |
| 8 | **Deployment** — the service in Docker on the server since 18.10, §12 | Docker on the `server`, memory measured | ssh access |
| 9 | **Firmware** — since 30.10, nearly done: a live panel in its enclosure, fw-0.7 (§10) | Frames and partial refresh, clock and status, 8 buttons, diagnostics, OTA with an update screen (through the service, espota as the fallback), a greeting after a new version. Left: tune `big_change` and `max_partials` | — |
| 10 | **Move to infomaster** — done 21.10 (§12) | The infomaster source (API and `tablo.ics`), an "infomaster unreachable" icon, optional events marked; the university app, mail, Telegram, Haiku, grades, the dictionary, the to-do lists and the LLM sensors removed from Tablo | Run infomaster, the token and the feed link |

After each stage the result is visible in the emulator.

Outside the plan, 31.10: sticky messages (§5) — `tablo.show_message` with `sticky`, until a press, a queue, `tablo.clear_messages`, a sensor and the `tablo_message_dismissed` event in HA.

---

## 16. Open questions

Settled on 18.10: overdue deadlines, hiding wrong ones and own deadlines, logging in to the university app again (tested live in Safari), "lights N of M", the backlight, the printer, mail over IMAP — the answers are in §7.2, §7.5, §7.6, §8.2, §8.4.

Left, settled along the way:

1. ~~**Routes**~~ — settled on 18.10.
2. ~~**Haiku cost**~~ — with infomaster (the "LLM usage" screen).
3. **Full refresh:** how often it is really needed. To be tuned on the live panel.
4. **Font in black and white:** no antialiasing or a threshold. To be decided on previews and on the panel.
