"""Whether the panel is connected to the service (§8.4)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TabloConfigEntry
from .entity import TabloEntity


async def async_setup_entry(hass: HomeAssistant, entry: TabloConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([ConnectedSensor(entry.runtime_data, "connected")])


class ConnectedSensor(TabloEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool:
        return bool(self.panel.get("connected"))
