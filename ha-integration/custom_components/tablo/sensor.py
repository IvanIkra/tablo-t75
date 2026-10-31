"""Wi-Fi level, the last contact of the panel and the sticky messages on it (§8.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TabloConfigEntry
from .entity import TabloEntity

async def async_setup_entry(hass: HomeAssistant, entry: TabloConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities([SignalSensor(coordinator, "wifi_signal"), LastContactSensor(coordinator, "last_contact"),
                        MessagesSensor(coordinator, "messages")])


class SignalSensor(TabloEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> int | None:
        return self.panel.get("rssi")


class LastContactSensor(TabloEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> datetime | None:
        seen = self.panel.get("last_seen")
        return dt_util.parse_datetime(seen) if seen else None


class MessagesSensor(TabloEntity, SensorEntity):
    """How many sticky messages wait for a button; their titles, oldest first, in `messages`."""

    @property
    def _messages(self) -> list[dict]:
        return self.coordinator.data.status.get("messages", [])

    @property
    def native_value(self) -> int:
        return len(self._messages)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"messages": self._messages}
