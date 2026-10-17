"""Assembles the screen model from sources, HA state and config.

Blocks whose demo switch is off stay empty until their real source exists,
so the screen shows only what is real (§15).
"""

import datetime as dt

from . import stub
from .config import Config
from .ha import LIGHTS
from .model import Home, ScreenModel, Tile

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


def build(now: dt.datetime, cfg: Config, ha) -> ScreenModel:
    demo = cfg.demo
    weather, forecast = stub.weather(now) if demo["weather"] else (None, ())
    classes, classes_label = stub.classes(now) if demo["classes"] else ((), "")
    return ScreenModel(
        today=now.date(),
        weather=weather,
        forecast=forecast,
        deadlines=stub.deadlines(now) if demo["deadlines"] else (),
        grades=stub.grades() if demo["grades"] else (),
        news=stub.news() if demo["news"] else (),
        classes=classes,
        classes_label=classes_label,
        home=home(ha) if ha is not None else None,
        tiles=tiles(cfg, ha),
    )
