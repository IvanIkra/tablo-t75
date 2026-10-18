"""Timetable from iCal and the subject dictionary, against a fake feed (no real link)."""

import asyncio
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from aiohttp import web

from tablo import builder, config
from tablo.model import Deadline, ScreenModel
from tablo.render import screen
from tablo.sources import ical
from tablo.store import Store
from tablo.subjects import Subjects, clean

FEED = (Path(__file__).parent / "fixtures" / "ruz.ics").read_bytes()
MSK = ZoneInfo("Europe/Moscow")
SUNDAY = dt.datetime(2026, 10, 18, 12, 0)

NAMES = {
    "Математический анализ": ("Calculus", "Calc"),
    "Основы российской государственности": ("Rus Statehood", "RSF"),
    "Algebra": ("Algebra", "Alg"),
    "Discrete Mathematics": ("Discrete Math", "DM"),
    "Introduction into Software Engineering": ("Intro to SE", "SE"),
    "Foundations of Russian Statehood": ("Rus Statehood", "RSF"),
    "Введение в программирование": ("Intro to Prog", "Prog"),
}


class FakeLLM:
    available = True

    def __init__(self, names=NAMES):
        self.names = dict(names)
        self.prompts = []

    async def json(self, system, prompt, schema, max_tokens=8000):
        self.prompts.append(prompt)
        items = []
        for line in prompt.splitlines():
            if line.startswith("- id "):
                i, name = line[5:].split(": ", 1)
                title, abbr = self.names[name.strip('"')]
                items.append({"id": i, "title": title, "abbr": abbr})
        return {"items": items}


def subjects(llm=None, store=None, fits=lambda s: len(s) <= 13):
    return Subjects(llm or FakeLLM(), store or Store(), budget=13, fits=fits)


def by_uid(events):
    return {e.uid.split("@")[0][-1]: e for e in events}


def test_parse_rooms_names_and_local_times():
    events = ical.parse(FEED, MSK)
    e = by_uid(events)
    assert "8" not in e  # STATUS:CANCELLED
    assert e["1"].subject == "Математический анализ"  # folded "(р ус)" is dropped
    assert e["1"].start == dt.datetime(2026, 10, 19, 9, 30) and e["1"].end == dt.datetime(2026, 10, 19, 10, 50)
    assert [e[k].room for k in "12345"] == ["D208", "online", "R401", "online", "109"]
    assert e["6"].room == ""  # no location, no link
    assert [k for k, x in e.items() if x.midterm] == ["6", "7"]
    assert events == sorted(events, key=lambda x: x.start)


def test_clean_drops_rus_mark():
    assert clean("  Алгебра  (рус) ") == "Алгебра"
    assert clean("Algebra") == "Algebra"


@pytest.mark.parametrize("now, label, starts", [
    (SUNDAY, "tomorrow", ["09:30", "11:10", "13:00"]),
    (dt.datetime(2026, 10, 19, 10, 0), "today", ["09:30", "11:10", "13:00"]),  # 09:30 is still on
    (dt.datetime(2026, 10, 19, 14, 30), "today", ["16:40"]),
    (dt.datetime(2026, 10, 19, 18, 0), "Wed", ["09:30"]),  # Tuesday's class is cancelled
    (dt.datetime(2026, 10, 15, 8, 0), "Mon", ["09:30", "11:10", "13:00"]),
    (dt.datetime(2026, 10, 10, 8, 0), "Oct 19", ["09:30", "11:10", "13:00"]),
    (dt.datetime(2026, 11, 1, 8, 0), "", []),
])
def test_pick(now, label, starts):
    items, got = ical.pick(ical.parse(FEED, MSK), now)
    assert got == label
    assert [e.start.strftime("%H:%M") for e in items] == starts


async def test_subjects_ask_once_and_pass_known_names():
    llm = FakeLLM()
    s = subjects(llm)
    got = await s.resolve(["Algebra"])
    assert got["Algebra"].abbr == "Alg"
    llm.names["Алгебра"] = ("Algebra", "Alg")
    await s.resolve(["Algebra", "Алгебра (рус)"])
    assert len(llm.prompts) == 2
    assert '"Algebra": title "Algebra", abbr "Alg"' in llm.prompts[1]  # known entries keep languages consistent
    assert '- id 0: "Алгебра"' in llm.prompts[1]
    await s.resolve(["Алгебра", "Algebra"])
    assert len(llm.prompts) == 2


async def test_subject_too_wide_gets_one_retry():
    llm = FakeLLM({"Discrete Mathematics": ("Discrete Mathematics", "DM")})
    s = subjects(llm)

    async def answer(system, prompt, schema, max_tokens=8000):
        llm.prompts.append(prompt)
        title = "Discrete Math" if "too wide" in prompt else "Discrete Mathematics"
        return {"items": [{"id": "0", "title": title, "abbr": "DM"}]}

    llm.json = answer
    got = await s.resolve(["Discrete Mathematics"])
    assert got["Discrete Mathematics"].title == "Discrete Math"
    assert len(llm.prompts) == 2


