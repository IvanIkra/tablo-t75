import json
from pathlib import Path

import pytest
from aiohttp import WSMsgType

from tablo import config, protocol
from tablo.app import HUB, create_app
from tablo.ha import FakeHA

CFG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"
WS = "/ws?device=test&token=dev-device-token"
AUTH = {"Authorization": "Bearer dev-api-token"}


@pytest.fixture
async def client(aiohttp_client, tmp_path):
    cfg = config.load(CFG_PATH, local=False)
    app = create_app(cfg, FakeHA(fast_delay=0, slow_delay=0), data_dir=tmp_path, periodic=False)
    return await aiohttp_client(app)


async def _recv(ws):
    msg = await ws.receive(timeout=5)
    if msg.type == WSMsgType.BINARY:
        return protocol.decode_frame(msg.data)
    assert msg.type == WSMsgType.TEXT, msg
    return json.loads(msg.data)


async def _hello(ws, last_crc=None):
    await ws.send_json({"type": "hello", "fw": "test", "last_crc": last_crc})
    config_msg, health, frame = await _recv(ws), await _recv(ws), await _recv(ws)
    assert config_msg["type"] == "config" and health["type"] == "health"
    assert config_msg["theme"] in ("dark", "light")
    assert isinstance(frame, protocol.Frame) and frame.kind == protocol.KIND_BASE
    return frame


async def test_bad_token_is_refused(client):
    resp = await client.get("/ws?token=wrong")
    assert resp.status == 401


async def test_hello_gets_config_health_and_frame(client):
    ws = await client.ws_connect(WS)
    frame = await _hello(ws)
    # Reconnecting with the same CRC skips the frame.
    ws2 = await client.ws_connect(WS)
    await ws2.send_json({"type": "hello", "last_crc": frame.crc})
    assert (await _recv(ws2))["type"] == "config"
    assert (await _recv(ws2))["type"] == "health"
    await ws2.send_json({"type": "status", "rssi": -60})
    resp = await client.get("/api/status")
    assert (await resp.json())["devices"]["test"]["rssi"] == -60


async def test_toggle_sends_new_frame_then_result(client):
    ha = client.app[HUB].ha
    ws = await client.ws_connect(WS)
    first = await _hello(ws)
    await ws.send_json({"type": "button", "id": 4, "press": "short", "seq": 9})
    frame, result = await _recv(ws), await _recv(ws)
    assert isinstance(frame, protocol.Frame) and frame.crc != first.crc
    assert result == {"type": "button_result", "seq": 9, "ok": True}
    assert ha.state("light.desk_light") == "on"
    assert ("tablo_button", {"button": 4, "press": "short"}) in ha.events


async def test_long_press_qr_sends_overlay(client):
    ws = await client.ws_connect(WS)
    await _hello(ws)
    await ws.send_json({"type": "button", "id": 7, "press": "long", "seq": 1})
    overlay = await _recv(ws)
    assert overlay.kind == protocol.KIND_OVERLAY and overlay.ttl_s == 20
    assert (await _recv(ws))["ok"] is True


async def test_failed_action_reports_error(client):
    client.app[HUB].ha.states.pop("light.ceiling_light")
    ws = await client.ws_connect(WS)
    await _hello(ws)
    await ws.send_json({"type": "button", "id": 2, "press": "short", "seq": 5})
    result = await _recv(ws)
    assert result["seq"] == 5 and result["ok"] is False and "unknown entity" in result["error"]


async def test_api_requires_token_and_shows_message(client):
    ws = await client.ws_connect(WS)
    await _hello(ws)
    resp = await client.post("/api/overlay/message", json={"title": "Hi", "text": "x"})
    assert resp.status == 401
    resp = await client.post("/api/overlay/message", json={"title": "Hi", "text": "x", "duration_s": 5}, headers=AUTH)
    assert resp.status == 200
    overlay = await _recv(ws)
    assert overlay.kind == protocol.KIND_OVERLAY and overlay.ttl_s == 5


async def test_put_config_applies_and_is_saved(client, tmp_path):
    ws = await client.ws_connect(WS)
    await _hello(ws)
    new = {"display": {"long_press_ms": 800}, "buttons": [{"id": 1, "icon": "mdi:lamp", "short": {"action": "event"}}]}
    resp = await client.put("/api/config", json=new, headers=AUTH)
    assert resp.status == 200
    msg = await _recv(ws)
    assert msg["type"] == "config" and msg["long_press_ms"] == 800
    assert (tmp_path / "config.yaml").exists()
    resp = await client.put("/api/config", json={"buttons": [{"id": 9}]}, headers=AUTH)
    assert resp.status == 400


async def test_frame_png(client):
    resp = await client.get("/frame.png")
    assert resp.status == 200 and resp.content_type == "image/png"


async def test_demo_switches_turn_off_fake_ha_and_persist(client, tmp_path):
    ws = await client.ws_connect(WS)
    await _hello(ws)
    resp = await client.put("/api/demo", json={"ha": False, "news": False})
    assert resp.status == 401
    resp = await client.put("/api/demo", json={"ha": False, "news": False}, headers=AUTH)
    assert resp.status == 200 and (await resp.json())["ha"] is False
    msgs = [await _recv(ws) for _ in range(2)]
    health = next(m for m in msgs if isinstance(m, dict))
    assert (health["type"], health["ha"], health["data"]) == ("health", False, False) and "llm" not in health
    assert json.loads((tmp_path / "demo.json").read_text())["news"] is False

    await ws.send_json({"type": "button", "id": 4, "press": "short", "seq": 2})
    result = await _recv(ws)
    assert result["ok"] is False and "not connected" in result["error"]

    resp = await client.put("/api/demo", json={"bogus": True}, headers=AUTH)
    assert resp.status == 400


