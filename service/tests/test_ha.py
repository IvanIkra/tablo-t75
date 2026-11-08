"""Home Assistant WebSocket client against a fake HA, and the Home block built from its states."""

import asyncio
import datetime as dt
import math
from pathlib import Path

import pytest
from aiohttp import WSMsgType, web

from tablo import builder, config
from tablo.ha import FakeHA, HAError, HomeAssistant, script_length

TOKEN = "good-token"
CFG = config.load(Path(__file__).resolve().parents[1] / "config.yaml", local=False)


class FakeServer:
    """Speaks just enough of HA's WebSocket API: auth, subscribe_entities, render_template, call_service,
    fire_event. A template renders to what `results` maps it to; "BAD" in it is a syntax error."""

    def __init__(self):
        self.states = {
            "light.lamp": {"s": "off", "a": {"friendly_name": "Lamp"}},
            "light.dead": {"s": "unavailable", "a": {}},
            "sensor.t": {"s": "21.5", "a": {"unit_of_measurement": "°C"}},
            "script.closet": {"s": "off", "a": {"friendly_name": "Closet"}},
        }
        self.scripts = {"script.closet": {"sequence": [{"action": "light.turn_on"}, {"delay": "00:05:00"}]}}
        self.calls: list[dict] = []
        self.sockets: list[web.WebSocketResponse] = []
        self.sub_id = None
        self.answer_toggle = True
        self.results: dict[str, str] = {}
        self.template_subs: dict[int, str] = {}  # live render_template subscriptions

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
            elif m["type"] == "render_template":
                if "BAD" in m["template"]:
                    await ws.send_json({"id": m["id"], "type": "result", "success": False,
                                        "error": {"code": "template_error", "message": "unexpected end"}})
                    continue
                self.template_subs[m["id"]] = m["template"]
                await ws.send_json({"id": m["id"], "type": "result", "success": True, "result": None})
                await ws.send_json({"id": m["id"], "type": "event",
                                    "event": {"result": self.results.get(m["template"], ""), "listeners": {}}})
            elif m["type"] == "script/config":
                self.calls.append(m)
                await ws.send_json({"id": m["id"], "type": "result", "success": True,
                                    "result": {"config": self.scripts[m["entity_id"]]}})
            elif m["type"] == "unsubscribe_events":
                self.template_subs.pop(m["subscription"], None)
                await ws.send_json({"id": m["id"], "type": "result", "success": True, "result": None})
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

    async def rerender(self, template, result):
        self.results[template] = result
        for sub, t in self.template_subs.items():
            if t == template:
                for ws in self.sockets:
                    if not ws.closed:
                        await ws.send_json({"id": sub, "type": "event", "event": {"result": result, "listeners": {}}})

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


async def test_a_started_script_is_asked_how_long_it_runs(ha_pair):
    fake, ha = ha_pair
    seen = []
    ha.add_listener(lambda e, old, new: seen.append(e))
    assert ha.script_length("script.closet") is None
    await fake.change("script.closet", "on")
    await _until(lambda: ha.script_length("script.closet") == 300)
    assert {"type": "script/config", "entity_id": "script.closet"} in [
        {k: v for k, v in c.items() if k != "id"} for c in fake.calls]
    assert "script:script.closet" in seen  # the screen is drawn again with the time left


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

async def test_templates_are_kept_rendered_by_ha(ha_pair):
    fake, ha = ha_pair
    fake.results = {"{{ a }}": "21.4° · 42%", "{{ b }}": "3 of 5"}
    seen = []
    ha.add_listener(lambda e, old, new: seen.append(e))
    ha.set_templates(["{{ a }}", "{{ b }}", "{{ BAD"])
    await _until(lambda: ha.template("{{ a }}") == "21.4° · 42%" and ha.template("{{ b }}") == "3 of 5")
    assert ha.template("{{ BAD") is None and "template:{{ a }}" in seen
    await fake.rerender("{{ a }}", "21.5° · 42%")  # an entity inside changed: HA sends the new result
    await _until(lambda: ha.template("{{ a }}") == "21.5° · 42%")
    ha.set_templates(["{{ b }}"])  # a row removed in HA: its subscription goes
    await _until(lambda: sorted(fake.template_subs.values()) == ["{{ b }}"])
    assert ha.template("{{ a }}") is None


async def test_templates_survive_a_lost_connection_and_resubscribe(ha_pair):
    fake, ha = ha_pair
    fake.results = {"{{ a }}": "on"}
    ha.set_templates(["{{ a }}"])
    await _until(lambda: ha.template("{{ a }}") == "on")
    await fake.sockets[0].close()
    await _until(lambda: not ha.connected)
    assert ha.template("{{ a }}") == "on"  # last known, shown on screen (§11)
    fake.results["{{ a }}"] = "off"
    await _until(lambda: ha.connected and ha.template("{{ a }}") == "off", timeout=4)


def _printer_ha(state, progress="42", left="1.33", unit="h"):
    ha = FakeHA()
    ha.states.update({"sensor.printer_current_print_state": state, "sensor.printer_progress": progress,
                      "sensor.printer_print_time_left": left})
    ha.attrs["sensor.printer_print_time_left"] = {"unit_of_measurement": unit} if unit else {}
    return ha


