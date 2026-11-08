# Tablo — software: data sources (§7)

> Part of the software design, index in [`docs/README.md`](../README.md). Section numbers §N run through all the parts.

## 7. Data sources

Since 21.10.2026 Tablo only shows data (infomaster decision 35). The university app, mail, Telegram chats, the timetable and the grade sheets are collected by a separate service, **infomaster** (its own repository, the contract is its `architecture.md`, §8.2): it merges deadlines, parses news and grades with Haiku, keeps own and hidden deadlines (its Mini App and the forum buttons) and serves the result. Tablo has no LLM of its own.

| Block | Source | Polled |
|---|---|---|
| Deadlines | infomaster `GET /api/deadlines` | 1 min |
| News | infomaster `GET /api/news` | 1 min |
| Grades | infomaster `GET /api/grades` | 1 min |
| Block failures | infomaster `GET /api/status` | 1 min |
| Classes | infomaster's `tablo.ics` feed | 10 min |
| Weather | Open-Meteo, Moscow | 15 min |
| Home | HA WebSocket | Instantly |

### 7.1 infomaster (`sources/infomaster.py`)

- **Address:** `infomaster.url`, `http://infomaster:8081` by default — infomaster's internal port, only inside its `infomaster` docker network (Tablo joins it as an external network, §12). **Token:** `Authorization: Bearer <TABLO_INFOMASTER_TOKEN>` (infomaster's `API_TOKEN`, `.env`, §13).
- Once a minute (`infomaster.poll_seconds`), four `GET`s: `/api/deadlines`, `/api/news`, `/api/grades`, `/api/status`. Each answer is the full current state, with no cursors. Every good answer is saved in `kv` (`infomaster.deadlines`, `.news`, `.grades`, `.status`, with `fetched_at`); an answer that does not parse into the screen model counts as an error and is not saved. A 401 ends the round: all four share one token.
- **infomaster unreachable** (network, 401, bad JSON): the blocks show what was saved. Its own status is `ok_at` (the last round without errors) and `error`. If the oldest of the four saved answers is older than **10 minutes**, the service sends the board `health` with `data: false`, and the `mdi:database-off` icon appears in the status line (§2, §3.3); once answers come again, the icon goes away.
- `tablo.refresh_data` and button 8 just poll at once: infomaster has no "refresh now".
- **Grades** (`/api/grades`): new and changed within infomaster's window, the last event for each piece of work, newest first. The screen gets `label`, `value` (already 0–10) and `bonus` in the order they came. What does not fit becomes `+N` in the header. A failure comes from the sheets in the status's `grades.sheets`: all failing — *sheets unavailable*, some — *N sheet(s) failing* (instead of "no new grades" when there are none).

### 7.2 Deadlines

The list from `/api/deadlines` is already merged, without hidden and completed ones, picked and ordered the way the block shows it: upcoming by due date, then overdue (3 days past due, 1 day for mail and Telegram). Tablo neither filters nor sorts, it just takes the first rows (5 at 22 px now); the rest is a `+N` counter in the header. An urgent one (today or tomorrow) is inverted, an overdue one is marked `overdue`.

Each deadline has two attributes, both shown as icons on the left:

| `source` | Where from (in infomaster) | Source icon |
|---|---|---|
| `hseapp` | the university app | `mdi:school` |
| `mail` | a letter | `mdi:email-outline` |
| `tg` | a Telegram chat or channel | `mdi:send` |
| `ical` | an interim assessment from the timetable (`<abbr> Midterm`) | `mdi:calendar` |
| `ha` | own, from the Mini App or the forum buttons | `mdi:home-outline` |

**Category icons:** study (`study`) — `mdi:book-open-variant`, personal (`personal`) — `mdi:account`. A row: `[category][source] Calc HW 5 … tomorrow`.

**Failures** come from the university app status in `/api/status` (`hseapp`), as the block's first row: `login_needed` — *HSE login needed* (plus an HA notification with a link to the infomaster bot, §8.4); `error` with `ok_at` older than 3 hours or `null` — *the university app unavailable*. `ok_at: null` without an error is not a failure: infomaster keeps it in memory, so after its restart it is empty until the source runs.

There are no to-do lists in HA any more (infomaster decision 34): own deadlines are added and hidden in infomaster's Mini App.

### 7.3 Classes — the `tablo.ics` feed

- The link `http://infomaster:8081/calendar/<CALENDAR_SECRET>/tablo.ics` has no token, the secret is in the path; it is set in HA (the "Sources" form, §8.3) or in `config.local.yaml`. Polled every 10 min (`ical.poll_minutes`): the feed is internal and cheap. It carries timetable classes, consultations and events from chats, required and optional ones together.
- **The title is `SUMMARY` as is:** infomaster has already given a short English one from its dictionary (a 13-character budget). If it does not fit — "…".
- The first line of `DESCRIPTION` is the type (*Lecture*, *Seminar*, *Consultation*, *Event*, *Interim assessment*), followed by infomaster's notes.
- **Room:** the first part of `LOCATION` up to the comma (`R609`, `109`). A link in `LOCATION` or in the description, or a `URL`, means `online`. Nothing means empty.
- **Marks** (`ClassItem.mark`), one per class, by priority: `STATUS:CANCELLED` — *cancelled* (such classes are shown, not skipped); a `Moved from …` line in `DESCRIPTION` after the type — *moved* (the time in the feed is already the new one); `STATUS:TENTATIVE` or `X-INFOMASTER-OPTIONAL:TRUE` — *optional* (an optional event, infomaster decision 36).
- **A row on screen:** `10:00 Algebra R401`; *cancelled* is the word in place of the room (`10:00 Algebra cancelled`), *optional* a 15 px smiley there; a *moved* class keeps its room and its new time is drawn white on black, as the time is what changed.
- **Which classes to show:** up to 5 of the nearest that have not ended today (as many rows as the block holds; the one going on now is a normal row), with *today* in the header. Nothing left today — the nearest day with events, with *tomorrow*, the weekday (*Tue*) or the date in the header if it is a week or more away. The pick runs on every redraw, once a minute, over the saved feed.
- **Interim assessment** is a normal feed event; the `<abbr> Midterm` deadline comes in `/api/deadlines` with `source: ical`, Tablo does not make it from the feed.
- **Failures:** if the feed does not answer, the saved one stays. No link — *calendar link not set*; a failure for over 12 hours — *timetable unavailable* (instead of "no classes" when there are none). A timetable error inside infomaster itself (`ruz.error`) shows in its "System" topic.
- `X-INFOMASTER-SOURCE` and `X-INFOMASTER-LINK` are not read yet: an event's source icon is for an extended version of the screen.

