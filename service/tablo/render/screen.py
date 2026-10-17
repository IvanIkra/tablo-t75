"""Main screen layout (§2). All coordinates for the base frame live here."""

import datetime as dt

from .. import protocol
from ..model import ScreenModel
from . import fonts, weather_icons
from .canvas import BLACK, WHITE, Canvas

# Blocks: x, y, w, h (§2).
WEATHER_BOX = (188, 14, 142, 68)
FORECAST_BOX = (340, 26, 452, 68)
DEADLINES = (0, 100, 272, 164)
GRADES = (0, 264, 272, 164)
NEWS = (272, 100, 288, 328)
CLASSES = (560, 100, 240, 164)
HOME = (560, 264, 240, 164)

PAD = 16
HEADER_H = 36  # block title + underline
ROW_H = 22
# Medium rather than Regular: one-pixel Regular stems look broken on a 1-bit screen.
BODY = "medium"

CATEGORY_ICONS = {"study": "mdi:book-open-variant", "personal": "mdi:account"}
SOURCE_ICONS = {
    "hseapp": "mdi:school",
    "mail": "mdi:email-outline",
    "tg": "mdi:send",
    "ical": "mdi:calendar",
    "ha": "mdi:home-outline",
}


def render(model: ScreenModel, font_mode: str = "aliased") -> Canvas:
    c = Canvas(font_mode)
    _grid(c)
    _weather(c, model)
    _forecast(c, model)
    _deadlines(c, model)
    _grades(c, model)
    _news(c, model)
    _classes(c, model)
    _home(c, model)
    _tiles(c, model)
    # Firmware zones stay white whatever was drawn near them (§2).
    for rect in protocol.FIRMWARE_ZONES.values():
        c.clear(rect)
    return c


def _grid(c: Canvas) -> None:
    c.hline(0, 800, 100)
    c.vline(271, 100, 428)
    c.vline(559, 100, 428)
    c.hline(0, 271, 263)
    c.hline(561, 800, 263)
    c.hline(0, 800, 427)


def _block_header(c: Canvas, block, title: str, right: str = "") -> None:
    x, y, w, _ = block
    f = fonts.inter(16, "semibold")
    c.text((x + PAD, y + 10), title, f)
    if right:
        c.text((x + w - PAD, y + 10), right, fonts.inter(16, BODY), anchor="ra")
    c.hline(x + PAD, x + w - PAD, y + 32)


def _rows(block) -> int:
    """How many text rows fit under the block header."""
    return (block[3] - HEADER_H - 12) // ROW_H


def _row_y(block, i: int) -> int:
    return block[1] + HEADER_H + 8 + i * ROW_H


def _row(c: Canvas, block, i: int, left: str, right: str = "", left_x: int | None = None,
         inverted: bool = False, right_font=None) -> None:
    x, _, w, _ = block
    y = _row_y(block, i)
    f = fonts.inter(16, BODY)
    rf = right_font or f
    fg = WHITE if inverted else BLACK
    if inverted:
        c.rect(x + 8, y - 2, w - 16, ROW_H, fill=BLACK)
    lx = left_x if left_x is not None else x + PAD
    right_w = c.width(right, rf) if right else 0
    c.text((lx, y), c.fit(left, f, x + w - PAD - lx - right_w - 8), f, fill=fg)
    if right:
        c.text((x + w - PAD, y), right, rf, fill=fg, anchor="ra")


def _fmt_temp(t: float) -> str:
    t = round(t)
    return f"+{t}°" if t > 0 else f"{t}°"


def _weather(c: Canvas, m: ScreenModel) -> None:
    x, y, w, h = WEATHER_BOX
    c.rect(x, y, w, h, outline=BLACK, width=2)
    if not m.weather:
        c.text((x + w / 2, y + h / 2), "no weather", fonts.inter(15, BODY), anchor="mm")
        return
    weather_icons.draw(c.draw, m.weather.icon, x + 30, y + h / 2, 44)
    c.text((x + 58, y + 8), _fmt_temp(m.weather.temp), fonts.inter(30, "semibold"))
    c.text((x + 60, y + 44), f"feels {_fmt_temp(m.weather.feels)}", fonts.inter(15, BODY))


def _forecast(c: Canvas, m: ScreenModel) -> None:
    x, y, w, h = FORECAST_BOX
    c.rect(x, y, w, h, outline=BLACK, width=2)
    if not m.forecast:
        c.text((x + w / 2, y + h / 2), "no forecast", fonts.inter(15, BODY), anchor="mm")
        return
    col = w / 8
    for i, hour in enumerate(m.forecast[:8]):
        cx = x + col * i + col / 2
        c.text((cx, y + 4), f"{hour.hour:02d}", fonts.inter(15, BODY), anchor="ma")
        weather_icons.draw(c.draw, hour.icon, cx, y + 34, 22)
        c.text((cx, y + h - 6), _fmt_temp(hour.temp), fonts.inter(16, "semibold"), anchor="md")


