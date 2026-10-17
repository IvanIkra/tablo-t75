"""Assembles the screen model from sources, HA state and config."""

import datetime as dt

from . import stub
from .config import Config
from .ha import LIGHTS
from .model import Home, ScreenModel, Tile

REFRESH_TILE = Tile(icon="mdi:refresh", on=False)


def tiles(cfg: Config, ha) -> tuple[Tile, ...]:
    result = []
    for button_id in range(1, 8):
        button = cfg.button(button_id)
        if not button:
            result.append(Tile(icon=None, on=False))
            continue
        entity = button.tile_entity
        result.append(Tile(icon=button.icon, on=bool(entity) and ha.state(entity) == "on"))
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
    weather, forecast = stub.weather(now)
    classes, classes_label = stub.classes(now)
    return ScreenModel(
        today=now.date(),
        weather=weather,
        forecast=forecast,
        deadlines=stub.deadlines(now),
        grades=stub.grades(),
        news=stub.news(),
        classes=classes,
        classes_label=classes_label,
        home=home(ha),
        tiles=tiles(cfg, ha),
    )
