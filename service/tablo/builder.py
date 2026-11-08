"""Assembles the screen model from sources, HA state and config.

Blocks whose demo switch is off stay empty until their real source exists,
so the screen shows only what is real (§15).
"""

import datetime as dt
import math
from zoneinfo import ZoneInfo

from . import stub
from .config import Config
from .model import Home, HomeRow, ScreenModel, Tile

REFRESH_TILE = Tile(icon="mdi:refresh", on=False)
SCRIPT_PREFIX = "Tablo · "  # how the scripts for the buttons are named in HA; the block says less


def tiles(cfg: Config, ha) -> tuple[Tile, ...]:
    """ha is None when no Home Assistant is available: icons stay, nothing is filled."""
    result = []
    for button_id in range(1, 8):
        button = cfg.button(button_id)
        if not button:
            result.append(Tile(icon=None, on=False))
            continue
        entity = button.tile_entity
        on = ha is not None and bool(entity) and ha.state(entity) == "on"
        result.append(Tile(icon=button.icon, on=on))
    result.append(REFRESH_TILE)
    return tuple(result)


def home(ha, cfg: Config, now: dt.datetime | None = None) -> Home | None:
    """None until HA has sent its states once; after that the last known results, also offline (§11).

    A row whose template gave nothing (not rendered yet, empty, an error) is left out (§8.3).
    now: local time without a zone, as the rest of the screen uses it.
    """
    if ha is None or not ha.ready:
        return None
    rows = []
    for row in cfg.home.rows:
        value = (ha.template(row.template) or "").strip()
        if value:
            rows.append(HomeRow(row.label, " ".join(value.split())))
    tz = ZoneInfo(cfg.display.tz_name)
    now = now.replace(tzinfo=tz) if now else dt.datetime.now(tz)
    return Home(rows=tuple(rows), scripts=running_scripts(ha, now))


def running_scripts(ha, now: dt.datetime) -> tuple[HomeRow, ...]:
    """§8.3: scripts that are on and wait (a delay, a trigger), with the time left when their delays tell it.

    A script that never waits is on for a moment only: no row, which would just flash on the panel.
    """
    result = []
    for entity, state in sorted(ha.states.items()):
        if not entity.startswith("script.") or state != "on":
            continue
        length = ha.script_length(entity)
        if not length:  # not known yet (asked when it started), or done in a moment
            continue
        name = ha.attribute(entity, "friendly_name") or entity.split(".", 1)[1].replace("_", " ")
        result.append(HomeRow(str(name).removeprefix(SCRIPT_PREFIX), _time_left(ha, entity, length, now)))
    return tuple(result)


def _time_left(ha, entity: str, length: float, now: dt.datetime) -> str:
    """"4 min left", "1:20 left" past an hour; "running" when it cannot be told or the delays are over."""
    try:
        started = dt.datetime.fromisoformat(str(ha.attribute(entity, "last_triggered")))
    except ValueError:
        return "running"
    if math.isinf(length) or started.tzinfo is None:
        return "running"
    seconds = (started - now).total_seconds() + length
    if seconds <= 0:
        return "running"
    minutes = math.ceil(seconds / 60)
    return f"{minutes} min left" if minutes < 60 else f"{minutes // 60}:{minutes % 60:02d} left"


def build(now: dt.datetime, cfg: Config, ha, grades: tuple = (), grades_problem: str | None = None,
          deadlines: tuple = (), deadlines_problem: str | None = None,
          classes: tuple = (), classes_label: str = "", classes_problem: str | None = None,
          news: tuple = (), news_problem: str | None = None, weather: tuple = (None, ())) -> ScreenModel:
    """grades, deadlines, classes, news, weather: real data from the sources, used when the demo switch is off."""
    demo = cfg.demo
    weather, forecast = stub.weather(now) if demo["weather"] else weather
    if demo["classes"]:
        classes, classes_label = stub.classes(now)
        classes_problem = None
    return ScreenModel(
        today=now.date(),
        weather=weather,
        forecast=forecast,
        deadlines=stub.deadlines(now) if demo["deadlines"] else deadlines,
        deadlines_problem=None if demo["deadlines"] else deadlines_problem,
        grades=stub.grades() if demo["grades"] else grades,
        grades_problem=None if demo["grades"] else grades_problem,
        news=stub.news() if demo["news"] else news,
        news_problem=None if demo["news"] else news_problem,
        classes=classes,
        classes_label=classes_label,
        classes_problem=classes_problem,
        home=home(ha, cfg, now),
        tiles=tiles(cfg, ha),
    )
