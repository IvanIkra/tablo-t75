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
    cfg = config.load(CFG_PATH)
    app = create_app(cfg, FakeHA(fast_delay=0, slow_delay=0), saved_config=tmp_path / "config.yaml", periodic=False)
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
