"""Service configuration.

One schema for both sources: `config.yaml` during development, and later the
payload the Home Assistant integration sends to `PUT /api/config` (§6.5).
Secrets come from the environment and override the file.
"""

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
class Sheet:
    url: str
    label: str | None = None  # short course name on screen; None = derived from the sheet title


@dataclass
class Grades:
    """§7.1: grade sheets kept by teachers, shared by link."""

    student: str = ""  # surname and first name as written in the sheets
    sheets: list[Sheet] = field(default_factory=list)
    window_days: int = 7
    poll_minutes: int = 30
    # Development aid: also show grades that were already there on the first fetch.
    include_baseline: bool = False


@dataclass
class HseApp:
    """§7.2: personal deadlines from the university app. The login itself lives in the store, not here."""

    enabled: bool = True
    poll_minutes: int = 15


@dataclass
class Ical:
    """§7.3: the RUZ timetable. The link is a secret: TABLO_ICAL_URL in .env (later from HA)."""

    url: str = ""
    poll_minutes: int = 60


@dataclass
class Channel:
    name: str  # without "@"
    study: bool = False  # study channels are polled more often and their posts rank higher


@dataclass
class News:
    """§7.5: public Telegram channels through t.me/s (mail comes later), read by Haiku."""

    channels: list[Channel] = field(default_factory=list)
    ttl_hours: int = 24  # news lifetime; also how far back the first poll of a channel reaches
    study_poll_minutes: int = 5
    poll_minutes: int = 15


DEMO_KEYS = ("weather", "deadlines", "grades", "news", "classes", "ha")


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 8765
    device_token: str = "dev-device-token"
    api_token: str = "dev-api-token"
    ha_mode: str = "fake"
    display: Display = field(default_factory=Display)
    buttons: list[Button] = field(default_factory=list)
    wifi_networks: list[WifiNetwork] = field(default_factory=list)
    qr_duration_s: int = 20
    message_duration_s: int = 30
    # Which blocks show demo data until their real source exists; "ha" is the in-memory fake HA.
    demo: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(DEMO_KEYS, True))
    grades: Grades = field(default_factory=Grades)
    hseapp: HseApp = field(default_factory=HseApp)
    ical: Ical = field(default_factory=Ical)
    news: News = field(default_factory=News)

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
    cfg.ha_mode = (data.pop("ha", {}) or {}).get("mode", cfg.ha_mode)

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

    grades = dict(data.pop("grades", {}) or {})
    sheets = [Sheet(**_known(Sheet, s, "grades.sheets")) for s in grades.pop("sheets", []) or []]
    cfg.grades = Grades(sheets=sheets, **_known(Grades, grades, "grades"))
    if sheets and not cfg.grades.student.strip():
        raise ConfigError("grades.student is required to find your row in the sheets")

    cfg.hseapp = HseApp(**_known(HseApp, dict(data.pop("hseapp", {}) or {}), "hseapp"))
    cfg.ical = Ical(**_known(Ical, dict(data.pop("ical", {}) or {}), "ical"))

    news = dict(data.pop("news", {}) or {})
    channels = []
    for raw in news.pop("channels", []) or []:
        raw = {"name": raw} if isinstance(raw, str) else dict(raw)
        channel = Channel(**_known(Channel, raw, "news.channels"))
        channel.name = channel.name.strip().rstrip("/").rsplit("/", 1)[-1].lstrip("@")
        if not channel.name:
            raise ConfigError("news.channels: empty channel name")
        channels.append(channel)
    if len({c.name.casefold() for c in channels}) != len(channels):
        raise ConfigError("news.channels: duplicate channels")
    cfg.news = News(channels=channels, **_known(News, news, "news"))

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
    cfg.ical.url = os.environ.get("TABLO_ICAL_URL", cfg.ical.url)
    if "TABLO_PORT" in os.environ:
        cfg.port = int(os.environ["TABLO_PORT"])


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def load(path: Path, local: bool = True) -> Config:
    """Load a config file, then `<name>.local.yaml` next to it if present.

    The local file is for personal settings that stay out of git: sheet links,
    calendar links, the student name.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    local_path = path.with_name(f"{path.stem}.local{path.suffix}")
    if local and local_path.exists():
        with open(local_path, encoding="utf-8") as f:
            data = _merge(data, yaml.safe_load(f) or {})
    return from_dict(data)
