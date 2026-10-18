"""Connecting to the service, and the "Configure" forms: buttons, Wi-Fi, sources, home, screen (§8.2, §8.3)."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)
from homeassistant.helpers.template import Template

from . import forms
from .api import TabloApi, TabloAuthError, TabloError
from .const import ACTIONS, CONF_API_TOKEN, CONF_URL, CONFIGURABLE_BUTTONS, DEFAULT_URL, DOMAIN, OPT_CONFIG, RUN_DOMAINS

# Shown and saved when the icon field is left empty and the entity has no icon of its own (§8.2).
DOMAIN_ICONS = {
    "light": "mdi:lightbulb",
    "switch": "mdi:toggle-switch",
    "fan": "mdi:fan",
    "cover": "mdi:window-shutter",
    "script": "mdi:script-text",
    "scene": "mdi:palette",
    "automation": "mdi:robot",
    "button": "mdi:gesture-tap-button",
    "input_button": "mdi:gesture-tap-button",
    "input_boolean": "mdi:toggle-switch",
    "media_player": "mdi:speaker",
    "climate": "mdi:thermostat",
}
DEFAULT_ICON = "mdi:help"

MULTILINE = TextSelector(TextSelectorConfig(multiline=True))
URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _number(lo: float, hi: float, unit: str | None = None, step: float | str = 1) -> NumberSelector:
    config = NumberSelectorConfig(min=lo, max=hi, step=step, mode=NumberSelectorMode.BOX)
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _select(options: list[str], key: str | None = None, multiple: bool = False) -> SelectSelector:
    config = SelectSelectorConfig(options=options, multiple=multiple, mode=SelectSelectorMode.DROPDOWN)
    if key:
        config["translation_key"] = key
    return SelectSelector(config)


def _entity(domain: str | list[str] | None = None, multiple: bool = False) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=domain, multiple=multiple) if domain
                          else EntitySelectorConfig(multiple=multiple))


def _clean(values: Mapping[str, Any]) -> dict[str, Any]:
    """Suggested values without empty ones: an empty string would show as a chosen "nothing"."""
    return {k: v for k, v in values.items() if v not in (None, "", [])}


class TabloConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            await self.async_set_unique_id(url)
            self._abort_if_unique_id_configured()
            api = TabloApi(async_get_clientsession(self.hass), url, user_input[CONF_API_TOKEN])
            try:
                # The integration starts from what the service has now: nothing is typed again (§8.1).
                config = await api.get_config()
            except TabloAuthError:
                errors["base"] = "invalid_auth"
            except TabloError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title="Tablo T75",
                    data={CONF_URL: url, CONF_API_TOKEN: user_input[CONF_API_TOKEN]},
                    options={OPT_CONFIG: config},
                )
        schema = vol.Schema({
            vol.Required(CONF_URL, default=DEFAULT_URL): URL,
            vol.Required(CONF_API_TOKEN): PASSWORD,
        })
        return self.async_show_form(step_id="user", data_schema=self.add_suggested_values_to_schema(
            schema, user_input or {}), errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            api = TabloApi(async_get_clientsession(self.hass), entry.data[CONF_URL], user_input[CONF_API_TOKEN])
            try:
                await api.get_config()
            except TabloAuthError:
                errors["base"] = "invalid_auth"
            except TabloError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(step_id="reauth_confirm", errors=errors,
                                    data_schema=vol.Schema({vol.Required(CONF_API_TOKEN): PASSWORD}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TabloOptionsFlow:
        return TabloOptionsFlow()


class TabloOptionsFlow(OptionsFlow):
    """Each form is saved on its own and sent to the service: the screen changes at once (§8.2)."""

    def __init__(self) -> None:
        self._cfg: dict | None = None
        self._button: int | None = None

    @property
    def cfg(self) -> dict:
        if self._cfg is None:
            self._cfg = copy.deepcopy(dict(self.config_entry.options.get(OPT_CONFIG, {})))
        return self._cfg

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["buttons", "wifi", "sources", "home", "screen"])

    def _api(self) -> TabloApi:
        entry = self.config_entry
        return TabloApi(async_get_clientsession(self.hass), entry.data[CONF_URL], entry.data[CONF_API_TOKEN])

    async def _save(self) -> str | None:
        """Send the config to the service, which checks it; returns its complaint, if any."""
        entry = self.config_entry
        api = self._api()
        try:
            await api.put_config(self.cfg)
        except TabloError as e:
            return str(e)
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None:
            coordinator.pushed = copy.deepcopy(self.cfg)
        return None

    async def _finish(self, step_id: str, schema: vol.Schema, user_input: dict, apply) -> ConfigFlowResult:
        """Apply the form to the config, send it, and end the flow; or show the form again with the error."""
        before = copy.deepcopy(self.cfg)
        try:
            apply(user_input)
            error = await self._save()
        except forms.FormError as e:
            error = str(e)
        if error is None:
            return self.async_create_entry(data={OPT_CONFIG: self.cfg})
        self._cfg = before
        return self.async_show_form(step_id=step_id, data_schema=self.add_suggested_values_to_schema(
            schema, user_input), errors={"base": "rejected"}, description_placeholders={"error": error})

    # --- buttons ---------------------------------------------------------------

    def _buttons(self) -> dict[int, dict]:
        return {b["id"]: b for b in self.cfg.get("buttons", [])}

    async def async_step_buttons(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._button = int(user_input["button"])
            return await self.async_step_button()
        buttons = self._buttons()
        options = []
        for n in CONFIGURABLE_BUTTONS:
            b = buttons.get(n, {})
            what = b.get("short", {}).get("entity") or b.get("short", {}).get("action", "none")
            options.append({"value": str(n), "label": f"{n} · {b.get('icon', '—')} · {what}"})
        schema = vol.Schema({vol.Required("button", default="1"): SelectSelector(SelectSelectorConfig(
            options=options, mode=SelectSelectorMode.LIST))})
        return self.async_show_form(step_id="buttons", data_schema=schema)

    def _action_schema(self) -> vol.Schema:
        fields: dict = {
            vol.Required("action", default="none"): _select(list(ACTIONS), "action"),
            vol.Optional("entity"): _entity(),
        }
        ssids = [w["ssid"] for w in self.cfg.get("wifi_networks", [])]
        if ssids:
            fields[vol.Optional("networks")] = _select(ssids, multiple=True)
        fields[vol.Optional("duration_s")] = _number(5, 600, "s")
        fields[vol.Optional("title")] = TextSelector()
        fields[vol.Optional("text")] = MULTILINE
        return vol.Schema(fields)

    def _button_schema(self) -> vol.Schema:
        return vol.Schema({
            vol.Optional("icon"): IconSelector(),
            vol.Required("tile", default="auto"): _select(["auto", "entity", "never"], "tile"),
            vol.Optional("tile_entity"): _entity(),
            vol.Required("short"): section(self._action_schema(), {"collapsed": False}),
            vol.Required("long"): section(self._action_schema(), {"collapsed": False}),
        })

    async def async_step_button(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        n = self._button or 1
        schema = self._button_schema()
        if user_input is not None:
            return await self._finish("button", schema, user_input, lambda data: self._apply_button(n, data))
        b = self._buttons().get(n, {"id": n})
        tile = b.get("tile")
        values = {
            "icon": b.get("icon"),
            "tile": "never" if tile == "none" else "entity" if tile else "auto",
            "tile_entity": tile if tile and tile != "none" else None,
            "short": _clean(b.get("short", {})),
            "long": _clean(b.get("long", {})),
        }
        return self.async_show_form(step_id="button", data_schema=self.add_suggested_values_to_schema(
            schema, _clean(values)), description_placeholders={"button": str(n)})

    def _action(self, data: Mapping[str, Any], where: str) -> dict:
        action = data.get("action", "none")
        out: dict[str, Any] = {"action": action}
        entity = data.get("entity")
        if action in ("toggle", "script"):
            if not entity:
                raise forms.FormError(f"{where}: choose an entity for '{action}'")
            if action == "script" and entity.split(".", 1)[0] not in RUN_DOMAINS:
                raise forms.FormError(f"{where}: {entity} is not a script, scene, automation or button")
            out["entity"] = entity
        if action == "qr" and data.get("networks"):
            out["networks"] = list(data["networks"])
        if action in ("qr", "message") and data.get("duration_s"):
            out["duration_s"] = int(data["duration_s"])
        if action == "message":
            out["title"], out["text"] = data.get("title", ""), data.get("text", "")
        return out

    def _icon(self, data: Mapping[str, Any], short: dict, long: dict) -> str:
        """Empty icon field: the icon of the entity, else one for its domain."""
        if data.get("icon"):
            return data["icon"]
        entity = short.get("entity") or long.get("entity")
        if not entity:
            return DEFAULT_ICON
        state = self.hass.states.get(entity)
        icon = state.attributes.get("icon") if state else None
        return icon or DOMAIN_ICONS.get(entity.split(".", 1)[0], DEFAULT_ICON)

    def _apply_button(self, n: int, data: Mapping[str, Any]) -> None:
        short = self._action(data.get("short", {}), "Short press")
        long = self._action(data.get("long", {}), "Long press")
        button: dict[str, Any] = {"id": n, "icon": self._icon(data, short, long)}
        match data.get("tile", "auto"):
            case "never":
                button["tile"] = "none"
            case "entity":
                if not data.get("tile_entity"):
                    raise forms.FormError("Tile: choose the entity whose state lights it")
                button["tile"] = data["tile_entity"]
        button["short"], button["long"] = short, long
        buttons = self._buttons()
        buttons[n] = button
        self.cfg["buttons"] = [buttons[k] for k in sorted(buttons)]

    # --- Wi-Fi -----------------------------------------------------------------

    async def async_step_wifi(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = vol.Schema({vol.Optional("networks"): MULTILINE})
        if user_input is not None:
            def apply(data):
                self.cfg["wifi_networks"] = forms.wifi_from_text(data.get("networks", ""))
            return await self._finish("wifi", schema, user_input, apply)
        values = {"networks": forms.wifi_to_text(self.cfg.get("wifi_networks", []))}
        return self.async_show_form(step_id="wifi", data_schema=self.add_suggested_values_to_schema(
            schema, _clean(values)))

    # --- sources ---------------------------------------------------------------

    def _sources_schema(self) -> vol.Schema:
        return vol.Schema({
            vol.Optional("ical_url"): URL,
            vol.Optional("hseapp"): BooleanSelector(),
            vol.Optional("student"): TextSelector(),
            vol.Optional("sheets"): MULTILINE,
            vol.Optional("window_days"): _number(1, 60, "d"),
            vol.Optional("channels"): MULTILINE,
            vol.Optional("ttl_hours"): _number(1, 168, "h"),
            vol.Optional("mail"): BooleanSelector(),
            vol.Optional("subjects"): MULTILINE,
            vol.Optional("latitude"): _number(-90, 90, "°", "any"),
            vol.Optional("longitude"): _number(-180, 180, "°", "any"),
        })

    async def async_step_sources(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = self._sources_schema()
        if user_input is not None:
            return await self._finish("sources", schema, user_input, self._apply_sources)
        c = self.cfg
        grades, news, weather = c.get("grades", {}), c.get("news", {}), c.get("weather", {})
        values = {
            "ical_url": c.get("ical", {}).get("url"),
            "hseapp": c.get("hseapp", {}).get("enabled", True),
            "student": grades.get("student"),
            "sheets": forms.sheets_to_text(grades.get("sheets", [])),
            "window_days": grades.get("window_days", 7),
            "channels": forms.channels_to_text(news.get("channels", [])),
            "ttl_hours": news.get("ttl_hours", 24),
            "mail": c.get("mail", {}).get("enabled", True),
            "subjects": forms.subjects_to_text(c.get("subjects", [])),
            "latitude": weather.get("latitude"),
            "longitude": weather.get("longitude"),
        }
        return self.async_show_form(step_id="sources", data_schema=self.add_suggested_values_to_schema(
            schema, _clean(values)))

    def _apply_sources(self, data: Mapping[str, Any]) -> None:
        c = self.cfg
        c.setdefault("ical", {})["url"] = data.get("ical_url", "").strip()
        c.setdefault("hseapp", {})["enabled"] = bool(data.get("hseapp", False))
        grades = c.setdefault("grades", {})
        grades["student"] = data.get("student", "").strip()
        grades["sheets"] = forms.sheets_from_text(data.get("sheets", ""))
        grades["window_days"] = int(data.get("window_days", 7))
        news = c.setdefault("news", {})
        news["channels"] = forms.channels_from_text(data.get("channels", ""))
        news["ttl_hours"] = int(data.get("ttl_hours", 24))
        c.setdefault("mail", {})["enabled"] = bool(data.get("mail", False))
        c["subjects"] = forms.subjects_from_text(data.get("subjects", ""))
        weather = c.setdefault("weather", {})
        for key in ("latitude", "longitude"):
            if data.get(key) is not None:
                weather[key] = float(data[key])

    # --- home ------------------------------------------------------------------

    async def async_step_home(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Rows of HA templates (§8.3): the service subscribes to them, an empty result hides the row."""
        schema = vol.Schema({vol.Optional("rows"): MULTILINE})
        if user_input is not None:
            def apply(data):
                rows = forms.home_rows_from_text(data.get("rows", ""))
                for n, row in enumerate(rows, 1):
                    try:
                        Template(row["template"], self.hass).ensure_valid()
                    except TemplateError as e:
                        raise forms.FormError(f"row {n}: {e}") from e
                self.cfg["home"] = {"rows": rows}
            return await self._finish("home", schema, user_input, apply)
        rows = self.cfg.get("home", {}).get("rows")
        if rows is None:
            # Saved before the rows existed: the service has already turned the old fields into rows.
            try:
                rows = (await self._api().get_config()).get("home", {}).get("rows", [])
            except TabloError:
                rows = []
        return self.async_show_form(step_id="home", data_schema=self.add_suggested_values_to_schema(
            schema, _clean({"rows": forms.home_rows_to_text(rows)})))

    # --- screen ----------------------------------------------------------------

    async def async_step_screen(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        schema = vol.Schema({
            vol.Required("semester_start"): DateSelector(),
            vol.Required("full_refresh_at"): TimeSelector(),
            vol.Required("font_mode"): _select(["aliased", "threshold"], "font_mode"),
            vol.Required("long_press_ms"): _number(300, 3000, "ms", 50),
            vol.Required("qr_duration_s"): _number(5, 600, "s"),
            vol.Required("message_duration_s"): _number(5, 600, "s"),
        })
        if user_input is not None:
            def apply(data):
                display = self.cfg.setdefault("display", {})
                display["semester_start"] = data["semester_start"]
                display.setdefault("full_refresh", {})["at"] = data["full_refresh_at"][:5]
                display["font_mode"] = data["font_mode"]
                display["long_press_ms"] = int(data["long_press_ms"])
                overlays = self.cfg.setdefault("overlays", {})
                overlays["qr_duration_s"] = int(data["qr_duration_s"])
                overlays["message_duration_s"] = int(data["message_duration_s"])
            return await self._finish("screen", schema, user_input, apply)
        display = self.cfg.get("display", {})
        overlays = self.cfg.get("overlays", {})
        values = {
            "semester_start": display.get("semester_start", "2026-09-01"),
            "full_refresh_at": display.get("full_refresh", {}).get("at", "04:00") + ":00",
            "font_mode": display.get("font_mode", "aliased"),
            "long_press_ms": display.get("long_press_ms", 600),
            "qr_duration_s": overlays.get("qr_duration_s", 20),
            "message_duration_s": overlays.get("message_duration_s", 30),
        }
        return self.async_show_form(step_id="screen", data_schema=self.add_suggested_values_to_schema(
            schema, values))
