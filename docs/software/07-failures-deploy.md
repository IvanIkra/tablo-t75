# Tablo — software: failures, deployment, secrets (§11–13)

> Part of the software design, index in [`docs/README.md`](../README.md). Section numbers §N run through all the parts.

## 11. Failures

| What failed | Screen | Buttons |
|---|---|---|
| **Wi-Fi** | The frame stays, the clock runs on the internal clock; after `offline_after_s` — an "offline since" badge | Inversion, rolled back after 1.5 s |
| **Service** | The same, the cloud in the status line goes out | The same |
| **HA** (the service is alive) | The house in the status line goes out, the Home block and the tiles show the last known state | `button_result ok:false`, the tile rolls back |
| **infomaster** (no answer, 401, a bad answer) | Deadlines, news and grades show the last saved data; after 10 min — the `mdi:database-off` icon in the status line (`health.data: false`) | — |
| **A source inside infomaster** | A note in its own block, from `/api/status` (§7.1–7.5): *HSE login needed*, *the university app unavailable* (3 h), *N sheet(s) failing* / *sheets unavailable*, *news unavailable* (3 h). Timetable, mail and Telegram errors are in infomaster's "System" topic | — |
| **Class feed** | The saved one; after 12 h — *timetable unavailable* | — |
| **Weather** | The forecast shifts with the hours; after 3 h — *no weather* | — |
| **Service restart** | The board reconnects and gets the config and the frame | — |

---

## 12. Deployment and resources

**Development** — on the dev machine; the service can talk to the real HA (`TABLO_HA_URL`) or run with the built-in fake one.

**Production** — Docker Compose on the `server` ([`service/compose.yaml`](../../service/compose.yaml)), running since 18.10:
- A `~/tablo` directory on the server: the code from `service/`, `.env` and `data/` (SQLite with infomaster's last answers and the config from HA). To update the code, rsync `service/` and run `docker compose up -d --build`. If the server cannot reach Docker Hub or PyPI, build the image on the dev machine (`docker buildx build --platform linux/amd64 -t tablo:latest --load .`) and move it with `docker save | ssh server docker load`.
- A bridge network, with the port published on one LAN address only (`TABLO_BIND_IP` in `.env`): another service on the host may already hold `127.0.0.1:8765`. DNS for the container is set explicitly (`TABLO_DNS`, `TABLO_DNS_FALLBACK`). Not `network_mode: host`: with it the container takes the host's DNS, which broke HA once already.
- HA is reached at `TABLO_HA_URL` from `.env`.
- **infomaster:** Tablo joins its `infomaster` docker network as an external one (`networks: [default, infomaster]`) and reaches `http://infomaster:8081` by service name. infomaster's compose creates the network, so infomaster starts before Tablo. infomaster's port is not published on the host.
- A `./data` volume for SQLite and the saved config. `mem_limit: 256m`, `TZ=Europe/Moscow`.
- **Internet access** (the service only needs Open-Meteo): no proxy of its own is needed.

**Memory** (measured on 18.10 in the container):

| State | RSS |
|---|---|
| After startup, all sources and sheet parsing | 124 MB, peak 126 MB |
| `docker stats` | 95 MB of 256 MB |

Measured before the move to infomaster; without Haiku, sheets, mail and Telegram it uses less — to be measured again after a deploy. CPU at idle is near zero.

---

## 13. Secrets and privacy

| Secret | Where it is kept |
|---|---|
| The HA token, the infomaster token (`TABLO_INFOMASTER_TOKEN` = infomaster's `API_TOKEN`), the board and API tokens | The service's `.env` |
| The class feed link (with infomaster's `CALENDAR_SECRET`), Wi-Fi passwords for the QR | The integration's settings in HA (`.storage`) |

- Each secret lives in one place. infomaster collects deadlines, news and grades and holds the credentials for them; Tablo keeps only the HA, infomaster, board and API tokens.
- Secrets never go into the repository: it only has `.env.example`.
- The service listens on the local network only and is not exposed to the internet.