@pytest.mark.parametrize("state, unit, expected", [
    ("printing", "h", "42% · 1:20"),
    ("printing", "min", "42% · 0:01"),
    ("printing", "s", "42% · 0:00"),
    ("printing", None, None),  # unknown unit: template error, no row
    ("paused", "h", "paused · 42%"),
    ("standby", "h", "idle"),
    ("cancelled", "h", "idle"),
    ("complete", "h", "done"),
    ("error", "h", "error"),
    ("unavailable", "h", "off"),  # the Klipper host or the printer is off
])
def test_default_printer_row(state, unit, expected):
    printer = CFG.home.rows[2]
    assert printer.label == "printer"
    assert _printer_ha(state, unit=unit).template(printer.template) == expected


def test_home_block_shows_rows_that_gave_something():
    ha = _printer_ha("printing")
    home = builder.home(ha, CFG)
    assert [(r.label, r.value) for r in home.rows] == [("", "22.4° · 45%"), ("lights", "3 of 5"),
                                                      ("printer", "42% · 1:20")]
    ha.states["sensor.printer_current_print_state"] = "standby"
    ha.states["sensor.room_sensor_temperature"] = "unavailable"
    assert [(r.label, r.value) for r in builder.home(ha, CFG).rows] == [("lights", "3 of 5"), ("printer", "idle")]
    ha.ready = False
    assert builder.home(ha, CFG) is None


def test_old_home_settings_become_the_same_rows():
    old = {"temperature": "sensor.room_sensor_temperature",
           "humidity": "sensor.room_sensor_humidity",
           "lights": ["light.ceiling_light", "light.desk_lamp",
                      "light.desk_light", "light.desk_backlight", "light.closet_light"],
           "printer": {"state": "sensor.printer_current_print_state", "progress": "sensor.printer_progress",
                       "time_left": "sensor.printer_print_time_left"}}
    assert config.from_dict({"home": old}).home.rows == CFG.home.rows
    with_rows = config.from_dict({"home": {**old, "rows": [{"label": "door", "template": "{{ 1 }}"}]}})
    assert [(r.label, r.template) for r in with_rows.home.rows] == [("door", "{{ 1 }}")]


@pytest.mark.parametrize("home, error", [
    ({"rows": [{"label": "x", "template": " "}]}, "needs a template"),
    ({"rows": [{"label": "a|b", "template": "{{ 1 }}"}]}, "cannot have"),
    ({"rows": [{"template": "{{ 1 }}"}] * 6}, "at most 5"),
    ({"rows": [], "colour": "red"}, "unknown keys"),
])
def test_bad_home_rows_are_refused(home, error):
    with pytest.raises(config.ConfigError, match=error):
        config.from_dict({"home": home})


@pytest.mark.parametrize(("sequence", "seconds"), [
    ([{"action": "light.turn_on"}], 0),
    ({"action": "light.turn_on"}, 0),
    ([{"delay": "00:05:00"}, {"action": "light.turn_off"}], 300),
    ([{"delay": "01:30"}], 5400),  # HA reads two parts as hours and minutes
    ([{"delay": 90}, {"delay": "45"}], 135),
    ([{"delay": {"minutes": 2, "seconds": 30}}], 150),
    ([{"delay": "{{ states('input_number.minutes') | int }}:00"}], math.inf),
    ([{"delay": {"minutes": "{{ 5 }}"}}], math.inf),
    ([{"wait_for_trigger": [{"trigger": "state"}]}], math.inf),
    ([{"choose": [{"sequence": [{"delay": 10}]}]}], math.inf),
    (None, math.inf),  # no sequence: a blueprint script
])
def test_script_length(sequence, seconds):
    assert script_length(sequence) == seconds


NOW = dt.datetime(2026, 11, 9, 12, 0)  # local time, as the builder gets it
UTC_NOW = NOW.replace(tzinfo=dt.timezone(dt.timedelta(hours=3))).astimezone(dt.UTC)  # Europe/Moscow


def test_home_block_shows_running_scripts_with_the_time_left():
    ha = FakeHA()
    assert builder.home(ha, CFG, NOW).scripts == ()
    ha.start_script("script.closet_5min", at=UTC_NOW - dt.timedelta(seconds=90))
    home = builder.home(ha, CFG, NOW)
    assert [(r.label, r.value) for r in home.scripts] == [("Closet for 5 min", "4 min left")]
    assert builder.home(ha, CFG, NOW + dt.timedelta(minutes=3, seconds=29)).scripts[0].value == "1 min left"
    assert builder.home(ha, CFG, NOW + dt.timedelta(minutes=4)).scripts[0].value == "running"  # off any moment

    ha.script_lengths["script.closet_5min"] = 2 * 3600
    assert builder.home(ha, CFG, NOW).scripts[0].value == "1:59 left"
    ha.script_lengths["script.closet_5min"] = math.inf  # waits for a trigger
    assert builder.home(ha, CFG, NOW).scripts[0].value == "running"

    ha.states["script.quick"] = "on"  # no waits: on for a moment, never a row
    ha.states["script.new"] = "on"
    ha.script_lengths["script.new"] = None  # HA not asked yet
    assert [r.label for r in builder.home(ha, CFG, NOW).scripts] == ["Closet for 5 min"]
    ha.states["script.closet_5min"] = "off"
    assert builder.home(ha, CFG, NOW).scripts == ()
