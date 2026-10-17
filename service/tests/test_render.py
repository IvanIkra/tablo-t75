import datetime as dt
from pathlib import Path

import pytest

from tablo import builder, config, protocol
from tablo.ha import FakeHA
from tablo.model import Deadline, ScreenModel
from tablo.render import overlays, screen
from tablo.render.canvas import Canvas
from tablo.render.screen import _due_label

CFG = config.load(Path(__file__).resolve().parents[1] / "config.yaml")
NOW = dt.datetime(2026, 10, 18, 18, 42)


def _black(bw, rect) -> int:
    x, y, w, h = rect
    return sum(1 for yy in range(y, y + h) for xx in range(x, x + w) if bw.getpixel((xx, yy)) == 0)


@pytest.mark.parametrize("mode", ["aliased", "threshold"])
def test_main_screen_is_pure_bw_and_leaves_firmware_zones_white(mode):
    bw = screen.render(builder.build(NOW, CFG, FakeHA()), mode).to_bw()
    assert bw.mode == "1" and bw.size == (protocol.WIDTH, protocol.HEIGHT)
    for rect in protocol.FIRMWARE_ZONES.values():
        assert _black(bw, rect) == 0
    assert _black(bw, (0, 100, 800, 328)) > 1000  # the blocks have content


def test_tile_fill_follows_ha_state():
    ha = FakeHA()
    ha.states["light.desk_light"] = "off"
    off = screen.render(builder.build(NOW, CFG, ha)).to_bw()
    ha.states["light.desk_light"] = "on"
    on = screen.render(builder.build(NOW, CFG, ha)).to_bw()
    tile4 = (300, 430, 100, 50)
    assert _black(off, tile4) < 1000 < _black(on, tile4)


def test_due_labels():
    today = dt.date(2026, 10, 18)
    assert _due_label(today, today) == "today"
    assert _due_label(today + dt.timedelta(days=1), today) == "tomorrow"
    assert _due_label(dt.date(2026, 10, 25), today) == "Oct 25"
    assert _due_label(today - dt.timedelta(days=1), today) == "overdue"


def test_old_overdue_deadlines_are_dropped():
    today = NOW.date()
    model = ScreenModel(today=today, deadlines=(
        Deadline("recent", today - dt.timedelta(days=2), "study", "hseapp"),
        Deadline("ancient", today - dt.timedelta(days=10), "study", "hseapp"),
    ))
    # Only the 3-day overdue window counts, so no "+N" overflow and one row drawn.
    bw = screen.render(model).to_bw()
    first_row, second_row = (8, 144, 256, 22), (8, 168, 256, 22)
    assert _black(bw, first_row) > 0 and _black(bw, second_row) == 0


def test_wrap_marks_cut_text():
    c = Canvas()
    from tablo.render import fonts
    lines = c.wrap("one two three four five six seven eight nine ten eleven twelve", fonts.inter(16), 120, 2)
    assert len(lines) == 2 and lines[-1].endswith("…")


def test_overlays_render():
    assert overlays.wifi_qr(CFG.wifi_networks).to_bw().size == (800, 480)
    assert overlays.message("Title", "Body\nsecond line", "mdi:bell").to_bw().size == (800, 480)