def _due_label(due: dt.date, today: dt.date) -> str:
    days = (due - today).days
    if days < 0:
        return "overdue"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return due.strftime("%b %d").replace(" 0", " ")


def _deadlines(c: Canvas, m: ScreenModel) -> None:
    today = m.today
    # Upcoming by date first, then overdue ones (shown for 3 days after the due date, §7.2).
    upcoming = sorted((d for d in m.deadlines if d.due >= today), key=lambda d: d.due)
    overdue = sorted((d for d in m.deadlines if today - dt.timedelta(days=3) <= d.due < today),
                     key=lambda d: d.due, reverse=True)
    items = upcoming + overdue
    more = len(items) - _rows(DEADLINES)
    _block_header(c, DEADLINES, "Deadlines", f"+{more}" if more > 0 else "")
    x = DEADLINES[0]
    if not items:
        _row(c, DEADLINES, 0, "no deadlines")
    for i, d in enumerate(items[: _rows(DEADLINES)]):
        urgent = 0 <= (d.due - today).days <= 1
        fg = WHITE if urgent else BLACK
        _row(c, DEADLINES, i, d.title, _due_label(d.due, today), left_x=x + PAD + 40, inverted=urgent)
        cy = _row_y(DEADLINES, i) + 8
        c.icon(CATEGORY_ICONS.get(d.category), x + PAD + 7, cy, 15, fill=fg)
        c.icon(SOURCE_ICONS.get(d.source), x + PAD + 26, cy, 15, fill=fg)


def _fmt_grade(value: float) -> str:
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"


def _grades(c: Canvas, m: ScreenModel) -> None:
    more = len(m.grades) - _rows(GRADES)
    _block_header(c, GRADES, "Grades", f"+{more}" if more > 0 else "")
    if not m.grades:
        _row(c, GRADES, 0, "no new grades")
        return
    for i, g in enumerate(m.grades[: _rows(GRADES)]):
        value = _fmt_grade(g.value) + (f" +{_fmt_grade(g.bonus)}" if g.bonus else "")
        _row(c, GRADES, i, g.label, value, right_font=fonts.inter(16, "semibold"))


def _news(c: Canvas, m: ScreenModel) -> None:
    x, y, w, h = NEWS
    _block_header(c, NEWS, "News")
    f = fonts.inter(16, BODY)
    line_h = 20
    text_x = x + PAD + 22
    max_w = x + w - PAD - text_x
    cy = y + HEADER_H + 8
    bottom = y + h - 8
    if not m.news:
        c.text((x + PAD, cy), "no news", f)
    for item in m.news:
        lines = c.wrap(item.text, f, max_w, 2)
        if cy + len(lines) * line_h > bottom:
            break
        c.icon(SOURCE_ICONS.get(item.source), x + PAD + 7, cy + 9, 15)
        for j, line in enumerate(lines):
            c.text((text_x, cy + j * line_h), line, f)
        cy += len(lines) * line_h + 10


def _classes(c: Canvas, m: ScreenModel) -> None:
    _block_header(c, CLASSES, "Classes", m.classes_label)
    x = CLASSES[0]
    if not m.classes:
        _row(c, CLASSES, 0, "no classes")
    for i, cl in enumerate(m.classes[: _rows(CLASSES)]):
        room = cl.mark if cl.mark else cl.room
        _row(c, CLASSES, i, cl.subject, room, left_x=x + PAD + 52)
        c.text((x + PAD, _row_y(CLASSES, i)), cl.start.strftime("%H:%M"), fonts.inter(16, "semibold"))


def _home(c: Canvas, m: ScreenModel) -> None:
    _block_header(c, HOME, "Home")
    h = m.home
    if not h:
        _row(c, HOME, 0, "no Home Assistant")
        return
    climate = []
    if h.temp is not None:
        climate.append(f"{h.temp:.1f}°")
    if h.humidity is not None:
        climate.append(f"{h.humidity:.0f}%")
    bold = fonts.inter(16, "semibold")
    _row(c, HOME, 0, " · ".join(climate) or "—")
    _row(c, HOME, 1, "lights", f"{h.lights_on} of {h.lights_total}", right_font=bold)
    _row(c, HOME, 2, "printer", h.printer, right_font=bold)


def _tiles(c: Canvas, m: ScreenModel) -> None:
    bx, by, _, bh = protocol.BUTTONS_ZONE
    tw = protocol.TILE_WIDTH
    for i, tile in enumerate(m.tiles[:8]):
        x = bx + i * tw
        if tile.on:
            c.rect(x, by + 2, tw, bh - 2, fill=BLACK)
        elif i:
            c.vline(x, by + 2, by + bh, width=1)
        c.icon(tile.icon, x + tw / 2, by + 2 + (bh - 2) / 2, 30, fill=WHITE if tile.on else BLACK)
