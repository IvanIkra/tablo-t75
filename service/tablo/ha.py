"""Home Assistant access (§7.6, §8.1).

`HomeAssistant` is the real client: one WebSocket, `subscribe_entities` for
states, `call_service` for buttons, `fire_event` for `tablo_button`. `FakeHA`
is an in-memory house with the same methods, for the emulator and tests.
States survive a lost connection: the screen shows the last known ones (§11).
"""

import asyncio
import logging
from collections.abc import Callable

import aiohttp

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

    # --- reading ----------------------------------------------------------------

    def add_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def add_status_listener(self, listener: StatusListener) -> None:
        self._status_listeners.append(listener)

    def state(self, entity: str) -> str | None:
        return self.states.get(entity)

    def attribute(self, entity: str, name: str):
        return self.attrs.get(entity, {}).get(name)

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
            if item.get("type") == "event" and item.get("id") == sub_id:
                self._apply(item["event"], full=first)
                first = False
            elif item.get("type") == "result":
                self._result(item, item.get("id") == sub_id)

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
        }
        self.attrs: dict[str, dict] = {"sensor.printer_print_time_left": {"unit_of_measurement": "h"}}
        self._listeners: list[StateListener] = []
        self.events: list[tuple[str, dict]] = []

    def add_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def add_status_listener(self, listener: StatusListener) -> None:
        pass  # always connected

    def state(self, entity: str) -> str | None:
        return self.states.get(entity)

    def attribute(self, entity: str, name: str):
        return self.attrs.get(entity, {}).get(name)

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
        else:
            log.info("fake HA: script %s has no effect here", entity)

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
