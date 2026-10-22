"""What the HA integration uses: config import, refetch, change events, status (§6.4, §8)."""

import datetime as dt
from pathlib import Path

import pytest

from tablo import config
from tablo.app import HUB, create_app
from tablo.ha import FakeHA
from tablo.sources import infomaster

CFG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
AUTH = {"Authorization": "Bearer dev-api-token"}


@pytest.fixture
async def client(aiohttp_client, tmp_path):
    cfg = config.load(CFG_PATH, local=False)
    app = create_app(cfg, FakeHA(fast_delay=0, slow_delay=0), data_dir=tmp_path, periodic=False)
    return await aiohttp_client(app)


def _uni_status(hub, **hseapp):
    """infomaster's status as if just fetched."""
    hub.store.put_json("infomaster.status", {"fetched_at": hub.now().isoformat(), "data": {"hseapp": hseapp}})


def test_to_dict_round_trip_without_secrets(monkeypatch):
    monkeypatch.setenv("TABLO_INFOMASTER_TOKEN", "secret")
    cfg = config.load(CFG_PATH, local=False)
    d = config.to_dict(cfg)
    assert not {"server", "device", "api", "ha", "demo", "infomaster_token"} & set(d)
    assert d["infomaster"] == {"url": "http://infomaster:8081", "poll_seconds": 60}
    again = config.from_dict(d)
    assert config.to_dict(again) == d and again.infomaster_token == "secret"


def test_old_source_settings_are_rejected():
    for key in ("grades", "hseapp", "news", "mail", "subjects"):
        with pytest.raises(config.ConfigError, match="unknown"):
            config.from_dict({key: {}})


async def test_config_needs_token(client):
    assert (await client.get("/api/config")).status == 401
    resp = await client.get("/api/config", headers=AUTH)
    assert (await resp.json())["buttons"][0]["short"]["entity"] == "script.all_lights_on"


async def test_pushed_config_keeps_the_infomaster_token(client):
    hub = client.app[HUB]
    hub.cfg.infomaster_token = "from-env"
    data = config.to_dict(hub.cfg)
    data["ical"]["url"] = "http://infomaster:8081/calendar/s/tablo.ics"
    assert (await client.put("/api/config", json=data, headers=AUTH)).status == 200
    assert hub.cfg.infomaster_token == "from-env" and hub.cfg.ical.url.endswith("tablo.ics")


async def test_old_deadline_and_hseapp_routes_are_gone(client):
    for method, path in (("GET", "/api/deadlines"), ("POST", "/api/deadlines"), ("GET", "/hseapp"),
                         ("GET", "/api/llm/runs"), ("GET", "/api/hseapp/login")):
        assert (await client.request(method, path, headers=AUTH)).status in (404, 405)


async def test_login_change_fires_tablo_changed(client):
    hub = client.app[HUB]
    await hub.render_base()
    events = hub.ha.events
    assert events == [("tablo_changed", {"kind": "status"})]
    events.clear()
    await hub.render_base()
    assert events == []  # nothing changed
    _uni_status(hub, login_needed=True)
    await hub.render_base()
    for task in list(hub._tasks):
        await task
    assert events == [("tablo_changed", {"kind": "status"})]


async def test_refresh_refetches_sources(client, monkeypatch):
    hub = client.app[HUB]
    woken = []
    monkeypatch.setattr(hub.infomaster, "refetch", lambda: woken.append("infomaster"))
    monkeypatch.setattr(hub.weather, "refetch", lambda: woken.append("weather"))
    resp = await client.post("/api/refresh", json={"sources": ["infomaster", "weather"]}, headers=AUTH)
    assert resp.status == 200 and woken == ["infomaster", "weather"]
    for old in ("grades", "news", "hseapp"):
        resp = await client.post("/api/refresh", json={"sources": [old]}, headers=AUTH)
        assert resp.status == 400


async def test_status_has_panel_and_login_from_infomaster(client):
    hub = client.app[HUB]
    ws = await client.ws_connect("/ws?device=test&token=dev-device-token")
    await ws.send_json({"type": "hello", "rssi": -70})
    await ws.receive(timeout=5)
    await ws.send_json({"type": "button", "id": 4, "press": "short", "seq": 1})
    status = await (await client.get("/api/status")).json()
    assert status["panel"]["connected"] and status["panel"]["rssi"] == -70 and status["panel"]["last_seen"]
    assert status["hseapp"]["login_needed"] is False and status["infomaster"]["down"] is True
    assert "llm" not in status and "news" not in status and "grades" not in status
    _uni_status(hub, login_needed=True, logged_in=False)
    status = await (await client.get("/api/status")).json()
    assert status["hseapp"]["login_needed"] is True and status["hseapp"]["problem"] == "HSE login needed"
    await ws.close()


async def test_health_tells_the_panel_when_infomaster_goes_and_comes_back(client):
    hub = client.app[HUB]
    ws = await client.ws_connect("/ws?device=test&token=dev-device-token")
    await ws.send_json({"type": "hello"})
    await ws.receive(timeout=5)  # config
    health = await ws.receive_json(timeout=5)
    assert health["type"] == "health" and health["data"] is False and "llm" not in health
    await ws.receive(timeout=5)  # frame
    for name in infomaster.ENDPOINTS:
        hub.store.put_json(f"infomaster.{name}", {"fetched_at": hub.now().isoformat(), "data": {"items": []}})
    hub.infomaster.status.ok_at = hub.now().isoformat()
    await hub.render_base()
    msg = await ws.receive_json(timeout=5)
    assert msg["type"] == "health" and msg["data"] is True
    await ws.close()


async def test_infomaster_going_quiet_between_polls_reaches_the_panel(client, monkeypatch):
    """DOWN_AFTER runs out between two polls: the next render tells the panel, and so does the way back."""
    hub = client.app[HUB]
    for name in infomaster.ENDPOINTS:
        hub.store.put_json(f"infomaster.{name}", {"fetched_at": hub.now().isoformat(), "data": {"items": []}})
    hub.infomaster.status.ok_at = hub.now().isoformat()
    ws = await client.ws_connect("/ws?device=test&token=dev-device-token")
    await ws.send_json({"type": "hello"})
    await ws.receive(timeout=5)  # config
    assert (await ws.receive_json(timeout=5))["data"] is True
    await ws.receive(timeout=5)  # frame
    hub.infomaster.status.error = "deadlines: HTTP 503"
    later = hub.now() + infomaster.DOWN_AFTER + dt.timedelta(minutes=1)
    monkeypatch.setattr(hub.infomaster, "now", lambda: later)
    await hub.render_base()
    assert (await ws.receive_json(timeout=5))["data"] is False
    # A panel that reconnects now hears the same; the way back is told at once.
    await hub.render_base()
    hub.infomaster.status.error = None
    await hub.render_base()
    assert (await ws.receive_json(timeout=5))["data"] is True
    await ws.close()
