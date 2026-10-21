"""Timetable from infomaster's tablo.ics, against a fake feed (no real link)."""

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from aiohttp import web

from tablo import config
from tablo.model import ClassItem, ScreenModel
from tablo.render import screen
from tablo.sources import ical
from tablo.store import Store

# Written by infomaster's own feed builder (outputs/ical_feed.py).
FEED = (Path(__file__).parent / "fixtures" / "tablo.ics").read_bytes()
MSK = ZoneInfo("Europe/Moscow")
SUNDAY = dt.datetime(2026, 10, 18, 12, 0)


def by_uid(events):
    return {e.uid: e for e in events}


def test_parse_rooms_names_marks_and_local_times():
    events = ical.parse(FEED, MSK)
    e = by_uid(events)
    assert e["ruz-1001"].subject == "Calculus"  # SUMMARY as it is
    assert e["ruz-1001"].start == dt.datetime(2026, 10, 19, 9, 30)
    assert e["ruz-1001"].end == dt.datetime(2026, 10, 19, 10, 50)
    assert [e[f"ruz-100{k}"].room for k in "1234"] == ["D208", "R401", "online", ""]
    assert {uid: x.mark for uid, x in e.items() if x.mark} == {
        "ruz-1005": "cancelled", "ruz-1006": "moved", "tg-77": "optional"}
    assert e["ruz-1007"].kind == "Interim assessment"
    assert events == sorted(events, key=lambda x: x.start)


def test_optional_by_either_field_and_moved_wins():
    def one(*lines):
        body = "\r\n".join(["BEGIN:VCALENDAR", "BEGIN:VEVENT", "UID:x", "DTSTART:20261019T063000Z",
                            "SUMMARY:Debate club", *lines, "END:VEVENT", "END:VCALENDAR"])
        return ical.parse(body, MSK)[0].mark

    assert one("STATUS:TENTATIVE") == "optional"
    assert one("X-UNI-OPTIONAL:TRUE") == "optional"
    assert one("STATUS:CONFIRMED") is None
    assert one("STATUS:TENTATIVE", "DESCRIPTION:Event\\nMoved from Tue Oct 20 13:00") == "moved"
    assert one("DESCRIPTION:Moved from the chat") is None  # only a note under the type counts


@pytest.mark.parametrize("now, label, starts", [
    (SUNDAY, "tomorrow", ["09:30", "11:10", "13:00", "16:40"]),
    (dt.datetime(2026, 10, 19, 10, 0), "today", ["09:30", "11:10", "13:00", "16:40"]),  # 09:30 is still on
    (dt.datetime(2026, 10, 19, 14, 30), "today", ["16:40"]),
    (dt.datetime(2026, 10, 19, 18, 0), "tomorrow", ["09:30"]),  # cancelled, but shown with its mark
    (dt.datetime(2026, 10, 20, 12, 0), "tomorrow", ["09:30", "18:00"]),
    (dt.datetime(2026, 10, 15, 8, 0), "Mon", ["09:30", "11:10", "13:00", "16:40"]),
    (dt.datetime(2026, 10, 10, 8, 0), "Oct 19", ["09:30", "11:10", "13:00", "16:40"]),
    (dt.datetime(2026, 11, 1, 8, 0), "", []),
])
def test_pick(now, label, starts):
    items, got = ical.pick(ical.parse(FEED, MSK), now)
    assert got == label
    assert [e.start.strftime("%H:%M") for e in items] == starts


@pytest.fixture
async def feed(aiohttp_server):
    state = {"calls": 0, "if_none_match": [], "status": 200}

    async def cal(request):
        state["calls"] += 1
        state["if_none_match"].append(request.headers.get("If-None-Match"))
        if state["status"] != 200:
            return web.Response(status=state["status"])
        if request.headers.get("If-None-Match") == 'W/"v1"':
            return web.Response(status=304)
        return web.Response(body=FEED, content_type="text/calendar", headers={"ETag": 'W/"v1"'})

    app = web.Application()
    app.router.add_get("/calendar/secret/tablo.ics", cal)
    server = await aiohttp_server(app)
    state["url"] = str(server.make_url("/calendar/secret/tablo.ics"))
    return state


def make_source(url, store=None, now=SUNDAY):
    cfg = config.Config()
    cfg.ical.url = url
    src = ical.IcalSource(get_cfg=lambda: cfg, store=store or Store(), on_change=lambda: None, now=lambda: now)
    return src, cfg


async def test_poll_uses_etag(feed):
    src, _ = make_source(feed["url"])
    assert await src.poll() is True
    assert await src.poll() is False
    assert feed["if_none_match"] == [None, 'W/"v1"']
    classes, label = src.classes()
    assert label == "tomorrow"
    assert classes == (ClassItem(dt.time(9, 30), "Calculus", "D208"), ClassItem(dt.time(11, 10), "Algebra", "R401"),
                       ClassItem(dt.time(13, 0), "Rus Statehood", "online"), ClassItem(dt.time(16, 40), "Discrete Math", ""))
    assert src.problem() is None


async def test_marks_reach_the_classes_block(feed):
    src, _ = make_source(feed["url"], now=dt.datetime(2026, 10, 20, 12, 0))
    await src.poll()
    classes, label = src.classes()
    assert label == "tomorrow"
    assert [(c.subject, c.room, c.mark) for c in classes] == [
        ("Intro to SE", "109", "moved"), ("Career talk", "G406", "optional")]
    screen.render(ScreenModel(today=dt.date(2026, 10, 20), classes=classes, classes_label=label))


async def test_failing_feed_keeps_saved_events_then_reports(feed):
    store = Store()
    src, _ = make_source(feed["url"], store=store)
    await src.poll()
    feed["status"] = 503
    late = make_source(feed["url"], store=store, now=SUNDAY + dt.timedelta(hours=13))[0]
    await late.poll()
    assert late.classes()[0]  # last known timetable stays on screen
    assert late.problem() == "timetable unavailable"


def test_saved_events_from_before_the_marks_still_load():
    store = Store()
    store.put_json(ical.EVENTS_KEY, {"fetched_at": SUNDAY.isoformat(), "events": [
        {"uid": "1", "start": "2026-10-19T09:30:00", "end": "2026-10-19T10:50:00", "subject": "Calculus",
         "room": "D208", "kind": "Seminar"}]})
    src, _ = make_source("http://x", store=store)
    assert src.classes()[0] == (ClassItem(dt.time(9, 30), "Calculus", "D208"),)


def test_a_full_day_fills_the_block():
    day = "\r\n".join(["BEGIN:VCALENDAR", *(line for h in range(8, 15) for line in (
        "BEGIN:VEVENT", f"UID:{h}", f"DTSTART:20261019T{h - 3:02d}0000Z", f"DTEND:20261019T{h - 3:02d}5000Z",
        f"SUMMARY:Class {h}", "END:VEVENT")), "END:VCALENDAR"])
    items, label = ical.pick(ical.parse(day, MSK), SUNDAY)
    assert label == "tomorrow" and len(items) == ical.MAX_CLASSES == screen._rows(screen.CLASSES) == 5


def test_no_link_is_a_problem():
    src, _ = make_source("")
    assert src.problem() == "calendar link not set"
    assert src.classes() == ((), "")
    screen.render(ScreenModel(today=SUNDAY.date(), classes_problem=src.problem()))