async def test_concurrent_resolves_ask_each_name_once():
    llm = FakeLLM()
    ask = llm.json

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.01)  # both sources are waiting on Haiku at once, as at start-up
        return await ask(*args, **kwargs)

    llm.json = slow
    s = subjects(llm)
    await asyncio.gather(s.resolve(["Algebra"]), s.resolve(["Algebra", "Discrete Mathematics"]))
    assert len(llm.prompts) == 2
    assert '- id 0: "Discrete Mathematics"' in llm.prompts[1]
    assert '"Algebra": title "Algebra"' in llm.prompts[1]  # known by then, not asked again


async def test_manual_name_is_kept():
    s = subjects()
    s.set("Algebra", "Lin Alg", "LA")
    s.set("Algebra", "Algebra", "Alg", manual=False)
    assert s.get("Algebra").title == "Lin Alg"
    assert await s.resolve(["Algebra"]) == {"Algebra": s.get("Algebra")}


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
    app.router.add_get("/v3/ruz/cal/test", cal)
    server = await aiohttp_server(app)
    state["url"] = str(server.make_url("/v3/ruz/cal/test"))
    return state


def make_source(url, llm=None, store=None, now=SUNDAY):
    cfg = config.Config()
    cfg.ical.url = url
    store = store or Store()
    src = ical.IcalSource(get_cfg=lambda: cfg, store=store, subjects=subjects(llm, store),
                          on_change=lambda: None, now=lambda: now)
    return src, cfg


async def test_poll_uses_etag_and_dictionary(feed):
    llm = FakeLLM()
    src, _ = make_source(feed["url"], llm)
    assert await src.poll() is True
    assert await src.poll() is False
    assert feed["if_none_match"] == [None, 'W/"v1"']
    assert len(llm.prompts) == 1
    classes, label = src.classes()
    assert label == "tomorrow"
    assert [(c.start.strftime("%H:%M"), c.subject, c.room) for c in classes] == [
        ("09:30", "Calculus", "D208"), ("11:10", "Algebra", "R401"), ("13:00", "Rus Statehood", "online")]
    assert src.deadlines() == (
        Deadline("RSF Midterm", dt.date(2026, 10, 26), "study", "ical", "RSF"),
        Deadline("Prog Midterm", dt.date(2026, 10, 29), "study", "ical", "Prog"),
    )
    assert src.problem() is None


async def test_without_haiku_feed_names_are_shown_and_retried(feed):
    llm = FakeLLM()
    llm.available = False
    src, _ = make_source(feed["url"], llm)
    await src.poll()
    assert src.status.subjects_error
    assert src.classes()[0][0].subject == "Математический анализ"
    llm.available = True
    await src.poll()  # 304, but the names still get translated
    assert src.status.subjects_error is None
    assert src.classes()[0][0].subject == "Calculus"


async def test_failing_feed_keeps_saved_events_then_reports(feed):
    store = Store()
    src, _ = make_source(feed["url"], store=store)
    await src.poll()
    feed["status"] = 503
    late = make_source(feed["url"], store=store, now=SUNDAY + dt.timedelta(hours=13))[0]
    await late.poll()
    assert late.classes()[0]  # last known timetable stays on screen
    assert late.problem() == "timetable unavailable"


def test_no_link_is_a_problem():
    src, _ = make_source("")
    assert src.problem() == "calendar link not set"
    assert src.classes() == ((), "")


def test_link_comes_from_env(monkeypatch):
    monkeypatch.setenv("TABLO_ICAL_URL", "https://example.test/cal/x")
    assert config.from_dict({}).ical.url == "https://example.test/cal/x"


def test_merge_drops_duplicates_from_less_reliable_sources():
    hse = (Deadline("Prog midterm", dt.date(2026, 10, 29), "study", "hseapp", "Prog"),
           Deadline("DM HW 3", dt.date(2026, 10, 19), "study", "hseapp", "DM"))
    cal = (Deadline("Prog Midterm", dt.date(2026, 10, 29), "study", "ical", "Prog"),
           Deadline("RSF Midterm", dt.date(2026, 10, 26), "study", "ical", "RSF"),
           Deadline("DM Midterm", dt.date(2026, 10, 19), "study", "ical", "DM"))
    merged = builder.merge_deadlines(hse, cal)
    assert [(d.title, d.source) for d in merged] == [
        ("Prog midterm", "hseapp"), ("DM HW 3", "hseapp"), ("RSF Midterm", "ical"), ("DM Midterm", "ical")]


def test_classes_problem_and_budget():
    assert 12 <= round(screen.class_subject_width() / 8.1) <= 13
    assert screen.class_subject_fits("Intro to Prog")
    screen.render(ScreenModel(today=SUNDAY.date(), classes_problem="calendar link not set"))
