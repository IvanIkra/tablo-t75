"""Screen model: plain data for one frame, no pixels (§6.2).

Sources fill it, the renderer draws it. Weather icon keys: sun, moon, cloud,
rain1, rain2, rain3, snow, storm, fog.
"""

import datetime as dt
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WeatherNow:
    temp: float
    feels: float
    icon: str


@dataclass(frozen=True)
class HourForecast:
    hour: int
    temp: float
    icon: str


@dataclass(frozen=True)
class Deadline:
    title: str
    due: dt.date
    category: str  # "study" | "personal"
    source: str  # "hseapp" | "mail" | "tg" | "ical" | "ha" (own, from infomaster's Mini App)


@dataclass(frozen=True)
class Grade:
    label: str
    value: float
    bonus: float | None = None


@dataclass(frozen=True)
class NewsItem:
    text: str  # up to 2 lines
    source: str  # "tg" | "mail"
    short: str = ""  # 1 line; empty = same as text
    importance: int = 3  # 1-5; 1 (ads, memes) only fills space left over
    study: bool = False

    @property
    def rank(self) -> int:
        return self.importance + self.study


@dataclass(frozen=True)
class ClassItem:
    start: dt.time
    subject: str
    room: str
    mark: str | None = None  # "moved" | "cancelled" | "optional": shown in place of the room


@dataclass(frozen=True)
class HomeRow:
    label: str  # empty: the value starts at the left edge
    value: str  # what HA rendered from the row's template


@dataclass(frozen=True)
class Home:
    rows: tuple[HomeRow, ...] = ()  # only rows whose template gave something


@dataclass(frozen=True)
class Tile:
    icon: str | None
    on: bool


@dataclass(frozen=True)
class ScreenModel:
    today: dt.date
    weather: WeatherNow | None = None
    forecast: tuple[HourForecast, ...] = ()
    deadlines: tuple[Deadline, ...] = ()
    deadlines_problem: str | None = None  # e.g. "HSE login needed": first row of the block
    grades: tuple[Grade, ...] = ()
    grades_problem: str | None = None  # shown instead of "no new grades" when the source is failing
    news: tuple[NewsItem, ...] = ()
    news_problem: str | None = None  # shown instead of "no news" when infomaster cannot read the chats
    classes: tuple[ClassItem, ...] = ()
    classes_label: str = ""
    classes_problem: str | None = None  # shown instead of "no classes" when the calendar is failing
    home: Home | None = None
    tiles: tuple[Tile, ...] = field(default_factory=tuple)
