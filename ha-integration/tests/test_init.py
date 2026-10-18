"""Connecting, importing the config, entities, actions and the HSE login notice."""

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from tablo import config as service_config

from custom_components.tablo.const import DOMAIN, LOGIN_NOTIFICATION, OPT_CONFIG
from .conftest import TOKEN


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


async def test_llm_sensors_show_the_last_runs(hass: HomeAssistant, entry, hub):
    import datetime as dt
    assert hass.states.get("sensor.tablo_llm_run_news").state == "unknown"
    at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    hub._on_llm_run({"at": at, "task": "news", "model": "claude-haiku-5-5", "ok": True, "error": None,
                     "input_tokens": 3000, "output_tokens": 200, "cache_write": 0, "cache_read": 0,
                     "cost_usd": 0.0004, "duration_s": 3.2})
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    news = hass.states.get("sensor.tablo_llm_run_news")
    assert news.state != "unknown"
    assert (news.attributes["input_tokens"], news.attributes["cost_usd"], news.attributes["duration_s"]) == (
        3000, 0.0004, 3.2)
    assert hass.states.get("sensor.tablo_llm_run_grades").state == "unknown"
    cost = hass.states.get("sensor.tablo_llm_cost_today")
    assert float(cost.state) == 0.0004 and cost.attributes["runs"] == 1


async def service_client(service):
    from aiohttp.test_utils import TestClient
    client = TestClient(service)
    await client.start_server()
    return client


async def test_hse_login_notice(hass: HomeAssistant, entry, hub):
    # The test service has the university app on and no login.
    notices = persistent_notification._async_get_or_create_notifications(hass)
    assert LOGIN_NOTIFICATION in notices
    assert "/hseapp?api_token=" in notices[LOGIN_NOTIFICATION]["message"]
    hub.cfg.hseapp.enabled = False
    await entry.runtime_data.async_refresh()
    assert LOGIN_NOTIFICATION not in notices


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
    await hass.services.async_call(DOMAIN, "refresh_data", {"sources": ["news", "grades"]}, blocking=True)
    await hass.services.async_call(DOMAIN, "refresh_data", {}, blocking=True)
    await hass.services.async_call(DOMAIN, "full_refresh", {}, blocking=True)
    assert calls == [("message", "Hi", "there", "mdi:bell", 10), ("qr", ["Home"], None)]
    assert refetched == [["news", "grades"], None]


async def test_config_is_pushed_again_after_the_service_restarts(hass: HomeAssistant, entry, hub):
    coordinator = entry.runtime_data
    hub.cfg.buttons = []  # as if the service had lost what HA sent
    coordinator.pushed = None  # what a failed poll leaves
    await coordinator.async_refresh()
    assert hub.cfg.button(2).short.entity == "light.ceiling_light"
