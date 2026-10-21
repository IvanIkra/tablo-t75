"""Connecting, importing the config, migration, entities, actions, the HSE login notice and the brand images."""

from pathlib import Path

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from tablo import config as service_config

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tablo.const import DOMAIN, LOGIN_NOTIFICATION, OPT_BOT, OPT_CONFIG
from .conftest import TOKEN

BRAND = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN / "brand"


async def test_flow_imports_the_service_config(hass: HomeAssistant, entry, hub):
    assert entry.options[OPT_CONFIG] == service_config.to_dict(hub.cfg)
    assert entry.options[OPT_CONFIG]["buttons"][1]["short"] == {"action": "toggle",
                                                                 "entity": "light.ceiling_light"}
    device = dr.async_get(hass).async_get_device({(DOMAIN, entry.entry_id)})
    assert device.model == "T75"


async def test_flow_errors(hass: HomeAssistant, url):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": url, "api_token": "wrong"})
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": "http://127.0.0.1:9", "api_token": TOKEN})
    assert result["errors"] == {"base": "cannot_connect"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": url, "api_token": TOKEN})
    assert result["type"] == "create_entry"
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    again = await hass.config_entries.flow.async_configure(again["flow_id"], {"url": url + "/", "api_token": TOKEN})
    assert again["type"] == "abort" and again["reason"] == "already_configured"


async def test_entities_follow_the_panel(hass: HomeAssistant, entry, service):
    assert hass.states.get("binary_sensor.tablo_connected").state == "off"
    assert hass.states.get("sensor.tablo_last_contact").state == "unknown"
    client = await service_client(service)
    ws = await client.ws_connect("/ws?device=panel&token=dev-device-token")
    await ws.send_json({"type": "hello", "fw": "test", "rssi": -61})
    await ws.receive(timeout=5)  # config: the hello is handled
    # The service fires tablo_changed into its own (fake) HA; here the event is fired by hand.
    hass.bus.async_fire("tablo_changed", {"kind": "status"})
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    assert hass.states.get("binary_sensor.tablo_connected").state == "on"
    assert hass.states.get("sensor.tablo_wi_fi_signal").state == "-61"
    assert hass.states.get("sensor.tablo_last_contact").state != "unknown"
    await ws.close()
    await client.close()


async def test_no_todo_lists_or_llm_sensors(hass: HomeAssistant, entry):
    assert not hass.states.async_entity_ids("todo")
    assert not [e for e in hass.states.async_entity_ids("sensor") if "llm" in e]


async def service_client(service):
    from aiohttp.test_utils import TestClient
    client = TestClient(service)
    await client.start_server()
    return client


def _uni_status(hub, **hseapp):
    hub.store.put_json("infomaster.status", {"fetched_at": hub.now().isoformat(), "data": {"hseapp": hseapp}})


async def test_hse_login_notice_links_the_bot(hass: HomeAssistant, entry, hub):
    notices = persistent_notification._async_get_or_create_notifications(hass)
    assert LOGIN_NOTIFICATION not in notices  # nothing known from infomaster yet
    hass.config_entries.async_update_entry(entry, options={**entry.options, OPT_BOT: "example_bot"})
    _uni_status(hub, login_needed=True, logged_in=False)
    await entry.runtime_data.async_refresh()
    assert "https://t.me/example_bot?start=hseapp" in notices[LOGIN_NOTIFICATION]["message"]
    _uni_status(hub, login_needed=False, logged_in=True)
    await entry.runtime_data.async_refresh()
    assert LOGIN_NOTIFICATION not in notices


async def test_old_source_settings_are_dropped_on_migration(hass: HomeAssistant, url, hub):
    config = service_config.to_dict(hub.cfg)
    config.update(grades={"student": "Ivanov Ivan", "sheets": []}, hseapp={"enabled": True},
                  news={"channels": [{"name": "example_news3", "study": False}]}, mail={"enabled": True},
                  subjects=[{"name": "Матан", "title": "Calculus", "abbr": "Calc"}])
    config["ical"] = {"url": "http://infomaster:8081/calendar/s/tablo.ics", "poll_minutes": 60}
    old = MockConfigEntry(domain=DOMAIN, version=1, minor_version=1, data={"url": url, "api_token": TOKEN},
                          options={OPT_CONFIG: config})
    old.add_to_hass(hass)
    assert await hass.config_entries.async_setup(old.entry_id)
    await hass.async_block_till_done()
    assert old.minor_version == 2
    assert not {"grades", "hseapp", "news", "mail", "subjects"} & set(old.options[OPT_CONFIG])
    assert old.runtime_data.pushed == old.options[OPT_CONFIG]  # the service took it
    assert hub.cfg.ical.url.endswith("tablo.ics")


async def test_actions(hass: HomeAssistant, entry, hub, monkeypatch):
    calls = []

    async def show_message(title, text, icon=None, duration_s=None):
        calls.append(("message", title, text, icon, duration_s))

    async def show_qr(ssids=None, duration_s=None):
        calls.append(("qr", ssids, duration_s))

    monkeypatch.setattr(hub, "show_message", show_message)
    monkeypatch.setattr(hub, "show_qr", show_qr)
    refetched = []
    monkeypatch.setattr(hub, "refetch", lambda sources=None: refetched.append(sources))
    await hass.services.async_call(DOMAIN, "show_message", {"title": "Hi", "text": "there", "icon": "mdi:bell",
                                                            "duration": 10}, blocking=True)
    await hass.services.async_call(DOMAIN, "show_qr", {"networks": "Home"}, blocking=True)
    await hass.services.async_call(DOMAIN, "refresh_data", {"sources": ["infomaster", "weather"]}, blocking=True)
    await hass.services.async_call(DOMAIN, "refresh_data", {}, blocking=True)
    await hass.services.async_call(DOMAIN, "full_refresh", {}, blocking=True)
    assert calls == [("message", "Hi", "there", "mdi:bell", 10), ("qr", ["Home"], None)]
    assert refetched == [["infomaster", "weather"], None]


async def test_config_is_pushed_again_after_the_service_restarts(hass: HomeAssistant, entry, hub):
    coordinator = entry.runtime_data
    hub.cfg.buttons = []  # as if the service had lost what HA sent
    coordinator.pushed = None  # what a failed poll leaves
    await coordinator.async_refresh()
    assert hub.cfg.button(2).short.entity == "light.ceiling_light"


async def test_brand_images_served(hass: HomeAssistant, hass_client):
    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()
    for image in ("icon.png", "logo@2x.png", "dark_icon.png", "dark_logo.png"):
        resp = await client.get(f"/api/brands/integration/{DOMAIN}/{image}")
        assert resp.status == 200, image
        assert await resp.read() == (BRAND / image).read_bytes(), image
