"""Device triggers "button N, short / long press" (§8.2)."""

from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_get_device_automations, async_mock_service

from custom_components.tablo.const import DOMAIN


async def test_triggers_listed_and_fired(hass: HomeAssistant, entry):
    device = dr.async_get(hass).async_get_device({(DOMAIN, entry.entry_id)})
    triggers = await async_get_device_automations(hass, DeviceAutomationType.TRIGGER, device.id)
    assert len([t for t in triggers if t["domain"] == DOMAIN]) == 16
    calls = async_mock_service(hass, "test", "pressed")
    assert await async_setup_component(hass, automation.DOMAIN, {automation.DOMAIN: [{
        "triggers": [{"platform": "device", "domain": DOMAIN, "device_id": device.id,
                      "type": "long_press", "subtype": "button_3"}],
        "actions": [{"action": "test.pressed"}],
    }]})
    hass.bus.async_fire("tablo_button", {"button": 3, "press": "short"})
    hass.bus.async_fire("tablo_button", {"button": 2, "press": "long"})
    await hass.async_block_till_done()
    assert calls == []
    hass.bus.async_fire("tablo_button", {"button": 3, "press": "long"})
    await hass.async_block_till_done()
    assert len(calls) == 1
