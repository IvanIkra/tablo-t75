"""Home Assistant access (§7.6, §8.1).

`HomeAssistant` is the real client: one WebSocket, `subscribe_entities` for
states, `render_template` for the Home rows (§8.3), `script/config` for how long a
running script lasts, `call_service` for buttons, `fire_event` for `tablo_button`. `FakeHA` is an in-memory house with the same
methods, for the emulator and tests. States and template results survive a lost
connection: the screen shows the last known ones (§11).
"""

import asyncio
import contextlib
import datetime as dt
import logging
import math
from collections.abc import Callable

import aiohttp
from jinja2 import TemplateError, Undefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

log = logging.getLogger(__name__)

StateListener = Callable[[str, str | None, str | None], None]
StatusListener = Callable[[], None]

LIGHTS = (
    "light.ceiling_light",
    "light.desk_lamp",
    "light.desk_light",
    "light.desk_backlight",
    "light.closet_light",
)

# What a "script" button action calls, by domain of its entity.
RUN_SERVICES = {
    "script": "turn_on",  # returns at once, also for scripts with a delay
    "scene": "turn_on",
    "automation": "trigger",
    "button": "press",
    "input_button": "press",
}
COMMAND_TIMEOUT_S = 10
RETRY_S = (1, 2, 5, 10, 30, 60)
AUTH_RETRY_S = 300  # a bad token stays bad; do not hammer HA's login ban


# Steps that keep a script running; "delay" is the only one whose length can be known in advance.
WAIT_STEPS = ("delay", "wait_template", "wait_for_trigger")