async def test_emulator_files_and_fonts_are_revalidated(client):
    for path in ("/emu/static/emu.js", "/fonts/pixel/clock-64.txt", "/mdi/materialdesignicons-webfont.ttf"):
        resp = await client.get(path)
        assert resp.status == 200 and resp.headers["Cache-Control"] == "no-cache", path
    page = await client.get("/emu")
    assert page.headers["Cache-Control"] == "no-store"
    html = await page.text()
    assert "/emu/static/emu.js?v=" in html and "/emu/static/emu.css?v=" in html


async def _no_message(ws):
    with pytest.raises(TimeoutError):
        await ws.receive(timeout=0.2)


async def test_sticky_messages_wait_for_a_button_in_order(client):
    hub, ha = client.app[HUB], client.app[HUB].ha
    ws = await client.ws_connect(WS)
    await _hello(ws)
    for title in ("First", "Second"):
        resp = await client.post("/api/overlay/message", json={"title": title, "sticky": True}, headers=AUTH)
        assert resp.status == 200
        overlay = await _recv(ws)
        assert overlay.kind == protocol.KIND_OVERLAY and overlay.ttl_s == 0
    status = await (await client.get("/api/status")).json()
    assert [m["title"] for m in status["messages"]] == ["First", "Second"]

    # A reconnect gets the oldest one again after the base frame.
    ws = await client.ws_connect(WS)
    await _hello(ws)
    shown = await _recv(ws)
    assert shown.ttl_s == 0 and shown.payload == overlay.payload

    await ws.send_json({"type": "overlay_closed", "reason": "button"})
    assert (await _recv(ws)).ttl_s == 0  # the second one
    assert [m["title"] for m in hub.sticky] == ["Second"]
    assert any(e == "tablo_message_dismissed" and d["title"] == "First" and d["waiting"] == 1 for e, d in ha.events)
    await ws.send_json({"type": "overlay_closed", "reason": "button"})
    await _no_message(ws)
    assert hub.sticky == [] and hub.store.get_json("messages.sticky") == []


async def test_sticky_message_comes_back_after_a_timed_one(client):
    ws = await client.ws_connect(WS)
    await _hello(ws)
    await client.post("/api/overlay/message", json={"title": "Urgent", "sticky": True}, headers=AUTH)
    sticky = await _recv(ws)
    await client.post("/api/overlay/qr", json={}, headers=AUTH)
    assert (await _recv(ws)).ttl_s > 0
    await ws.send_json({"type": "overlay_closed", "reason": "ttl"})
    assert (await _recv(ws)).payload == sticky.payload
    assert len(client.app[HUB].sticky) == 1


async def test_sticky_message_closed_by_old_firmware_is_not_sent_again(client):
    ws = await client.ws_connect(WS)
    await _hello(ws)
    await client.post("/api/overlay/message", json={"title": "Urgent", "sticky": True}, headers=AUTH)
    await _recv(ws)
    await ws.send_json({"type": "overlay_closed", "reason": "ttl"})
    await _no_message(ws)
    assert len(client.app[HUB].sticky) == 1


async def test_clear_messages_takes_the_shown_one_off(client):
    ws = await client.ws_connect(WS)
    await _hello(ws)
    await client.post("/api/overlay/message", json={"title": "Urgent", "sticky": True}, headers=AUTH)
    await _recv(ws)
    assert (await client.delete("/api/messages")).status == 401
    resp = await client.delete("/api/messages", headers=AUTH)
    assert (await resp.json()) == {"cleared": 1}
    assert (await _recv(ws)) == {"type": "close_overlay"}
    assert client.app[HUB].sticky == []


async def _hello_fw(client, fw, notes=None):
    """Connects, skips config and health; what comes next is up to the test."""
    ws = await client.ws_connect(WS)
    await ws.send_json({"type": "hello", "fw": fw, "notes": notes, "last_crc": None})
    for _ in range(2):  # config, health
        await _recv(ws)
    return ws


async def test_new_firmware_number_gets_a_welcome_until_a_button_then_sticky_messages(client):
    store = client.app[HUB].store
    ws = await _hello_fw(client, "fw-0.4+aaa")
    assert (await _recv(ws)).kind == protocol.KIND_BASE
    await _no_message(ws)  # first seen: nothing to compare with
    await client.post("/api/overlay/message", json={"title": "Urgent", "sticky": True}, headers=AUTH)

    ws = await _hello_fw(client, "fw-0.5+bbb", "Update screen on the panel.")
    welcome = await _recv(ws)  # before the base: the panel keeps the base for after it
    assert welcome.kind == protocol.KIND_OVERLAY and welcome.ttl_s == 0
    assert (await _recv(ws)).kind == protocol.KIND_BASE
    await _no_message(ws)  # the sticky one waits for the welcome
    assert store.get_json("device.fw:test") == "fw-0.4+aaa"  # not seen yet

    # A reconnect before the button: the welcome again.
    ws = await _hello_fw(client, "fw-0.5+bbb", "Update screen on the panel.")
    assert (await _recv(ws)).payload == welcome.payload
    assert (await _recv(ws)).kind == protocol.KIND_BASE
    await ws.send_json({"type": "overlay_closed", "reason": "button"})
    sticky = await _recv(ws)
    assert sticky.ttl_s == 0 and sticky.payload != welcome.payload
    assert store.get_json("device.fw:test") == "fw-0.5+bbb"

    # Same number, another commit: no welcome, the base and the sticky message at once.
    ws = await _hello_fw(client, "fw-0.5+ccc")
    assert (await _recv(ws)).kind == protocol.KIND_BASE
    assert (await _recv(ws)).payload == sticky.payload
    assert store.get_json("device.fw:test") == "fw-0.5+ccc"
