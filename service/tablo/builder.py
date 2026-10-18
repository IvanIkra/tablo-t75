"""Assembles the screen model from sources, HA state and config.

Blocks whose demo switch is off stay empty until their real source exists,
so the screen shows only what is real (§15).
"""

import datetime as dt
import re

from . import stub
from .config import Config
from .model import Deadline, Home, HomeRow, ScreenModel, Tile

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


DONE_WINDOW_DAYS = 14  # an extension moves the date in an email, while the university app keeps the old one


def _course(d: Deadline) -> str:
    """The course abbreviation, or the first word of the title when the source gave none ('Safety HW 2')."""
    return (d.course or d.title.split(" ", 1)[0]).casefold()


def _work(d: Deadline) -> str:
    """The title without the course prefix, for comparing: 'Prog Midterm' -> 'midterm'."""
    title = " ".join(d.title.casefold().split())
    course = _course(d)
    if title.startswith(course + " "):
        title = title[len(course) + 1:]
    return title


def _same_work(a: Deadline, b: Deadline) -> bool:
    """Same course and same work, whatever the date."""
    if " ".join(a.title.casefold().split()) == " ".join(b.title.casefold().split()):
        return True
    wa, wb = _work(a), _work(b)
    return bool(wa and wb) and _course(a) == _course(b) and (_contains(wa, wb) or _contains(wb, wa))


def _contains(part: str, whole: str) -> bool:
    """Whole words only: 'hw 2' is in 'hw 2 late', not in 'hw 20' or 'hw 2b'."""
    return re.search(rf"(?<!\w){re.escape(part)}(?!\w)", whole) is not None


def _same(a: Deadline, b: Deadline) -> bool:
    return a.due == b.due and _same_work(a, b)


def merge_deadlines(*sources: tuple[Deadline, ...]) -> tuple[Deadline, ...]:
    """One list from several sources, most reliable first; a duplicate of a kept deadline is dropped (§7.2)."""
    kept: list[Deadline] = []
    for items in sources:
        kept += [d for d in items if not any(_same(d, k) for k in kept)]
    return tuple(kept)


def drop_done(deadlines: tuple[Deadline, ...], done: tuple[Deadline, ...]) -> tuple[Deadline, ...]:
    """Hide copies of work completed in the university app: same course and work, dates up to 14 days apart (§7.2)."""
    return tuple(d for d in deadlines if d.source in ("hseapp", "ha") or not any(
        abs((d.due - x.due).days) <= DONE_WINDOW_DAYS and _same_work(d, x) for x in done))


def drop_hidden(deadlines: tuple[Deadline, ...], hidden: tuple[Deadline, ...]) -> tuple[Deadline, ...]:
    """Hide what was deleted or marked done in HA, also when it comes back from another source (§7.2).

    The user's own deadlines are deleted, not hidden: an edited copy of a hidden one stays.
    """
    return tuple(d for d in deadlines if d.source == "ha" or not any(_same(d, h) for h in hidden))


def build(now: dt.datetime, cfg: Config, ha, grades: tuple = (), grades_problem: str | None = None,
          deadlines: tuple = (), deadlines_problem: str | None = None,
          classes: tuple = (), classes_label: str = "", classes_problem: str | None = None,
          news: tuple = (), weather: tuple = (None, ())) -> ScreenModel:
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
        classes=classes,
        classes_label=classes_label,
        classes_problem=classes_problem,
        home=home(ha, cfg),
        tiles=tiles(cfg, ha),
    )