def _delay_s(value) -> float | None:
    """A fixed `delay` in seconds: "HH:MM", "HH:MM:SS", seconds, or {hours: …, minutes: …}; None for a template."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        units = {"days": 86400, "hours": 3600, "minutes": 60, "seconds": 1, "milliseconds": 0.001}
        if not set(value) <= set(units):
            return None
        parts = [_delay_s(v) for v in value.values()]
        if None in parts:
            return None
        return sum(units[k] * part for k, part in zip(value, parts, strict=True))
    if isinstance(value, str) and "{" not in value:
        try:
            parts = [float(p) for p in value.strip().split(":")]
        except ValueError:
            return None
        if len(parts) == 1:
            return parts[0]
        if len(parts) in (2, 3):  # as HA reads it: "HH:MM" or "HH:MM:SS"
            return sum(p * f for p, f in zip(parts, (3600, 60, 1), strict=False))
    return None


def _waits(value) -> bool:
    if isinstance(value, dict):
        return any(k in WAIT_STEPS for k in value) or any(_waits(v) for v in value.values())
    if isinstance(value, list):
        return any(_waits(v) for v in value)
    return False


def script_length(sequence) -> float:
    """How long a script runs, from its `sequence` (§8.3): 0 when it never waits (done in a moment), the sum
    of its delays when they are all fixed and at the top level, inf when it waits for something it cannot
    know in advance: a template delay, a trigger, a delay inside a choose or a repeat."""
    if sequence is None:
        return math.inf  # e.g. a script from a blueprint: no sequence in its config
    total = 0.0
    for step in sequence if isinstance(sequence, list) else [sequence]:
        if isinstance(step, dict) and "delay" in step:
            seconds = _delay_s(step["delay"])
            if seconds is None:
                return math.inf
            total += seconds
        elif _waits(step):
            return math.inf
    return total


class HAError(RuntimeError):
    pass


class _AuthError(HAError):
    pass


def not_connected() -> HAError:
    return HAError("Home Assistant is not connected")


class HomeAssistant:
    def __init__(self, url: str, token: str):
        base = url.rstrip("/")
        self.ws_url = ("ws" + base[4:] if base.startswith("http") else base) + "/api/websocket"
        self.token = token
        self.connected = False
        self.ready = False  # a full list of states has arrived at least once
        self.error: str | None = None
        self.states: dict[str, str] = {}
        self.attrs: dict[str, dict] = {}
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._waiters: dict[str, list[asyncio.Future]] = {}
        self._listeners: list[StateListener] = []
        self._status_listeners: list[StatusListener] = []
        self.templates: dict[str, str | None] = {}  # template -> last result; None = error or not rendered yet
        self._wanted: list[str] = []
        self._template_ids: dict[int, str] = {}  # subscription id -> template, on the current connection
        self.script_lengths: dict[str, float] = {}  # script -> seconds (see script_length), asked when it starts
        self._tasks: set[asyncio.Task] = set()

    # --- reading ----------------------------------------------------------------

    def add_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def add_status_listener(self, listener: StatusListener) -> None:
        self._status_listeners.append(listener)

    def state(self, entity: str) -> str | None:
        return self.states.get(entity)

    def attribute(self, entity: str, name: str):
        return self.attrs.get(entity, {}).get(name)

    def template(self, template: str) -> str | None:
        return self.templates.get(template)

    def script_length(self, entity: str) -> float | None:
        """None until HA has told how the script is made (asked each time it starts)."""
        return self.script_lengths.get(entity)

    async def _ask_script(self, entity: str) -> None:
        try:
            result = await self._command({"type": "script/config", "entity_id": entity})
            config = (result or {}).get("config") or {}
            length = script_length(config.get("sequence"))
        except (HAError, asyncio.TimeoutError) as e:
            log.warning("script %s: no config (%s); shown without the time left", entity, e)
            length = math.inf
        old = self.script_lengths.get(entity)
        self.script_lengths[entity] = length
        if old != length:
            for listener in self._listeners:
                listener(f"script:{entity}", None, None)

    def set_templates(self, templates: list[str]) -> None:
        """Keep these templates rendered by HA: subscribe to new ones, drop the rest."""
        wanted = list(dict.fromkeys(t for t in templates if t))
        if wanted == self._wanted:
            return
        self._wanted = wanted
        for t in list(self.templates):
            if t not in wanted:
                del self.templates[t]
        if self.connected and self._ws is not None:
            with contextlib.suppress(RuntimeError):  # no event loop: subscribed on the next connection
                task = asyncio.get_running_loop().create_task(self._sync_templates(self._ws))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _sync_templates(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        current = {t: sub for sub, t in self._template_ids.items()}
        for t, sub in current.items():
            if t not in self._wanted:
                del self._template_ids[sub]
                with contextlib.suppress(HAError, asyncio.TimeoutError):
                    await self._command({"type": "unsubscribe_events", "subscription": sub})
        for t in self._wanted:
            if t not in current:
                await self._subscribe_template(ws, t)

    async def _subscribe_template(self, ws: aiohttp.ClientWebSocketResponse, template: str) -> None:
        self._next_id += 1
        self._template_ids[self._next_id] = template
        await ws.send_json({"id": self._next_id, "type": "render_template", "template": template,
                            "report_errors": True})

    def _template_result(self, template: str, value: str | None) -> None:
        old = self.templates.get(template)
        self.templates[template] = value
        if old != value:
            for listener in self._listeners:
                listener(f"template:{template}", old, value)

    # --- actions ----------------------------------------------------------------

    async def toggle(self, entity: str) -> None:
        """Toggle and wait until HA reports the new state: the tile shows the real one (§4.2)."""
        if not self.connected:
            raise not_connected()
        old = self.states.get(entity)
        if old is None:
            raise LookupError(f"unknown entity {entity}")
        if old == "unavailable":
            raise HAError(f"{entity} is unavailable")
        changed = asyncio.get_running_loop().create_future()
        self._waiters.setdefault(entity, []).append(changed)
        try:
            await self.call_service("homeassistant", "toggle", entity)
            await changed
        finally:
            self._waiters[entity].remove(changed)
            if not self._waiters[entity]:
                del self._waiters[entity]

    async def run_script(self, entity: str) -> None:
        domain = entity.split(".", 1)[0]
        if domain not in RUN_SERVICES:
            raise HAError(f"cannot run {entity}: not a script, scene, automation or button")
        await self.call_service(domain, RUN_SERVICES[domain], entity)

    async def call_service(self, domain: str, service: str, entity: str | None = None,
                           data: dict | None = None) -> None:
        msg = {"type": "call_service", "domain": domain, "service": service}
        if entity:
            msg["target"] = {"entity_id": entity}
        if data:
            msg["service_data"] = data
        await self._command(msg)

    async def fire_event(self, event_type: str, data: dict) -> None:
        await self._command({"type": "fire_event", "event_type": event_type, "event_data": data})

    async def _command(self, msg: dict):
        ws = self._ws
        if not self.connected or ws is None:
            raise not_connected()
        self._next_id += 1
        msg_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        try:
            await ws.send_json({"id": msg_id, **msg})
            return await asyncio.wait_for(future, COMMAND_TIMEOUT_S)
        finally:
            self._pending.pop(msg_id, None)

    # --- connection -------------------------------------------------------------

    async def run(self) -> None:
        """Keep the connection up for as long as the service runs."""
        failures = 0
        while True:
            delay = RETRY_S[min(failures, len(RETRY_S) - 1)]
            try:
                async with aiohttp.ClientSession() as session:
                    # The first list of states is every entity in the house: allow a big message.
                    async with session.ws_connect(self.ws_url, heartbeat=30, max_msg_size=32 << 20) as ws:
                        await self._session(ws)
                        failures = 0
                self.error = "connection closed"
            except _AuthError as e:
                self.error, delay = str(e), AUTH_RETRY_S
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, KeyError, TypeError) as e:
                self.error = f"{type(e).__name__}: {e}"
            finally:
                self._ws = None
                self._set_connected(False)
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(not_connected())
            log.warning("Home Assistant: %s; retrying in %d s", self.error, delay)
            failures += 1
            await asyncio.sleep(delay)

    async def _session(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        hello = await ws.receive_json(timeout=10)
        if hello.get("type") != "auth_required":
            raise ValueError(f"unexpected greeting {hello.get('type')!r}")
        await ws.send_json({"type": "auth", "access_token": self.token})
        answer = await ws.receive_json(timeout=10)
        if answer.get("type") != "auth_ok":
            raise _AuthError(f"login refused: {answer.get('message') or answer.get('type')}")

        self._next_id += 1
        sub_id = self._next_id
        await ws.send_json({"id": sub_id, "type": "subscribe_entities"})
        self._template_ids = {}
        for template in self._wanted:
            await self._subscribe_template(ws, template)
        self._ws = ws
        self.error = None
        self._set_connected(True)
        log.info("Home Assistant connected: %s", self.ws_url)
        first = True
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                if msg.type == aiohttp.WSMsgType.ERROR:
                    raise ConnectionError(str(ws.exception()))
                continue
            item = msg.json()
            template = self._template_ids.get(item.get("id"))
            if item.get("type") == "event" and item.get("id") == sub_id:
                self._apply(item["event"], full=first)
                first = False
            elif template is not None:
                self._template_message(template, item)
            elif item.get("type") == "result":
                self._result(item, item.get("id") == sub_id)

    def _template_message(self, template: str, item: dict) -> None:
        """A `render_template` answer: the rendered text, or an error (shown as no row)."""
        if item.get("type") == "result":
            if not item.get("success"):
                log.warning("Home template %r refused: %s", template, (item.get("error") or {}).get("message"))
                self._template_result(template, None)
            return
        event = item.get("event") or {}
        if "error" in event:
            if event.get("level") == "ERROR":
                log.warning("Home template %r: %s", template, event["error"])
                self._template_result(template, None)
            return
        result = event.get("result")
        self._template_result(template, None if result is None else str(result))

    def _result(self, item: dict, subscription: bool) -> None:
        if subscription:
            if not item.get("success"):
                raise HAError(f"subscribe_entities failed: {item.get('error')}")
            return
        future = self._pending.get(item.get("id"))
        if future is None or future.done():
            return
        if item.get("success"):
            future.set_result(item.get("result"))
        else:
            error = item.get("error") or {}
            future.set_exception(HAError(error.get("message") or error.get("code") or "call failed"))

    def _apply(self, event: dict, full: bool) -> None:
        """One `subscribe_entities` event: "a" adds (the first one lists every entity), "c" changes, "r" removes."""
        old_states = dict(self.states)
        if full:
            self.states, self.attrs = {}, {}
        for entity, s in (event.get("a") or {}).items():
            self.states[entity] = s.get("s")
            self.attrs[entity] = dict(s.get("a") or {})
        for entity, change in (event.get("c") or {}).items():
            plus, minus = change.get("+") or {}, change.get("-") or {}
            if "s" in plus:
                self.states[entity] = plus["s"]
            attrs = self.attrs.setdefault(entity, {})
            attrs.update(plus.get("a") or {})
            for name in minus.get("a") or ():
                attrs.pop(name, None)
        for entity in event.get("r") or ():
            self.states.pop(entity, None)
            self.attrs.pop(entity, None)
        if full:
            self.ready = True
        for entity in old_states.keys() | self.states.keys():
            old, new = old_states.get(entity), self.states.get(entity)
            if old != new:
                self._changed(entity, old, new)

    def _changed(self, entity: str, old: str | None, new: str | None) -> None:
        for future in self._waiters.get(entity, ()):
            if not future.done():
                future.set_result(new)
        if entity.startswith("script.") and new == "on" and self.connected:
            # Its config may have changed since the last run: ask every time.
            task = asyncio.get_running_loop().create_task(self._ask_script(entity))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        for listener in self._listeners:
            listener(entity, old, new)

    def _set_connected(self, connected: bool) -> None:
        if self.connected == connected:
            return
        self.connected = connected
        for listener in self._status_listeners:
            listener()


class FakeHA:
    # Cloud Tuya devices answer slowly in real life; imitate that.
    SLOW = ("light.desk_light", "light.desk_backlight")

    def __init__(self, fast_delay: float = 0.3, slow_delay: float = 2.0):
        self.connected = True
        self.ready = True
        self.error = None
        self.fast_delay = fast_delay
        self.slow_delay = slow_delay
        self.states: dict[str, str] = {
            "light.ceiling_light": "on",
            "light.desk_lamp": "on",
            "light.desk_light": "off",
            "light.desk_backlight": "on",
            "light.closet_light": "off",
            "switch.vpn_ap": "off",
            "sensor.room_sensor_temperature": "22.4",
            "sensor.room_sensor_humidity": "45",
            "sensor.printer_current_print_state": "printing",
            "sensor.printer_progress": "42",
            "sensor.printer_print_time_left": "1.33",
            "script.closet_5min": "off",
        }
        self.attrs: dict[str, dict] = {
            "sensor.printer_print_time_left": {"unit_of_measurement": "h"},
            "script.closet_5min": {"friendly_name": "Tablo · Closet for 5 min"},
        }
        self.script_lengths: dict[str, float] = {"script.closet_5min": 300.0}
        self._script_tasks: dict[str, asyncio.Task] = {}
        self._listeners: list[StateListener] = []
        self.events: list[tuple[str, dict]] = []
        self._jinja = _fake_jinja(self)

    def add_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def add_status_listener(self, listener: StatusListener) -> None:
        pass  # always connected

    def state(self, entity: str) -> str | None:
        return self.states.get(entity)

    def attribute(self, entity: str, name: str):
        return self.attrs.get(entity, {}).get(name)

    def script_length(self, entity: str) -> float | None:
        return self.script_lengths.get(entity, 0.0 if entity in self.states else None)

    def set_templates(self, templates: list[str]) -> None:
        pass  # rendered on demand from the current states

    def template(self, template: str) -> str | None:
        """Like HA would render it, for the functions Home rows use; None on an error."""
        try:
            return self._jinja.from_string(template).render()
        except (TemplateError, ValueError, TypeError, KeyError, ZeroDivisionError) as e:
            log.info("fake HA: template %r: %s", template, e)
            return None

    async def toggle(self, entity: str) -> None:
        if entity not in self.states:
            raise LookupError(f"unknown entity {entity}")
        new = "off" if self.states[entity] == "on" else "on"
        await asyncio.sleep(self.slow_delay if entity in self.SLOW else self.fast_delay)
        self._set(entity, new)

    async def run_script(self, entity: str) -> None:
        await asyncio.sleep(self.fast_delay)
        if entity == "script.all_lights_on":
            for light in LIGHTS:
                self._set(light, "on")
        elif entity in ("script.all_lights_off", "script.leaving_home"):
            for light in LIGHTS:
                self._set(light, "off")
            if entity == "script.leaving_home":
                self._set("switch.vpn_ap", "off")
        elif entity == "script.closet_5min":
            self._set("light.closet_light", "on")
            self.start_script(entity)
        else:
            log.info("fake HA: script %s has no effect here", entity)

    def start_script(self, entity: str, at: dt.datetime | None = None) -> None:
        """Run a script with a known length, like HA in "restart" mode: a second start begins it again."""
        at = at or dt.datetime.now(dt.UTC)
        self.attrs.setdefault(entity, {})["last_triggered"] = at.isoformat()
        old = self._script_tasks.pop(entity, None)
        if old:
            old.cancel()
        with contextlib.suppress(RuntimeError):  # no event loop (tests): stays on until stopped by hand
            self._script_tasks[entity] = asyncio.get_running_loop().create_task(self._finish_script(entity))
        if self.states.get(entity) == "on":
            for listener in self._listeners:
                listener(entity, "on", "on")  # restarted: the time left changes
        self._set(entity, "on")

    async def _finish_script(self, entity: str) -> None:
        await asyncio.sleep(self.script_lengths.get(entity, 0.0))
        self._script_tasks.pop(entity, None)
        if entity == "script.closet_5min":
            self._set("light.closet_light", "off")
        self._set(entity, "off")

    async def fire_event(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, data))
        log.info("fake HA event %s %s", event_type, data)

    def _set(self, entity: str, new: str) -> None:
        old = self.states.get(entity)
        if old == new:
            return
        self.states[entity] = new
        for listener in self._listeners:
            listener(entity, old, new)


def _fake_jinja(ha: FakeHA) -> ImmutableSandboxedEnvironment:
    """The part of HA's template language the Home rows need: states, attributes and number filters."""
    env = ImmutableSandboxedEnvironment()

    def number(value, default=None, cast=float):
        try:
            result = float(value)
            if math.isnan(result):
                raise ValueError
            return cast(result)
        except (TypeError, ValueError):
            if default is not None:
                return default
            raise ValueError(f"{value!r} is not a number") from None

    def is_state(entity, state):
        return ha.states.get(entity) in (state if isinstance(state, (list, tuple)) else [state])

    env.globals.update(
        states=lambda entity: ha.states.get(entity, "unknown"),
        is_state=is_state,
        state_attr=lambda entity, name: ha.attrs.get(entity, {}).get(name),
        is_number=lambda value: number(value, default=False) is not False,
    )
    env.filters.update(
        float=lambda value, default=None: number(value, default),
        int=lambda value, default=None: number(value, default, cast=int),
        round=lambda value, precision=0, *args, default=None: round(number(value, default), precision),
    )
    env.tests["is_state"] = is_state
    env.undefined = Undefined
    return env
