"""Home Assistant WebSocket client against a fake HA, and the Home block built from its states."""

import asyncio
from pathlib import Path

import pytest
from aiohttp import WSMsgType, web

from tablo import builder, config
from tablo.ha import FakeHA, HAError, HomeAssistant

TOKEN = "good-token"
CFG = config.load(Path(__file__).resolve().parents[1] / "config.yaml", local=False)


class FakeServer:
    """Speaks just enough of HA's WebSocket API: auth, subscribe_entities, call_service, fire_event."""

    def __init__(self):
        self.states = {
            "light.lamp": {"s": "off", "a": {"friendly_name": "Lamp"}},
            "light.dead": {"s": "unavailable", "a": {}},
            "sensor.t": {"s": "21.5", "a": {"unit_of_measurement": "°C"}},
        }
        self.calls: list[dict] = []
        self.sockets: list[web.WebSocketResponse] = []
        self.sub_id = None
        self.answer_toggle = True

    async def handle(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        await ws.send_json({"type": "auth_required"})
        auth = await ws.receive_json()
        if auth.get("access_token") != TOKEN:
            await ws.send_json({"type": "auth_invalid", "message": "Invalid access token"})
            await ws.close()
            return ws
        await ws.send_json({"type": "auth_ok"})
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            m = msg.json()
            if m["type"] == "subscribe_entities":
                self.sub_id = m["id"]
                await ws.send_json({"id": m["id"], "type": "result", "success": True, "result": None})
                await ws.send_json({"id": m["id"], "type": "event", "event": {"a": self.states}})
            else:
                self.calls.append(m)
                ok = m.get("domain") != "bogus"
                await ws.send_json({"id": m["id"], "type": "result", "success": ok, "result": None,
                                    **({} if ok else {"error": {"code": "not_found", "message": "no such service"}})})
                if m.get("service") == "toggle" and self.answer_toggle:
                    entity = m["target"]["entity_id"]
                    new = "on" if self.states[entity]["s"] == "off" else "off"
                    await self.change(entity, new)
        return ws

    async def change(self, entity, state):
        self.states[entity]["s"] = state
        for ws in self.sockets:
            if not ws.closed:
                await ws.send_json({"id": self.sub_id, "type": "event",
                                    "event": {"c": {entity: {"+": {"s": state, "lc": 1.0}}}}})


async def _until(check, timeout=3.0):
    for _ in range(int(timeout / 0.01)):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met")


@pytest.fixture
async def ha_pair(aiohttp_server):
    fake = FakeServer()
    app = web.Application()
    app.router.add_get("/api/websocket", fake.handle)
    server = await aiohttp_server(app)
    client = HomeAssistant(str(server.make_url("")), TOKEN)
    task = asyncio.create_task(client.run())
    await _until(lambda: client.ready)
    yield fake, client
    task.cancel()


async def test_connects_and_reads_states(ha_pair):
    fake, ha = ha_pair
    assert ha.ws_url.startswith("ws://") and ha.ws_url.endswith("/api/websocket")
    assert ha.connected and ha.state("light.lamp") == "off" and ha.state("sensor.t") == "21.5"
    assert ha.attribute("sensor.t", "unit_of_measurement") == "°C"


async def test_toggle_waits_for_the_new_state(ha_pair):
    fake, ha = ha_pair
    seen = []
    ha.add_listener(lambda e, old, new: seen.append((e, old, new)))
    await asyncio.wait_for(ha.toggle("light.lamp"), 2)
    assert ha.state("light.lamp") == "on" and seen == [("light.lamp", "off", "on")]
    call = fake.calls[-1]
    assert (call["domain"], call["service"], call["target"]) == ("homeassistant", "toggle",
                                                                 {"entity_id": "light.lamp"})


async def test_toggle_without_answer_times_out_in_the_caller(ha_pair):
    fake, ha = ha_pair
    fake.answer_toggle = False
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ha.toggle("light.lamp"), 0.2)
    assert not ha._waiters


async def test_unknown_and_unavailable_entities_fail_at_once(ha_pair):
    _, ha = ha_pair
    with pytest.raises(LookupError):
        await ha.toggle("light.nope")
    with pytest.raises(HAError, match="unavailable"):
        await ha.toggle("light.dead")


async def test_scripts_scenes_and_events(ha_pair):
    fake, ha = ha_pair
    await ha.run_script("script.closet_5min")
    await ha.run_script("scene.evening")
    await ha.fire_event("tablo_button", {"button": 3, "press": "long"})
    assert [(c["type"], c.get("domain"), c.get("service")) for c in fake.calls] == [
        ("call_service", "script", "turn_on"), ("call_service", "scene", "turn_on"), ("fire_event", None, None)]
    assert fake.calls[-1]["event_data"] == {"button": 3, "press": "long"}
    with pytest.raises(HAError, match="not a script"):
        await ha.run_script("light.lamp")
    with pytest.raises(HAError, match="no such service"):
        await ha.call_service("bogus", "x")


async def test_lost_connection_keeps_states_and_reconnects(ha_pair):
    fake, ha = ha_pair
    changes = []
    ha.add_status_listener(lambda: changes.append(ha.connected))
    await fake.sockets[0].close()
    await _until(lambda: not ha.connected)
    assert ha.state("light.lamp") == "off"  # last known, shown on screen (§11)
    with pytest.raises(HAError, match="not connected"):
        await ha.toggle("light.lamp")
    await _until(lambda: ha.connected, timeout=4)
    assert changes == [False, True]


async def test_bad_token_is_reported(aiohttp_server):
    fake = FakeServer()
    app = web.Application()
    app.router.add_get("/api/websocket", fake.handle)
    server = await aiohttp_server(app)
    ha = HomeAssistant(str(server.make_url("")), "wrong")
    task = asyncio.create_task(ha.run())
    await _until(lambda: ha.error is not None)
    task.cancel()
    assert "Invalid access token" in ha.error and not ha.connected and not ha.ready


# --- Home block ---------------------------------------------------------------

def _printer_ha(state, progress="42", left="1.33", unit="h"):
    ha = FakeHA()
    ha.states.update({"sensor.printer_current_print_state": state, "sensor.printer_progress": progress,
                      "sensor.printer_print_time_left": left})
    ha.attrs["sensor.printer_print_time_left"] = {"unit_of_measurement": unit}
    return ha


@pytest.mark.parametrize("state, unit, expected", [
    ("printing", "h", ("printing", "42% · 1:20")),
    ("printing", "min", ("printing", "42% · 0:01")),
    ("printing", "s", ("printing", "42% · 0:00")),
    ("printing", None, ("printing", "42%")),
    ("paused", "h", ("paused", "42%")),
    ("standby", "h", ("idle", "")),
    ("complete", "h", ("done", "")),
    ("unavailable", "h", ("off", "")),
])
def test_printer_line(state, unit, expected):
    assert builder.printer(_printer_ha(state, unit=unit), CFG.home.printer) == expected


def test_home_block_from_config():
    ha = _printer_ha("printing")
    home = builder.home(ha, CFG)
    assert (home.temp, home.humidity, home.lights_on, home.lights_total) == (22.4, 45, 3, 5)
    assert builder.home(ha, config.Config()).printer is None  # no printer configured: no row
    ha.ready = False
    assert builder.home(ha, CFG) is None
