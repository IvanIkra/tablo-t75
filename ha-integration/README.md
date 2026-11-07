# Tablo integration for Home Assistant

The contract is [§8](../docs/software/05-ha-integration.md). Tested on HA 2026.4.4.

## Installation

1. Copy `custom_components/tablo` to `<HA config>/custom_components/tablo`.
2. Restart HA.
3. Settings → Devices & services → Add integration → **Tablo T75**: the service address (`http://<host-ip>:8765`) and the API token — `TABLO_API_TOKEN` from the service's `.env`, or `dev-api-token` if it is not set there. The service's config is imported by itself.
4. Scripts for long presses are in [`scripts/tablo.yaml`](scripts/tablo.yaml).
5. After updating from a version with to-do lists: remove the orphaned `todo.tablo_*` entities and the "LLM run: …", "LLM cost today" sensors in HA; in the "Sources" form, set the link to infomaster's `tablo.ics` and its bot name.

The service needs its own long-lived HA token (`TABLO_HA_TOKEN`) from an administrator user: without admin rights HA does not let it fire the `tablo_button` and `tablo_changed` events.

## What is where

| File | What |
|---|---|
| `__init__.py` | Setup, migration of old entries (1.1 → 1.2: without the infomaster source settings), the `tablo.*` actions (including `show_message` with `sticky` and `clear_messages`), `tablo_changed` events, the university app login notification with a link to the infomaster bot |
| `config_flow.py` | Connecting to the service and the "Configure" forms: buttons, Wi-Fi, sources, home, screen |
| `forms.py` | Multi-line form fields ↔ config lists |
| `coordinator.py`, `api.py` | Polling the service and the HTTP client |
| `device_trigger.py` | The "button N, short / long" triggers |
| `binary_sensor.py`, `sensor.py` | "Connected", Wi-Fi signal, last contact, "Sticky messages" (how many sticky messages are waiting, titles in the `messages` attribute) |

## Tests

The tests start a real service with a fake home and run the integration in a test HA.

```bash
uv sync    # Python 3.14, Home Assistant and the service from ../service, versions from uv.lock
```

```bash
uv run pytest
```
