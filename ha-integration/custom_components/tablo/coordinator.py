"""Status and deadlines of the service, refreshed by `tablo_changed` events and a slow poll (§8.1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TabloApi, TabloAuthError, TabloError
from .const import DOMAIN, OPT_CONFIG, POLL_SECONDS

_LOGGER = logging.getLogger(__name__)


@dataclass
class TabloData:
    status: dict
    deadlines: list[dict]


class TabloCoordinator(DataUpdateCoordinator[TabloData]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: TabloApi) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN,
                         update_interval=timedelta(seconds=POLL_SECONDS))
        self.api = api
        self.pushed: dict | None = None  # the config the service has from us; None = send it again
        self.login_needed: bool | None = None  # the university app state the notification was last made for

    async def push_config(self, config: dict | None = None) -> None:
        config = config if config is not None else self.config_entry.options.get(OPT_CONFIG, {})
        await self.api.put_config(config)
        self.pushed = config

    async def _async_update_data(self) -> TabloData:
        try:
            # After HA start or the service coming back, the service gets the config again (§8.1).
            if self.pushed is None:
                await self.push_config()
            return TabloData(await self.api.status(), await self.api.deadlines())
        except TabloAuthError as e:
            raise ConfigEntryAuthFailed(str(e)) from e
        except TabloError as e:
            self.pushed = None
            raise UpdateFailed(str(e)) from e
