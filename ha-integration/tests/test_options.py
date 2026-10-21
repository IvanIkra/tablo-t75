"""The "Configure" forms: each one reaches the service at once (§8.2, §8.3)."""

from homeassistant.core import HomeAssistant

from custom_components.tablo.const import OPT_BOT, OPT_CONFIG


async def _open(hass: HomeAssistant, entry, step: str):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    return await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})


async def test_button_form(hass: HomeAssistant, entry, hub):
    result = await _open(hass, entry, "buttons")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"button": "6"})
    assert result["step_id"] == "button"
    # The form starts from the button as it is.
    short = result["data_schema"].schema["short"].schema.schema
    entity = next(k for k in short if k == "entity")
    assert entity.description["suggested_value"] == "light.closet_light"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "tile": "never",
        "short": {"action": "message", "title": "Dinner", "text": "Come", "duration_s": 15},
        "long": {"action": "qr", "networks": ["Home"]},
    })
    assert result["type"] == "create_entry", result
    b = hub.cfg.button(6)
    assert (b.short.action, b.short.title, b.short.duration_s) == ("message", "Dinner", 15)
    assert b.long.networks == ["Home"] and b.tile == "none"
    assert b.icon == "mdi:help"  # no icon and no entity
    assert entry.options[OPT_CONFIG]["buttons"][5]["short"]["action"] == "message"


async def test_button_icon_from_entity(hass: HomeAssistant, entry, hub):
    hass.states.async_set("light.closet_light", "off")
    result = await _open(hass, entry, "buttons")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"button": "6"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "tile": "auto",
        "short": {"action": "toggle", "entity": "light.closet_light"},
        "long": {"action": "event"},
    })
    assert result["type"] == "create_entry"
    assert hub.cfg.button(6).icon == "mdi:lightbulb"
    assert hub.cfg.button(6).tile_entity == "light.closet_light"


async def test_button_errors_keep_the_form(hass: HomeAssistant, entry, hub):
    result = await _open(hass, entry, "buttons")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"button": "2"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "tile": "auto", "short": {"action": "script", "entity": "light.ceiling_light"},
        "long": {"action": "none"},
    })
    assert result["type"] == "form" and result["errors"] == {"base": "rejected"}
    assert "not a script" in result["description_placeholders"]["error"]
    assert hub.cfg.button(2).short.action == "toggle"


async def test_sources_form(hass: HomeAssistant, entry, hub):
    result = await _open(hass, entry, "sources")
    fields = {k.schema for k in result["data_schema"].schema}
    assert fields == {"ical_url", "latitude", "longitude", "bot"}  # the rest is in infomaster's Mini App
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "ical_url": "http://infomaster:8081/calendar/s/tablo.ics",
        "latitude": 55.75,
        "longitude": 37.62,
        "bot": "@example_bot",
    })
    assert result["type"] == "create_entry", result
    assert hub.cfg.ical.url == "http://infomaster:8081/calendar/s/tablo.ics"
    assert hub.cfg.weather.latitude == 55.75
    assert entry.options[OPT_BOT] == "example_bot" and OPT_BOT not in entry.options[OPT_CONFIG]
    # Another form keeps the bot.
    result = await _open(hass, entry, "wifi")
    await hass.config_entries.options.async_configure(result["flow_id"], {"networks": "Home | pw"})
    assert entry.options[OPT_BOT] == "example_bot"


async def test_wifi_home_screen(hass: HomeAssistant, entry, hub):
    result = await _open(hass, entry, "wifi")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "networks": "Home | pw | WPA\nGuest"})
    assert result["type"] == "create_entry"
    assert [(n.ssid, n.security) for n in hub.cfg.wifi_networks] == [("Home", "WPA"), ("Guest", "nopass")]

    result = await _open(hass, entry, "home")
    rows_field = next(k for k in result["data_schema"].schema if k == "rows")
    assert "lights | {{" in rows_field.description["suggested_value"]  # the service's rows, from config.yaml
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "rows": "| {{ states('sensor.t') }}°\ndoor | {{ 'open' if is_state('binary_sensor.door', 'on') }}"})
    assert result["type"] == "create_entry"
    assert [(r.label, r.template) for r in hub.cfg.home.rows] == [
        ("", "{{ states('sensor.t') }}°"), ("door", "{{ 'open' if is_state('binary_sensor.door', 'on') }}")]

    result = await _open(hass, entry, "home")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"rows": "door | {{ states("})
    assert result["errors"] == {"base": "rejected"}
    assert "row 1" in result["description_placeholders"]["error"]

    result = await _open(hass, entry, "screen")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "semester_start": "2027-01-11", "full_refresh_at": "03:30:00", "font_mode": "threshold",
        "long_press_ms": 700, "qr_duration_s": 25, "message_duration_s": 40})
    assert result["type"] == "create_entry"
    d = hub.cfg.display
    assert (str(d.semester_start), d.full_refresh_at, d.font_mode, d.long_press_ms) == (
        "2027-01-11", "03:30", "threshold", 700)
    assert hub.cfg.qr_duration_s == 25
