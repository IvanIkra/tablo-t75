"""Main screen layout (§2). All coordinates for the base frame live here."""

import datetime as dt

from .. import protocol
from ..model import ScreenModel
from . import fonts, pixels
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
# Marks drawn as an icon in place of the room; the others stay words.
MARK_ICONS = {"optional": "mdi:emoticon-outline"}


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
         inverted: bool = False, right_font=None, right_icon: str | None = None) -> None:
    x, _, w, _ = block
    y = _row_y(block, i)
    f = fonts.inter(16, BODY)
    rf = right_font or f
    fg = WHITE if inverted else BLACK
    if inverted:
        c.rect(x + 8, y - 2, w - 16, ROW_H, fill=BLACK)
    lx = left_x if left_x is not None else x + PAD
    right_w = pixels.ICON if right_icon else c.width(right, rf) if right else 0
    c.text((lx, y), c.fit(left, f, x + w - PAD - lx - right_w - 8), f, fill=fg)
    if right_icon:
        c.icon(right_icon, x + w - PAD - pixels.ICON / 2, y + 8, pixels.ICON, fill=fg)
    elif right:
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
    pixels.weather_big(c.draw, m.weather.icon, x + 30, y + h / 2)
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
        pixels.weather_small(c.draw, hour.icon, cx, y + 22)
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


DEADLINE_TEXT_X = PAD + 40  # after the category and source icons


def _deadlines(c: Canvas, m: ScreenModel) -> None:
    today = m.today
    items = m.deadlines  # picked and ordered by infomaster: upcoming by date, then overdue (§7.2)
    first = 1 if m.deadlines_problem else 0
    room = _rows(DEADLINES) - first
    more = len(items) - room
    _block_header(c, DEADLINES, "Deadlines", f"+{more}" if more > 0 else "")
    x = DEADLINES[0]
    if m.deadlines_problem:
        _row(c, DEADLINES, 0, m.deadlines_problem, left_x=x + DEADLINE_TEXT_X)
        c.icon("mdi:alert-circle-outline", x + PAD + 7, _row_y(DEADLINES, 0) + 8, 15, fill=BLACK)
    elif not items:
        _row(c, DEADLINES, 0, "no deadlines")
    for i, d in enumerate(items[:room], start=first):
        urgent = 0 <= (d.due - today).days <= 1
        fg = WHITE if urgent else BLACK
        _row(c, DEADLINES, i, d.title, _due_label(d.due, today), left_x=x + DEADLINE_TEXT_X, inverted=urgent)
        cy = _row_y(DEADLINES, i) + 8
        c.icon(CATEGORY_ICONS.get(d.category), x + PAD + 7, cy, 15, fill=fg)
        c.icon(SOURCE_ICONS.get(d.source), x + PAD + 26, cy, 15, fill=fg)


def _fmt_grade(value: float) -> str:
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"


def _grades(c: Canvas, m: ScreenModel) -> None:
    more = len(m.grades) - _rows(GRADES)
    _block_header(c, GRADES, "Grades", f"+{more}" if more > 0 else "")
    if not m.grades:
        _row(c, GRADES, 0, m.grades_problem or "no new grades")
        return
    for i, g in enumerate(m.grades[: _rows(GRADES)]):
        value = _fmt_grade(g.value) + (f" +{_fmt_grade(g.bonus)}" if g.bonus else "")
        _row(c, GRADES, i, g.label, value, right_font=fonts.inter(16, "semibold"))


NEWS_TEXT_X = PAD + 22  # after the source icon
NEWS_LINE_H = 20
NEWS_GAP = 10  # between items: a 1-line item takes 30 px, a 2-line one 50 px (§7.7)
TOP_RANK = 5  # importance + 1 for study


def news_text_width() -> float:
    return NEWS[2] - NEWS_TEXT_X - PAD


def layout_news(items, c: Canvas | None = None) -> list[tuple[object, list[str]]]:
    """Which items to show and in how many lines; items come ranked (§7.7).

    Top items (rank 5 and up: a study item to act on) get the long version first.
    Then as many items as fit in one line each, then the long version for the
    rest by rank while room is left. Importance 1 (ads, memes) only fills what remains.
    """
    c, f, w = c or Canvas(), fonts.inter(16, BODY), news_text_width()
    room = NEWS[3] - HEADER_H - 16 + NEWS_GAP  # the last item needs no gap below

    def cost(lines):
        return len(lines) * NEWS_LINE_H + NEWS_GAP

    full = [c.wrap(it.text, f, w, 2) for it in items]
    short = [c.wrap(it.short or it.text, f, w, 1) for it in items]
    chosen: dict[int, list[str]] = {}
    used = 0

    def add(indexes, versions):
        nonlocal used
        for k in indexes:
            if k in chosen:
                continue
            if used + cost(versions[k]) > room:
                break
            chosen[k] = versions[k]
            used += cost(versions[k])

    add([k for k, it in enumerate(items) if it.rank >= TOP_RANK], full)
    add([k for k, it in enumerate(items) if it.importance > 1], short)
    for k in list(chosen):
        extra = cost(full[k]) - cost(chosen[k])
        if used + extra <= room:
            chosen[k] = full[k]
            used += extra
    add([k for k, it in enumerate(items) if it.importance <= 1], short)
    return [(items[k], chosen[k]) for k in sorted(chosen)]


def _news(c: Canvas, m: ScreenModel) -> None:
    x, y, w, h = NEWS
    _block_header(c, NEWS, "News")
    f = fonts.inter(16, BODY)
    cy = y + HEADER_H + 8
    if not m.news:
        c.text((x + PAD, cy), m.news_problem or "no news", f)
    for item, lines in layout_news(m.news, c):
        c.icon(SOURCE_ICONS.get(item.source), x + PAD + 7, cy + 9, 15)
        for j, line in enumerate(lines):
            c.text((x + NEWS_TEXT_X, cy + j * NEWS_LINE_H), line, f)
        cy += len(lines) * NEWS_LINE_H + NEWS_GAP


CLASS_TEXT_X = PAD + 52  # after the start time


def _classes(c: Canvas, m: ScreenModel) -> None:
    _block_header(c, CLASSES, "Classes", m.classes_label)
    x = CLASSES[0]
    if not m.classes:
        _row(c, CLASSES, 0, m.classes_problem or "no classes")
    for i, cl in enumerate(m.classes[: _rows(CLASSES)]):
        room = cl.mark if cl.mark else cl.room
        _row(c, CLASSES, i, cl.subject, room, left_x=x + CLASS_TEXT_X, right_icon=MARK_ICONS.get(cl.mark))
        c.text((x + PAD, _row_y(CLASSES, i)), cl.start.strftime("%H:%M"), fonts.inter(16, "semibold"))


def _home(c: Canvas, m: ScreenModel) -> None:
    _block_header(c, HOME, "Home")
    h = m.home
    if not h:
        _row(c, HOME, 0, "no Home Assistant")
        return
    if not h.rows:
        _row(c, HOME, 0, "—")
        return
    x, _, w, _ = HOME
    bold = fonts.inter(16, "semibold")
    for i, row in enumerate(h.rows[:_rows(HOME)]):
        if row.label:
            # The value keeps at least the label's width; a long one is cut with "…".
            room = w - 2 * PAD - c.width(row.label, fonts.inter(16, BODY)) - 8
            _row(c, HOME, i, row.label, c.fit(row.value, bold, room), right_font=bold)
        else:
            _row(c, HOME, i, row.value)


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
