# Tablo — software: the system and the screen zones (§1–2)

> Part of the software design, index in [`docs/README.md`](../README.md). Section numbers §N run through all the parts.

## 1. The system

```
 infomaster ───────┐  API: deadlines, news, grades, status
 (infomaster net)  │  tablo.ics feed: classes
 Open-Meteo ───────┤                               WebSocket :8765
                   └──▶  Tablo service  ◀══════════════════════════▶  ESP32-L board
                        (Python, Pillow,    1-bit frames, config ▶     or the emulator
                         SQLite)            ◀ presses, status          in a browser
                            ▲   │
          HTTP API          │   │  HA WebSocket API
       (config, screens)    │   ▼  (states, call_service, events)
                  Home Assistant + the "Tablo" integration
```

The university app, mail, Telegram chats, the timetable and the grade sheets are collected by a separate service, infomaster (its own repository): it merges deadlines, parses news and grades with an LLM (Claude Haiku) and serves the result. Tablo only shows it.

| Part | What it does | Where it runs |
|---|---|---|
| **Service** | Takes data from infomaster and Open-Meteo, lays out the frame, keeps the link to the board, runs button actions in HA | Docker on the `server` |
| **Emulator** | Behaves exactly like the board, over the same protocol | A web page served by the service, runs in a browser on the dev machine |
| **HA integration** | Settings UI, button triggers for automations, `tablo.*` actions | `custom_components/tablo` in the HA config |
| **Firmware** | Shows frames, draws the clock, date and status line, polls the buttons | ESP32-L |

The main principle stays: a smart server and a simple device. The board does not know what is in the picture, but it can live without the service: the clock keeps going and the status line honestly shows the failure.

---

## 2. Who draws what

The screen is 800×480, 1 bit. Coordinates are `x, y, width, height` in pixels. They get final values during layout; the firmware receives the zones in the `config` message (§3.3), so they can change without reflashing.

| Zone | Rectangle | Drawn by | Contents |
|---|---|---|---|
| Clock and date | `0, 0, 184, 100` | **firmware** | Time in 64 px pixel digits of one width (`HH:MM` is always 174 px), below it "Wed, Oct 14 · wk 7" |
| Status line | `600, 0, 200, 24` | **firmware** | Wi-Fi, cloud (service), house (HA); while infomaster does not answer (`data: false` in `health`) there is also a "database off" icon on the left (`mdi:database-off`): the blocks show what was saved. Without a link to the service — a black "offline since HH:MM" badge. The last sync time is only on the diagnostics screen |
| Weather now | `188, 14, 142, 68` | service | Icon, temperature, "feels" |
| Forecast | `340, 26, 452, 68` | service | 8 columns: hour, icon, temperature |
| Deadlines | `0, 100, 272, 164` | service | |
| Grades | `0, 264, 272, 164` | service | |
| News | `272, 100, 288, 328` | service | |
| Classes | `560, 100, 240, 164` | service | |
| Home | `560, 264, 240, 164` | service | |
| Buttons | `0, 428, 800, 52` | service, the board inverts | 8 tiles of 100×52 |

- The service leaves the firmware zones **white**. The board draws them over the frame.
- **Date on the board:** the board takes "Wed, Oct 14" from its own clock and counts the week number "wk N" itself from `semester_start` in the config. So the date changes at midnight even if the service is down.
- **Button tiles:** a filled tile means "on". The service draws the icons and the fill. On a press the board inverts the tile **at once** (§4.2).
- The font is Inter. The screen interface is in English.
