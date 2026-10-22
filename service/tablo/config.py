"""Service configuration.

One schema for both sources: `config.yaml` during development, and later the
payload the Home Assistant integration sends to `PUT /api/config` (§6.5).
Secrets come from the environment and override the file.
"""

import dataclasses
import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ACTIONS = {"toggle", "script", "qr", "message", "event", "none"}
PRESSES = ("short", "long")


class ConfigError(ValueError):
    pass


@dataclass
class Action:
    action: str = "none"
    entity: str | None = None
    duration_s: int | None = None
    networks: list[str] = field(default_factory=list)  # ssids for "qr"; empty = all
    title: str | None = None
    text: str | None = None

    @classmethod
    def from_dict(cls, data: dict | None, where: str) -> "Action":
        data = dict(data or {})
        action = data.pop("action", "none")
        if action not in ACTIONS:
            raise ConfigError(f"{where}: unknown action {action!r}")
        obj = cls(action=action, **_known(cls, data, where))
        if action in ("toggle", "script") and not obj.entity:
            raise ConfigError(f"{where}: action {action!r} needs an entity")
        return obj


@dataclass
class Button:
    id: int
    icon: str = "mdi:help"
    tile: str | None = None  # entity whose on/off state fills the tile; "none" = never
    short: Action = field(default_factory=Action)
    long: Action = field(default_factory=Action)

    @property
    def tile_entity(self) -> str | None:
        if self.tile == "none":
            return None
        if self.tile:
            return self.tile
        return self.short.entity if self.short.action == "toggle" else None


@dataclass
class WifiNetwork:
    ssid: str
    password: str = ""
    security: str = "WPA"
    hidden: bool = False


@dataclass
class Display:
    tz: str = "MSK-3"
    tz_name: str = "Europe/Moscow"
    ntp: str = "pool.ntp.org"
    semester_start: dt.date = dt.date(2026, 9, 1)
    long_press_ms: int = 600
    full_refresh_at: str = "04:00"
    max_partials: int = 200
    offline_after_s: int = 120
    diag_ttl_s: int = 30
    font_mode: str = "aliased"  # "aliased" (FreeType mono) or "threshold" (grey + cut)


@dataclass
class Ical:
    """§7.3: the timetable, infomaster's tablo.ics feed. Its link carries the feed's secret."""

    url: str = ""
    poll_minutes: int = 10


@dataclass
class Infomaster:
    """§7.2: deadlines, news and grades from infomaster's internal API. The token is TABLO_INFOMASTER_TOKEN."""

    url: str = "http://infomaster:8081"
    poll_seconds: int = 60


@dataclass
class Weather:
    """§7.4: Open-Meteo, no key."""

    latitude: float = 55.7558
    longitude: float = 37.6173
    poll_minutes: int = 15


HOME_ROWS_MAX = 5  # rows that fit under the Home block header


@dataclass
class HomeRow:
    """One row of the Home block (§8.3): HA renders the template, an empty result hides the row."""

    label: str = ""  # left side; empty = the value starts at the left edge
    template: str = ""


@dataclass
class Home:
    """§7.6, §8.3: the Home block, rows of HA templates."""

    rows: list[HomeRow] = field(default_factory=list)


LEGACY_HOME_KEYS = {"temperature", "humidity", "lights", "printer"}
CLIMATE_TEMPLATE = "{{ states('$T') | round(1) }}° · {{ states('$H') | round(0) | int }}%"
LIGHTS_TEMPLATE = "{{ $LIST | select('is_state', 'on') | list | count }} of $N"
PRINTER_TEMPLATE = (
    "{% if is_state('$S', 'printing') %}{{ states('$P') | round(0) | int }}% · "
    "{% set unit = {'s': 1 / 60, 'min': 1, 'h': 60, 'd': 1440}[state_attr('$L', 'unit_of_measurement')] %}"
    "{% set m = (states('$L') | float(0) * unit) | round(0) | int %}{{ m // 60 }}:{{ '%02d' % (m % 60) }}{% endif %}"
)


def _fill(template: str, **values: str) -> str:
    for key, value in values.items():
        template = template.replace(f"${key}", value)
    return template


