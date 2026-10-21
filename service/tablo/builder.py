"""Assembles the screen model from sources, HA state and config.

Blocks whose demo switch is off stay empty until their real source exists,
so the screen shows only what is real (§15).
"""

import datetime as dt

from . import stub
from .config import Config
from .model import Home, HomeRow, ScreenModel, Tile

REFRESH_TILE = Tile(icon="mdi:refresh", on=False)


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


def home(ha, cfg: Config) -> Home | None:
    """None until HA has sent its states once; after that the last known results, also offline (§11).

    A row whose template gave nothing (not rendered yet, empty, an error) is left out (§8.3).
    """
    if ha is None or not ha.ready:
        return None
    rows = []
    for row in cfg.home.rows:
        value = (ha.template(row.template) or "").strip()
        if value:
            rows.append(HomeRow(row.label, " ".join(value.split())))
    return Home(rows=tuple(rows))


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
        home=home(ha, cfg),
        tiles=tiles(cfg, ha),
    )
