"""What the HA integration uses: config import, to-do lists, refetch, change events (§6.4, §8)."""

import datetime as dt
from pathlib import Path

import pytest

from tablo import config
from tablo.app import HUB, create_app
from tablo.ha import FakeHA
from tablo.model import Deadline

CFG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
AUTH = {"Authorization": "Bearer dev-api-token"}


@pytest.fixture
async def client(aiohttp_client, tmp_path):
    cfg = config.load(CFG_PATH, local=False)
    app = create_app(cfg, FakeHA(fast_delay=0, slow_delay=0), data_dir=tmp_path, periodic=False)
    return await aiohttp_client(app)


def test_to_dict_round_trip_without_secrets(monkeypatch):
    monkeypatch.setenv("TABLO_MAIL_PASSWORD", "secret")
    cfg = config.load(CFG_PATH, local=False)
    d = config.to_dict(cfg)
    assert not {"server", "device", "api", "ha", "demo"} & set(d)
    assert "password" not in d["mail"] and "user" not in d["mail"]
    again = config.from_dict(d)
    assert config.to_dict(again) == d and again.mail.password == "secret"


def test_ical_link_from_ha_wins_over_env(monkeypatch):
    monkeypatch.setenv("TABLO_ICAL_URL", "https://env")
    assert config.from_dict({}).ical.url == "https://env"
    assert config.from_dict({"ical": {"url": "https://ha"}}).ical.url == "https://ha"


async def test_config_needs_token(client):
    assert (await client.get("/api/config")).status == 401
    resp = await client.get("/api/config", headers=AUTH)
    assert (await resp.json())["buttons"][0]["short"]["entity"] == "script.all_lights_off"


async def test_subjects_from_ha_are_manual(client):
    hub = client.app[HUB]
    hub.subjects.set("Матан", "Calc", "Calc", manual=False)
    data = config.to_dict(hub.cfg)
    data["subjects"] = [{"name": "Дискретная математика", "title": "Discrete Math", "abbr": "DM"}]
    assert (await client.put("/api/config", json=data, headers=AUTH)).status == 200
    assert hub.subjects.get("Дискретная математика").abbr == "DM"
    data["subjects"] = []
    await client.put("/api/config", json=data, headers=AUTH)
    assert hub.subjects.get("Дискретная математика") is None  # Haiku's to name again
    assert hub.subjects.get("Матан").title == "Calc"  # Haiku's own entries stay


async def test_todo_api(client, monkeypatch):
    hub = client.app[HUB]
    today = hub.now().date()
    mail = Deadline("Calc HW 3", today + dt.timedelta(days=1), "study", "mail", "Calc")
    old = Deadline("Prog HW 1", today - dt.timedelta(days=2), "study", "hseapp", "Prog")
    monkeypatch.setattr(hub.news, "deadlines", lambda: (mail,))
    monkeypatch.setattr(hub.hseapp, "current", lambda: (old,))
    resp = await client.get("/api/deadlines", headers=AUTH)
    items = (await resp.json())["items"]
    assert [(i["title"], i["source"], i["overdue"]) for i in items] == [
        ("Calc HW 3", "mail", False), ("Prog HW 1", "hseapp", True)]

    # A new own deadline: needs a date and a list.
    bad = await client.post("/api/deadlines", json={"title": "Dentist", "category": "personal"}, headers=AUTH)
    assert bad.status == 400
    resp = await client.post("/api/deadlines", headers=AUTH, json={
        "title": "Dentist", "due": (today + dt.timedelta(days=5)).isoformat(), "category": "personal"})
    own = (await resp.json())["uid"]
    assert own.startswith("ha-")

    # Done hides it for good, also when it comes back from Telegram.
    uid = items[0]["uid"]
    assert (await client.patch(f"/api/deadlines/{uid}", json={"done": True}, headers=AUTH)).status == 200
    monkeypatch.setattr(hub.news, "deadlines",
                        lambda: (Deadline("Calc HW 3", today + dt.timedelta(days=1), "study", "tg", "Calc"),))
    titles = [d.title for d in hub.deadlines()]
    assert titles == ["Prog HW 1", "Dentist"]

    # Editing one from a source: hidden, an own copy with the new date.
    later = (today + dt.timedelta(days=9)).isoformat()
    resp = await client.patch(f"/api/deadlines/{items[1]['uid']}", json={"due": later}, headers=AUTH)
    copy = (await resp.json())["uid"]
    got = {d.title: (d.source, d.due.isoformat()) for d in hub.deadlines()}
    assert got == {"Prog HW 1": ("ha", later), "Dentist": ("ha", (today + dt.timedelta(days=5)).isoformat())}

    assert (await client.delete(f"/api/deadlines/{copy}", headers=AUTH)).status == 200
    assert (await client.delete(f"/api/deadlines/{own}", headers=AUTH)).status == 200
    assert hub.deadlines() == ()
    assert (await client.delete(f"/api/deadlines/{own}", headers=AUTH)).status == 404


async def test_changes_fire_tablo_changed(client, monkeypatch):
    hub = client.app[HUB]
    await hub.render_base()
    events = hub.ha.events
    assert ("tablo_changed", {"kind": "deadlines"}) in events
    events.clear()
    await hub.render_base()
    assert events == []  # nothing changed
    d = Deadline("Calc HW 3", hub.now().date(), "study", "tg", "Calc")
    monkeypatch.setattr(hub.news, "deadlines", lambda: (d,))
    await hub.render_base()
    for task in list(hub._tasks):
        await task
    assert events == [("tablo_changed", {"kind": "deadlines"})]


async def test_refresh_refetches_sources(client, monkeypatch):
    hub = client.app[HUB]
    woken = []
    monkeypatch.setattr(hub.grades, "refetch", lambda: woken.append("grades"))
    monkeypatch.setattr(hub.telegram, "refetch", lambda: woken.append("tg"))
    monkeypatch.setattr(hub.mail, "refetch", lambda: woken.append("mail"))
    resp = await client.post("/api/refresh", json={"sources": ["grades", "news"]}, headers=AUTH)
    assert resp.status == 200 and woken == ["grades", "tg", "mail"]
    resp = await client.post("/api/refresh", json={"sources": ["nope"]}, headers=AUTH)
    assert resp.status == 400


async def test_status_has_panel_and_login(client):
    ws = await client.ws_connect("/ws?device=test&token=dev-device-token")
    await ws.send_json({"type": "hello", "rssi": -70})
    await ws.receive(timeout=5)
    await ws.send_json({"type": "button", "id": 4, "press": "short", "seq": 1})
    status = await (await client.get("/api/status")).json()
    assert status["panel"]["connected"] and status["panel"]["rssi"] == -70 and status["panel"]["last_seen"]
    assert status["hseapp"]["login_needed"] is True
    await ws.close()
