"""The integration talks to the real service, started in the test's loop with the fake house."""

from pathlib import Path

import pytest
from aiohttp.test_utils import TestServer
from homeassistant.core import HomeAssistant
from tablo import config as service_config
from tablo.app import HUB, create_app
from tablo.ha import FakeHA

from custom_components.tablo.const import DOMAIN

SERVICE_CONFIG = Path(__file__).resolve().parents[2] / "service" / "config.yaml"
TOKEN = "dev-api-token"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
async def service(hass: HomeAssistant, tmp_path, socket_enabled):
    cfg = service_config.load(SERVICE_CONFIG, local=False)
    app = create_app(cfg, FakeHA(fast_delay=0, slow_delay=0), data_dir=tmp_path, periodic=False)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    yield server
    await server.close()


@pytest.fixture
def hub(service):
    return service.app[HUB]


@pytest.fixture
def url(service) -> str:
    return str(service.make_url("")).rstrip("/")


@pytest.fixture
async def entry(hass: HomeAssistant, url):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": url, "api_token": TOKEN})
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    return result["result"]