### 7.4 Weather — Open-Meteo

- Moscow, `55.7558, 37.6173`, time zone `Europe/Moscow`. No key.
- `current`: temperature, "feels like", weather code, day or night. `hourly`: `temperature_2m`, `precipitation`, `precipitation_probability`, `weather_code`, `is_day`.
- The forecast is 8 hours starting with the current one. We request 12 hours (`forecast_hours`) and keep the answer in the database.
- The icon: first the weather code (snow, thunderstorm, fog). Rain is drawn if the probability is ≥ 40%: < 2.5 mm/h — 1 stroke, 2.5–7.6 — 2, > 7.6 — 3. Otherwise a cloud, the sun or the moon (codes 0–1 are clear, the rest are cloud). For "now" the probability comes from the current hour, and if it is raining right now, rain is always drawn.
- **Open-Meteo does not answer:** the saved forecast shifts with the hours, and "now" comes from the forecast for the current hour. After **3 hours** without a fresh answer — *no weather*.
- Settings: the `weather` section (coordinates, `poll_minutes`).

### 7.5 News

`/api/news` returns infomaster's live news (not replaced, withdrawn, hidden or older than `ttl_hours`) in rank order: `importance` (1–5) + 1 for study items, newer first on a tie. Exactly what is pinned in the forum's "News". Tablo takes `full` (up to 2 lines of the column), `short` (1 line), `source` (`tg`, `mail`), `importance`, `study` and lays them out by §7.7. Each has its source icon on the left.

**Failure:** infomaster's batch parsing (`batches` in `/api/status`) has an error and `ok_at` is older than 3 hours or `null` — the row *news unavailable* instead of "no news" (when there are none).

### 7.6 Home — Home Assistant

- The service keeps a WebSocket to HA (`subscribe_entities`), so states arrive instantly. The address is `ha.url` in the config, the token is `TABLO_HA_TOKEN` in `.env`. A lost link reconnects after 1, 2, 5, 10, 30, 60 s; a bad token — every 5 min.
- The Home block is HA template rows (`home.rows`, §8.3): HA renders them itself and sends new values. By default: temperature and humidity (`sensor.room_sensor_temperature` / `_humidity`), "lights N of M", the printer.
- **Running scripts** come first in the block, above the template rows (which move down; the last ones drop off): `Closet for 5 min  4 min left`. A row appears for every `script.*` that is on and waits — a `delay`, `wait_template` or `wait_for_trigger`; a script that never waits is on for a moment only and gets no row, which would just flash on the panel. When a script starts, the service asks HA for its config (`script/config` over the WebSocket) and adds up its delays: the time left is `last_triggered` + that sum − now, in whole minutes rounded up (`1:20 left` past an hour), redrawn with the minute re-render. A script in `restart` mode starts the count again on a second press. When the length cannot be known in advance — a template delay, a wait for a trigger, a delay inside `choose`/`repeat`, a script from a blueprint, or the delays are already over — the row says `running`. The name is the script's `friendly_name` without the `Tablo · ` prefix the button scripts use; a long name is cut, the time left is not.
- **"lights N of M"** counts the 5 lights on the buttons: ceiling, lamp, desk, backlight, closet. The list is in the row's template.
- **Printer:** HA has no Klipper integration right now. We install the Moonraker integration in HA and take the status from its entities: its state, progress and time left. The service does not talk to Moonraker itself.
- The fake HA (tests, emulator) renders the same templates with jinja2: `states`, `is_state`, `state_attr`, `is_number`, the `round`, `float`, `int` filters.
  - The row is always there: `printer  42% · 1:20` while printing (the time left in h:mm by the sensor's `unit_of_measurement`), `printer  paused · 42%`, `printer  idle` (standby, cancelled), `done`, `error`, `off` (the sensor is unavailable — the host or the printer is off). No printer set — no row.
- The same channel gives the tile states (§8.2) and runs actions (`call_service`): a toggle is `homeassistant.toggle` with a wait for the new state, a script and a scene are `turn_on` (does not wait for the script to finish), an automation is `trigger`, a button is `press`.
- HA gone — the Home block and the tiles show the last known states (§11). Until the first list of states — *no Home Assistant*.
- In the emulator the *fake HA* checkbox switches between a stand-in home in memory and the real HA.

### 7.7 Fitting text into place

infomaster writes the texts: their length is checked by characters for now, not with Tablo's font (infomaster decision 39). Tablo cuts the extra with "…". Moving the check into infomaster with a real render (`render/pixelfont.py`) is a separate task.

**The news packer** (`render/screen.py`, `layout_news`): a one-line item takes 30 px, a two-line one 50 px. First `full` for rank 5 and above (study items that need action), then one `short` line for everything with importance above 1, then `full` for the rest by rank while there is room, and finally importance 1 in what is left.
