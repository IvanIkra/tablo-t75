"""Base of the Tablo entities: one device per service."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TabloCoordinator


class TabloEntity(CoordinatorEntity[TabloCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: TabloCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)})

    @property
    def panel(self) -> dict:
        return self.coordinator.data.status.get("panel", {})
