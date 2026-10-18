"""Wi-Fi level and the last contact of the panel, the service's Haiku runs (§6.6, §8.4)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TabloConfigEntry
from .const import LLM_TASKS
from .entity import TabloEntity

LLM_ATTRIBUTES = ("model", "ok", "error", "input_tokens", "output_tokens", "cache_write", "cache_read",
                  "cost_usd", "duration_s")


async def async_setup_entry(hass: HomeAssistant, entry: TabloConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    async_add_entities([SignalSensor(coordinator, "wifi_signal"), LastContactSensor(coordinator, "last_contact"),
                        *(LlmRunSensor(coordinator, task) for task in LLM_TASKS),
                        LlmCostTodaySensor(coordinator, "llm_cost_today")])


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


class LlmRunSensor(TabloEntity, SensorEntity):
    """Last Haiku run for one task: its time, and tokens, cost and duration as attributes."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, task: str) -> None:
        super().__init__(coordinator, f"llm_{task}")
        self.task = task

    @property
    def run(self) -> dict | None:
        return (self.coordinator.data.status.get("llm") or {}).get("tasks", {}).get(self.task)

    @property
    def native_value(self) -> datetime | None:
        run = self.run
        return dt_util.parse_datetime(run["at"]) if run else None

    @property
    def extra_state_attributes(self) -> dict:
        run = self.run or {}
        return {name: run.get(name) for name in LLM_ATTRIBUTES} if run else {}


class LlmCostTodaySensor(TabloEntity, SensorEntity):
    """What Haiku cost since midnight, with the number of runs and tokens."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "USD"
    _attr_suggested_display_precision = 4
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def today(self) -> dict:
        return (self.coordinator.data.status.get("llm") or {}).get("today") or {}

    @property
    def native_value(self) -> float | None:
        return self.today.get("cost_usd")

    @property
    def extra_state_attributes(self) -> dict:
        return {"runs": self.today.get("runs"), "tokens": self.today.get("tokens")}
