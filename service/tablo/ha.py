"""Home Assistant access.

Stage 1 only has `FakeHA`: an in-memory house with a few lights, so buttons can
be tried in the emulator. The real WebSocket client (stage 6) will expose the
same methods.
"""

import asyncio
import logging
from collections.abc import Callable

log = logging.getLogger(__name__)

StateListener = Callable[[str, str | None, str], None]

LIGHTS = (
    "light.ceiling_light",
    "light.desk_lamp",
    "light.desk_light",
    "light.desk_backlight",
    "light.closet_light",
)


class FakeHA:
    # Cloud Tuya devices answer slowly in real life; imitate that.
    SLOW = ("light.desk_light", "light.desk_backlight")

    def __init__(self, fast_delay: float = 0.3, slow_delay: float = 2.0):
        self.connected = True
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
        }
        self._listeners: list[StateListener] = []
        self.events: list[tuple[str, dict]] = []

    def add_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def state(self, entity: str) -> str | None:
        return self.states.get(entity)

    async def toggle(self, entity: str) -> None:
        if entity not in self.states:
            raise LookupError(f"unknown entity {entity}")
        new = "off" if self.states[entity] == "on" else "on"
        await asyncio.sleep(self.slow_delay if entity in self.SLOW else self.fast_delay)
        self._set(entity, new)

    async def run_script(self, entity: str) -> None:
        await asyncio.sleep(self.fast_delay)
        if entity in ("script.all_lights_off", "script.leaving_home"):
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