def legacy_home_rows(home: dict) -> list[HomeRow]:
    """The rows the old fixed Home block showed, from its old settings (sensors, lights, Moonraker sensors)."""
    rows = []
    t = home.get("temperature", "sensor.room_sensor_temperature")
    h = home.get("humidity", "sensor.room_sensor_humidity")
    if t and h:
        rows.append(HomeRow("", _fill(CLIMATE_TEMPLATE, T=t, H=h)))
    elif t or h:
        rows.append(HomeRow("", "{{ states('%s') | round(1) }}%s" % (t or h, "°" if t else "%")))
    lights = list(home.get("lights") or [])
    if lights:
        rows.append(HomeRow("lights", _fill(LIGHTS_TEMPLATE, LIST=repr(lights), N=str(len(lights)))))
    printer = dict(home.get("printer") or {})
    if printer.get("state") and printer.get("progress") and printer.get("time_left"):
        rows.append(HomeRow("printing", _fill(PRINTER_TEMPLATE, S=printer["state"], P=printer["progress"],
                                              L=printer["time_left"])))
    return rows


@dataclass
class HA:
    """§8.1: the service's own connection to HA. The token comes from TABLO_HA_TOKEN."""

    url: str = "http://192.168.1.50:8123"
    token: str = ""


DEMO_KEYS = ("weather", "deadlines", "grades", "news", "classes", "ha")


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 8765
    device_token: str = "dev-device-token"
    api_token: str = "dev-api-token"
    infomaster_token: str = ""
    ha: HA = field(default_factory=HA)
    display: Display = field(default_factory=Display)
    buttons: list[Button] = field(default_factory=list)
    wifi_networks: list[WifiNetwork] = field(default_factory=list)
    qr_duration_s: int = 20
    message_duration_s: int = 30
    # Which blocks show demo data until their real source exists; "ha" is the in-memory fake HA.
    demo: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(DEMO_KEYS, True))
    infomaster: Infomaster = field(default_factory=Infomaster)
    ical: Ical = field(default_factory=Ical)
    weather: Weather = field(default_factory=Weather)
    home: Home = field(default_factory=Home)

    def button(self, button_id: int) -> Button | None:
        return next((b for b in self.buttons if b.id == button_id), None)


def _known(cls, data: dict, where: str) -> dict:
    allowed = set(cls.__dataclass_fields__)
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")
    return data


def from_dict(data: dict) -> Config:
    data = dict(data or {})
    cfg = Config()

    server = data.pop("server", {}) or {}
    cfg.host = server.get("host", cfg.host)
    cfg.port = int(server.get("port", cfg.port))
    cfg.device_token = (data.pop("device", {}) or {}).get("token", cfg.device_token)
    cfg.api_token = (data.pop("api", {}) or {}).get("token", cfg.api_token)
    cfg.ha = HA(**_known(HA, dict(data.pop("ha", {}) or {}), "ha"))

    display = dict(data.pop("display", {}) or {})
    full_refresh = display.pop("full_refresh", {}) or {}
    if "at" in full_refresh:
        display["full_refresh_at"] = full_refresh["at"]
    if "max_partials" in full_refresh:
        display["max_partials"] = full_refresh["max_partials"]
    if isinstance(display.get("semester_start"), str):
        display["semester_start"] = dt.date.fromisoformat(display["semester_start"])
    cfg.display = Display(**_known(Display, display, "display"))
    if cfg.display.font_mode not in ("aliased", "threshold"):
        raise ConfigError("display.font_mode must be 'aliased' or 'threshold'")

    overlays = data.pop("overlays", {}) or {}
    cfg.qr_duration_s = int(overlays.get("qr_duration_s", cfg.qr_duration_s))
    cfg.message_duration_s = int(overlays.get("message_duration_s", cfg.message_duration_s))

    cfg.demo.update(parse_demo(data.pop("demo", {}) or {}))

    cfg.infomaster = Infomaster(**_known(Infomaster, dict(data.pop("infomaster", {}) or {}), "infomaster"))
    cfg.ical = Ical(**_known(Ical, dict(data.pop("ical", {}) or {}), "ical"))
    cfg.weather = Weather(**_known(Weather, dict(data.pop("weather", {}) or {}), "weather"))

    home = dict(data.pop("home", {}) or {})
    if "rows" in home:
        # An integration that still has the old fields sends them too; rows win.
        _known(Home, {k: v for k, v in home.items() if k not in LEGACY_HOME_KEYS}, "home")
        rows = [HomeRow(**_known(HomeRow, dict(r or {}), "home.rows")) for r in home["rows"] or []]
    else:
        _known(Home, {k: v for k, v in home.items() if k not in LEGACY_HOME_KEYS}, "home")
        rows = legacy_home_rows(home)
    for r in rows:
        if not isinstance(r.label, str) or not isinstance(r.template, str) or not r.template.strip():
            raise ConfigError("home.rows: each row needs a template")
        if "|" in r.label or "{" in r.label:
            raise ConfigError(f"home.rows: label {r.label!r} cannot have | or {{")
    if len(rows) > HOME_ROWS_MAX:
        raise ConfigError(f"home.rows: at most {HOME_ROWS_MAX} rows fit the block")
    cfg.home = Home(rows=rows)

    cfg.wifi_networks = [
        WifiNetwork(**_known(WifiNetwork, n, "wifi_networks")) for n in data.pop("wifi_networks", []) or []
    ]

    buttons = []
    for raw in data.pop("buttons", []) or []:
        raw = dict(raw)
        bid = int(raw.pop("id"))
        if not 1 <= bid <= 7:
            raise ConfigError(f"button {bid}: only buttons 1-7 are configurable, 8 is fixed")
        where = f"button {bid}"
        short = Action.from_dict(raw.pop("short", None), f"{where}.short")
        long = Action.from_dict(raw.pop("long", None), f"{where}.long")
        buttons.append(Button(id=bid, short=short, long=long, **_known(Button, raw, where)))
    if len({b.id for b in buttons}) != len(buttons):
        raise ConfigError("duplicate button ids")
    cfg.buttons = sorted(buttons, key=lambda b: b.id)

    if data:
        raise ConfigError(f"unknown top-level keys {sorted(data)}")
    _apply_env(cfg)
    return cfg


