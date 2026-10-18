"""Assembles the screen model from sources, HA state and config.

Blocks whose demo switch is off stay empty until their real source exists,
so the screen shows only what is real (§15).
"""

import datetime as dt

from . import stub
from .config import Config
from .ha import LIGHTS
from .model import Deadline, Home, ScreenModel, Tile

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


def home(ha) -> Home:
    def number(entity):
        try:
            return float(ha.state(entity))
        except (TypeError, ValueError):
            return None

    return Home(
        temp=number("sensor.room_sensor_temperature"),
        humidity=number("sensor.room_sensor_humidity"),
        lights_on=sum(ha.state(e) == "on" for e in LIGHTS),
        lights_total=len(LIGHTS),
        printer="idle",
    )


def _work(d: Deadline) -> str:
    """The title without the course prefix, for comparing: 'Prog Midterm' -> 'midterm'."""
    title = " ".join(d.title.casefold().split())
    if d.course and title.startswith(d.course.casefold() + " "):
        title = title[len(d.course) + 1:]
    return title


def _same(a: Deadline, b: Deadline) -> bool:
    if a.due != b.due:
        return False
    if " ".join(a.title.casefold().split()) == " ".join(b.title.casefold().split()):
        return True
    wa, wb = _work(a), _work(b)
    return bool(a.course) and a.course == b.course and (wa in wb or wb in wa)


def merge_deadlines(*sources: tuple[Deadline, ...]) -> tuple[Deadline, ...]:
    """One list from several sources, most reliable first; a duplicate of a kept deadline is dropped (§7.2)."""
    kept: list[Deadline] = []
    for items in sources:
        kept += [d for d in items if not any(_same(d, k) for k in kept)]
    return tuple(kept)


def build(now: dt.datetime, cfg: Config, ha, grades: tuple = (), grades_problem: str | None = None,
          deadlines: tuple = (), deadlines_problem: str | None = None,
          classes: tuple = (), classes_label: str = "", classes_problem: str | None = None) -> ScreenModel:
    """grades, deadlines, classes: real data from the sources, used when the demo switch is off."""
    demo = cfg.demo
    weather, forecast = stub.weather(now) if demo["weather"] else (None, ())
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
        news=stub.news() if demo["news"] else (),
        classes=classes,
        classes_label=classes_label,
        classes_problem=classes_problem,
        home=home(ha) if ha is not None else None,
        tiles=tiles(cfg, ha),
    )
