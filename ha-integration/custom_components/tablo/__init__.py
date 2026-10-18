"""Tablo T75: buttons, sources and to-do lists of the e-ink panel in Home Assistant (§8)."""

from __future__ import annotations

import copy

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import TabloApi, TabloError
from .const import CHANGED_EVENT, CONF_API_TOKEN, CONF_URL, DOMAIN, LOGIN_NOTIFICATION, OPT_CONFIG, SOURCES
from .coordinator import TabloCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.TODO]

type TabloConfigEntry = ConfigEntry[TabloCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SHOW_QR_SCHEMA = vol.Schema({
    vol.Optional("networks"): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
})
SHOW_MESSAGE_SCHEMA = vol.Schema({
    vol.Required("title"): cv.string,
    vol.Optional("text", default=""): cv.string,
    vol.Optional("icon"): cv.icon,
    vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
})
REFRESH_DATA_SCHEMA = vol.Schema({vol.Optional("sources"): vol.All(cv.ensure_list, [vol.In(SOURCES)])})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """The `tablo.*` actions (§8.4)."""

    def coordinator() -> TabloCoordinator:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                return entry.runtime_data
        raise ServiceValidationError("Tablo is not connected", translation_domain=DOMAIN,
                                     translation_key="not_loaded")

    async def call(coro) -> None:
        try:
            await coro
        except TabloError as e:
            raise HomeAssistantError(f"Tablo: {e}") from e

    async def show_qr(call_: ServiceCall) -> None:
        await call(coordinator().api.show_qr(call_.data.get("networks"), call_.data.get("duration")))

    async def show_message(call_: ServiceCall) -> None:
        d = call_.data
        await call(coordinator().api.show_message(d["title"], d["text"], d.get("icon"), d.get("duration")))

    async def full_refresh(call_: ServiceCall) -> None:
        await call(coordinator().api.refresh(full=True))

    async def refresh_data(call_: ServiceCall) -> None:
        await call(coordinator().api.refresh(refetch=True, sources=call_.data.get("sources")))

    hass.services.async_register(DOMAIN, "show_qr", show_qr, SHOW_QR_SCHEMA)
    hass.services.async_register(DOMAIN, "show_message", show_message, SHOW_MESSAGE_SCHEMA)
    hass.services.async_register(DOMAIN, "full_refresh", full_refresh, vol.Schema({}))
    hass.services.async_register(DOMAIN, "refresh_data", refresh_data, REFRESH_DATA_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TabloConfigEntry) -> bool:
    api = TabloApi(async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_API_TOKEN])
    coordinator = TabloCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Tablo",
        manufacturer="Tablo",
        model="T75",
        configuration_url=api.url + "/emu",
    )

    @callback
    def on_changed(event: Event) -> None:
        hass.async_create_task(coordinator.async_request_refresh())

    entry.async_on_unload(hass.bus.async_listen(CHANGED_EVENT, on_changed))
    entry.async_on_unload(coordinator.async_add_listener(lambda: _login_notice(hass, entry)))
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    _login_notice(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TabloConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _options_updated(hass: HomeAssistant, entry: TabloConfigEntry) -> None:
    """The forms already sent their config; this catches options changed any other way."""
    coordinator = entry.runtime_data
    config = entry.options.get(OPT_CONFIG, {})
    if config != coordinator.pushed:
        try:
            await coordinator.push_config(copy.deepcopy(config))
        except TabloError:
            coordinator.pushed = None  # sent again with the next successful poll


@callback
def _login_notice(hass: HomeAssistant, entry: TabloConfigEntry) -> None:
    """the university app needs a new login (§7.2): a notification with the link to the login page."""
    coordinator = entry.runtime_data
    if coordinator.data is None:
        return
    needed = bool(coordinator.data.status.get("hseapp", {}).get("login_needed"))
    if needed == coordinator.login_needed:
        return  # once per change: a dismissed notification does not come back every poll
    coordinator.login_needed = needed
    if needed:
        url = f"{entry.data[CONF_URL]}/hseapp?api_token={entry.data[CONF_API_TOKEN]}"
        persistent_notification.async_create(
            hass,
            f"The login to the university app has expired, so the panel shows no deadlines from it. "
            f"[Log in again]({url}) in any browser.",
            title="Tablo: HSE login needed",
            notification_id=LOGIN_NOTIFICATION,
        )
    else:
        persistent_notification.async_dismiss(hass, LOGIN_NOTIFICATION)