def parse_demo(data: dict) -> dict[str, bool]:
    unknown = set(data) - set(DEMO_KEYS)
    if unknown:
        raise ConfigError(f"demo: unknown keys {sorted(unknown)}")
    if not all(isinstance(v, bool) for v in data.values()):
        raise ConfigError("demo: values must be true or false")
    return dict(data)


def _apply_env(cfg: Config) -> None:
    cfg.device_token = os.environ.get("TABLO_DEVICE_TOKEN", cfg.device_token)
    cfg.api_token = os.environ.get("TABLO_API_TOKEN", cfg.api_token)
    cfg.infomaster_token = os.environ.get("TABLO_INFOMASTER_TOKEN", cfg.infomaster_token)
    cfg.ha.url = os.environ.get("TABLO_HA_URL", cfg.ha.url)
    cfg.ha.token = os.environ.get("TABLO_HA_TOKEN", cfg.ha.token)
    if "TABLO_PORT" in os.environ:
        cfg.port = int(os.environ["TABLO_PORT"])


def to_dict(cfg: Config) -> dict:
    """The config in the file's shape, for HA to import (`GET /api/config`).

    Without what HA does not set: the listening address, tokens, the service's own
    link to HA, demo switches (§6.5).
    """
    def plain(obj) -> dict:
        return {k: v for k, v in dataclasses.asdict(obj).items() if v is not None and v != []}

    display = plain(cfg.display)
    display["semester_start"] = cfg.display.semester_start.isoformat()
    display["full_refresh"] = {"at": display.pop("full_refresh_at"), "max_partials": display.pop("max_partials")}
    buttons = []
    for b in cfg.buttons:
        raw = {"id": b.id, "icon": b.icon}
        if b.tile:
            raw["tile"] = b.tile
        raw["short"], raw["long"] = plain(b.short), plain(b.long)
        buttons.append(raw)
    return {
        "display": display,
        "overlays": {"qr_duration_s": cfg.qr_duration_s, "message_duration_s": cfg.message_duration_s},
        "weather": plain(cfg.weather),
        "home": dataclasses.asdict(cfg.home),
        "infomaster": plain(cfg.infomaster),
        "ical": plain(cfg.ical),
        "wifi_networks": [dataclasses.asdict(n) for n in cfg.wifi_networks],
        "buttons": buttons,
    }


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def load(path: Path, local: bool = True) -> Config:
    """Load a config file, then `<name>.local.yaml` next to it if present.

    The local file is for personal settings that stay out of git: the calendar link.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    local_path = path.with_name(f"{path.stem}.local{path.suffix}")
    if local and local_path.exists():
        with open(local_path, encoding="utf-8") as f:
            data = _merge(data, yaml.safe_load(f) or {})
    return from_dict(data)
