"""The panel's theme, for dashboards and automations (§8.4); the Screen form sets it too."""

from __future__ import annotations

import copy

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TabloConfigEntry
from .api import TabloError
from .const import DEFAULT_THEME, OPT_CONFIG, THEMES
from .entity import TabloEntity


async def async_setup_entry(hass: HomeAssistant, entry: TabloConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([ThemeSelect(entry.runtime_data, "theme")])


class ThemeSelect(TabloEntity, SelectEntity):
    _attr_options = list(THEMES)
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def current_option(self) -> str:
        return self.coordinator.config_entry.options.get(OPT_CONFIG, {}).get("display", {}).get("theme",
                                                                                               DEFAULT_THEME)

    async def async_select_option(self, option: str) -> None:
        entry = self.coordinator.config_entry
        config = copy.deepcopy(entry.options.get(OPT_CONFIG, {}))
        config.setdefault("display", {})["theme"] = option
        try:
            await self.coordinator.push_config(copy.deepcopy(config))
        except TabloError as e:
            raise HomeAssistantError(f"Tablo: {e}") from e
        # Saved after the service took it, so the options listener has nothing left to send.
        self.hass.config_entries.async_update_entry(entry, options={**entry.options, OPT_CONFIG: config})
        self.async_write_ha_state()
