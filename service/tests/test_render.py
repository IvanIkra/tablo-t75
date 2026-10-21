import datetime as dt
from pathlib import Path

import pytest

from tablo import builder, config, protocol
from tablo.ha import FakeHA
from tablo.model import Deadline, ScreenModel
from tablo.render import fonts, overlays, pixelfont, pixels, screen
from tablo.render.canvas import Canvas
from tablo.render.screen import _due_label

CFG = config.load(Path(__file__).resolve().parents[1] / "config.yaml", local=False)
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


@pytest.mark.parametrize("sprites,size", [(pixels.SMALL_SPRITES, pixels.SMALL), (pixels.BIG_SPRITES, pixels.BIG),
                                          (pixels.ICONS, pixels.ICON)])
def test_pixel_icons_fit_their_box(sprites, size):
    for name, rows in sprites.items():
        assert len(rows) <= size, name
        assert all(len(r) == size and set(r) <= {"#", "."} for r in rows), name


def test_clouds_with_something_under_them_are_one_cloud():
    for sprites, cloud in ((pixels.SMALL_SPRITES, pixels.SMALL_SPRITES["cloud"]), (pixels.BIG_SPRITES, pixels.BIG_SPRITES["rain1"][:27])):
        for kind in ("rain1", "rain2", "rain3", "snow", "storm", "fog"):
            assert sprites[kind][:len(cloud)] == cloud, kind


def test_block_icons_have_pixel_versions():
    assert set(screen.CATEGORY_ICONS.values()) | set(screen.SOURCE_ICONS.values()) <= set(pixels.ICONS)


@pytest.mark.parametrize("size,weight", [(15, "medium"), (16, "medium"), (16, "semibold"), (30, "semibold")])
def test_screen_fonts_have_pixel_versions(size, weight):
    font = fonts.inter(size, weight)
    pf = pixelfont.lookup(font)
    assert pf is not None and (pf.ascent, pf.descent) == font.getmetrics()
    for ch in map(chr, range(32, 127)):
        g = pf.glyphs[ch]
        assert all(len(r) == len(g.rows[0]) and set(r) <= {"#", "."} for r in g.rows), ch
        assert 0 <= g.top and g.top + len(g.rows) <= pf.ascent + pf.descent, ch


def test_pixel_text_keeps_one_baseline_and_falls_back_to_freetype():
    c, font = Canvas(), fonts.inter(16, "medium")
    c.text((10, 10), "Physics", font)
    c.text((110, 10), "Oct 21", font)
    c.text((210, 10), "Ж", font)  # no pixel glyph: drawn by FreeType
    bw = c.to_bw()
    bottoms = [bw.crop((x, 0, x + 90, 60)).point(lambda v: 255 - v).getbbox()[3] for x in (10, 110)]
    assert bottoms[1] == 10 + 16  # the digits sit on the baseline, ascent 16 below the top
    assert bottoms[0] > bottoms[1]  # "y" goes below it
    assert bw.crop((205, 0, 260, 60)).point(lambda v: 255 - v).getbbox() is not None
    assert c.width("Oct 21", font) == pixelfont.width(pixelfont.lookup(font), font, "Oct 21")


@pytest.mark.parametrize("name", ["Inter-Medium-15", "Inter-Medium-16", "Inter-SemiBold-16", "Inter-SemiBold-30", "clock-64"])
def test_letters_and_digits_stand_on_common_lines(name):
    pf = pixelfont.load(pixelfont.PIXEL_DIR / f"{name}.txt")
    groups = ["ABCDEFGHIJKLMNOPRSTUVWXYZ", "0123456789", "acemnorsuvwxz", "bdfhkl"]
    for chars in groups:
        spans = {ch: (pf.glyphs[ch].top, pf.glyphs[ch].top + len(pf.glyphs[ch].rows)) for ch in chars if ch in pf.glyphs}
        assert len(set(spans.values())) <= 1, spans
        if spans:
            assert next(iter(spans.values()))[1] == pf.ascent  # last row right above the baseline


def test_clock_digits_fit_the_firmware_zone():
    pf = pixelfont.load(pixelfont.PIXEL_DIR / "clock-64.txt")
    x, y, w, h = protocol.FIRMWARE_ZONES["clock"]
    widths = {sum(pf.glyphs[ch].advance for ch in f"{hh:02d}:{mm:02d}") for hh in range(24) for mm in range(60)}
    assert widths == {174}  # one width whatever the time
    assert 6 + 174 <= w  # the emulator and the firmware start at x + 6
    right = max(6 + 40 * 3 + 14 + pf.glyphs[d].left + len(pf.glyphs[d].rows[0]) for d in "0123456789")
    assert right <= w


def test_due_labels():
    today = dt.date(2026, 10, 18)
    assert _due_label(today, today) == "today"
    assert _due_label(today + dt.timedelta(days=1), today) == "tomorrow"
    assert _due_label(dt.date(2026, 10, 25), today) == "Oct 25"
    assert _due_label(today - dt.timedelta(days=1), today) == "overdue"


def test_deadlines_are_drawn_as_infomaster_gives_them():
    today = NOW.date()
    items = tuple(Deadline(f"HW {n}", today + dt.timedelta(days=n), "study", "hseapp") for n in range(6, 0, -1))
    model = ScreenModel(today=today, deadlines=(*items, Deadline("old", today - dt.timedelta(days=9), "study", "tg")))
    c = Canvas()
    screen._deadlines(c, model)
    # Five rows of the seven, in the order given (no sorting, no window): "+2" in the header.
    plain = Canvas()
    screen._block_header(plain, screen.DEADLINES, "Deadlines", "+2")
    header = (0, 100, 272, 36)
    assert _black(c.to_bw(), header) == _black(plain.to_bw(), header)
    first = Canvas()
    screen._row(first, screen.DEADLINES, 0, "HW 6", "Oct 24", left_x=screen.DEADLINE_TEXT_X)
    row = (screen.DEADLINE_TEXT_X, 144, 200, 22)
    assert _black(c.to_bw(), row) == _black(first.to_bw(), row)


def test_news_problem_replaces_no_news():
    with_problem = screen.render(ScreenModel(today=NOW.date(), news_problem="news unavailable")).to_bw()
    without = screen.render(ScreenModel(today=NOW.date())).to_bw()
    first_line = (screen.NEWS[0] + 8, 144, 200, 22)
    assert _black(with_problem, first_line) != _black(without, first_line)


def test_wrap_marks_cut_text():
    c = Canvas()
    from tablo.render import fonts
    lines = c.wrap("one two three four five six seven eight nine ten eleven twelve", fonts.inter(16), 120, 2)
    assert len(lines) == 2 and lines[-1].endswith("…")


def test_overlays_render():
    assert overlays.wifi_qr(CFG.wifi_networks).to_bw().size == (800, 480)
    assert overlays.message("Title", "Body\nsecond line", "mdi:bell").to_bw().size == (800, 480)


def test_all_demo_off_renders_empty_blocks():
    cfg = config.load(Path(__file__).resolve().parents[1] / "config.yaml", local=False)
    cfg.demo = dict.fromkeys(cfg.demo, False)
    model = builder.build(NOW, cfg, None)
    assert model.weather is None and not model.news and model.home is None
    assert not any(t.on for t in model.tiles) and model.tiles[1].icon == "mdi:ceiling-light"
    assert screen.render(model).to_bw().size == (800, 480)
