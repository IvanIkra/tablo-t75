"""Device triggers "Tablo: button N, short / long press" from the `tablo_button` event (§8.2)."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import BUTTON_EVENT, BUTTONS, DOMAIN, PRESSES

CONF_SUBTYPE = "subtype"
TRIGGER_TYPES = {f"{press}_press": press for press in PRESSES}
SUBTYPES = [f"button_{n}" for n in BUTTONS]

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend({
    vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
    vol.Required(CONF_SUBTYPE): vol.In(SUBTYPES),
})


async def async_get_triggers(hass: HomeAssistant, device_id: str) -> list[dict[str, str]]:
    return [
        {CONF_PLATFORM: "device", CONF_DOMAIN: DOMAIN, CONF_DEVICE_ID: device_id,
         CONF_TYPE: trigger_type, CONF_SUBTYPE: subtype}
        for subtype in SUBTYPES for trigger_type in TRIGGER_TYPES
    ]


async def async_attach_trigger(hass: HomeAssistant, config: ConfigType, action: TriggerActionType,
                               trigger_info: TriggerInfo) -> CALLBACK_TYPE:
    """Fires for any action of the button, "event only" included, and for button 8 too."""
    event_config = event_trigger.TRIGGER_SCHEMA({
        event_trigger.CONF_PLATFORM: "event",
        event_trigger.CONF_EVENT_TYPE: BUTTON_EVENT,
        event_trigger.CONF_EVENT_DATA: {
            "button": int(config[CONF_SUBTYPE].removeprefix("button_")),
            "press": TRIGGER_TYPES[config[CONF_TYPE]],
        },
    })
    return await event_trigger.async_attach_trigger(hass, event_config, action, trigger_info,
                                                    platform_type="device")
