"""Deadlines, news and grades from infomaster, against a fake infomaster (answers as in its API, §7)."""

import datetime as dt

import pytest
from aiohttp import web

from tablo import config
from tablo.model import Deadline, Grade, NewsItem
from tablo.sources import infomaster
from tablo.store import Store

NOW = dt.datetime(2026, 10, 21, 15, 0)
TOKEN = "um-token"

DEADLINES = {"items": [
    {"uid": "hseapp-3f2a9c01be", "title": "DM HW 5", "due": "2026-10-22", "category": "study", "source": "hseapp",
     "overdue": False},
    {"uid": "ha-1", "title": "Dentist", "due": "2026-10-25", "category": "personal", "source": "ha", "overdue": False},
    {"uid": "ical-9", "title": "RSF Midterm", "due": "2026-10-19", "category": "study", "source": "ical",
     "overdue": True},
]}
NEWS = {"items": [
    {"id": 17, "source": "tg", "study": True, "posted_at": "2026-10-21T14:05:00",
     "full": "Calc KR-1 Oct 22/23 · Alg KR-1 Nov 7", "short": "Calc & Alg tests: Oct 22, Nov 7", "importance": 5},
    {"id": 18, "source": "mail", "study": False, "posted_at": "2026-10-21T12:00:00",
     "full": "Library closed on Saturday", "short": "", "importance": 2},
], "ttl_hours": 24}
GRADES = {"items": [
    {"key": "a", "label": "DM HW 1A", "value": 9.0, "bonus": 1.0, "seen_at": "2026-10-21T13:00:00"},
    {"key": "b", "label": "Calc Quiz 2", "value": 6, "bonus": None, "seen_at": "2026-10-20T10:00:00"},
], "window_days": 7}


def status(**changes):
    data = {
        "hseapp": {"enabled": True, "logged_in": True, "login_needed": False, "ok_at": "2026-10-21T14:50:00",
                   "error": None, "items": 4, "done": 9, "labels_error": None},
        "ruz": {"ok_at": "2026-10-21T14:00:00", "error": None, "classes": 40, "subjects_error": None},
        "batches": {"ok_at": "2026-10-21T14:55:00", "error": None, "queue": 0},
        "grades": {"configured": True, "sheets": {
            "s1": {"title": "DM", "ok_at": "2026-10-21T14:30:00", "error": None, "tabs": 2, "items": 5, "unread": 0},
            "s2": {"title": "Calc", "ok_at": "2026-10-21T14:30:00", "error": None, "tabs": 1, "items": 3,
                   "unread": 0}}, "llm": True, "new": 2},
        "mail": {"configured": True, "ok_at": None, "error": None, "last": None, "letters": 0},
        "telegram": {"ok_at": None, "error": None, "login_needed": False},
        "llm": {"spent_usd": 0.1, "limit_usd": 0.5, "raised_usd": 0, "level": "ok"},
    }
    for key, value in changes.items():
        data[key] = {**data[key], **value}
    return data


@pytest.fixture
async def fake(aiohttp_server):
    """infomaster's internal API; `answers` and `token` can change between polls."""
    state = {"answers": {"deadlines": DEADLINES, "news": NEWS, "grades": GRADES, "status": status()},
             "token": TOKEN, "calls": []}

    async def api(request):
        name = request.match_info["name"]
        state["calls"].append(name)
        if request.headers.get("Authorization") != f"Bearer {state['token']}":
            raise web.HTTPUnauthorized(text="Bearer token required")
        answer = state["answers"][name]
        if isinstance(answer, int):
            return web.Response(status=answer)
        if isinstance(answer, str):
            return web.Response(text=answer, content_type="application/json")
        return web.json_response(answer)

    app = web.Application()
    app.router.add_get("/api/{name}", api)
    server = await aiohttp_server(app)
    state["url"] = str(server.make_url(""))
    return state


def make_source(url, store=None, now=NOW, token=TOKEN):
    cfg = config.Config()
    cfg.infomaster.url, cfg.infomaster_token = url, token
    changes = []
    clock = {"now": now}
    src = infomaster.InfomasterSource(get_cfg=lambda: cfg, store=store or Store(),
                                    on_change=lambda: changes.append(1), now=lambda: clock["now"])
    return src, changes, clock


async def test_good_answers_fill_the_blocks(fake):
    src, changes, _ = make_source(fake["url"])
    assert await src.poll() is True
    assert fake["calls"] == ["deadlines", "news", "grades", "status"]
    assert src.deadlines() == (Deadline("DM HW 5", dt.date(2026, 10, 22), "study", "hseapp"),
                               Deadline("Dentist", dt.date(2026, 10, 25), "personal", "ha"),
                               Deadline("RSF Midterm", dt.date(2026, 10, 19), "study", "ical"))  # order as given
    assert src.news() == (NewsItem("Calc KR-1 Oct 22/23 · Alg KR-1 Nov 7", "tg", "Calc & Alg tests: Oct 22, Nov 7",
                                   5, True),
                          NewsItem("Library closed on Saturday", "mail", "", 2, False))
    assert src.grades() == (Grade("DM HW 1A", 9.0, 1.0), Grade("Calc Quiz 2", 6.0, None))
    assert src.status.error is None and src.status.ok_at == NOW.isoformat()
    assert not src.down()
    assert (src.deadlines_problem(), src.grades_problem(), src.news_problem()) == (None, None, None)
    assert changes == [1]
    # The same answers again: nothing to draw.
    assert await src.poll() is False and changes == [1]


async def test_wrong_token_keeps_saved_data_and_goes_down_later(fake):
    store = Store()
    src, _, clock = make_source(fake["url"], store)
    await src.poll()
    fake["token"] = "rotated"
    fake["calls"].clear()
    assert await src.poll() is True  # the error is news to the status line
    assert fake["calls"] == ["deadlines"]  # one 401 is enough
    assert "401" in src.status.error
    assert src.deadlines()[0].title == "DM HW 5"
    assert not src.down()  # a short break does not show yet
    clock["now"] = NOW + infomaster.DOWN_AFTER + dt.timedelta(minutes=1)
    await src.poll()
    assert src.down()
    fake["token"] = TOKEN
    await src.poll()
    assert not src.down() and src.status.error is None


async def test_unreachable_shows_saved_data_after_restart(fake, unused_tcp_port):
    store = Store()
    await make_source(fake["url"], store)[0].poll()
    # Restarted while infomaster is down: the saved lists, and the status line says they are old.
    later = NOW + dt.timedelta(hours=1)
    src, _, _ = make_source(f"http://127.0.0.1:{unused_tcp_port}", store, now=later)
    await src.poll()
    assert src.status.error.startswith("deadlines: ClientConnectorError") and "news" not in src.status.error
    assert len(src.news()) == 2 and src.down()


async def test_nothing_saved_and_no_token():
    src, _, _ = make_source("http://127.0.0.1:9", token="")
    await src.poll()
    assert src.status.error == "TABLO_INFOMASTER_TOKEN not set"
    assert src.deadlines() == src.news() == src.grades() == () and src.down()


async def test_bad_answer_is_an_error_not_data(fake):
    store = Store()
    src, _, _ = make_source(fake["url"], store)
    await src.poll()
    fake["answers"]["news"] = {"items": [{"id": 1}]}
    fake["answers"]["grades"] = "not json"
    fake["answers"]["status"] = 500
    await src.poll()
    assert src.status.error.startswith("news: KeyError")
    assert "grades: JSONDecodeError" in src.status.error and "status: HTTP 500" in src.status.error
    assert len(src.news()) == 2 and len(src.grades()) == 2  # the last good ones


async def test_ok_at_null_after_a_restart_is_not_a_failure(fake):
    fake["answers"]["status"] = status(hseapp={"ok_at": None}, batches={"ok_at": None},
                                       grades={"sheets": {"s1": {"ok_at": None, "error": None}}})
    src, _, _ = make_source(fake["url"])
    await src.poll()
    assert (src.deadlines_problem(), src.grades_problem(), src.news_problem()) == (None, None, None)


@pytest.mark.parametrize("changes, problem", [
    ({"hseapp": {"login_needed": True, "logged_in": False}}, "HSE login needed"),
    ({"hseapp": {"error": "HTTP 502", "ok_at": "2026-10-21T14:00:00"}}, None),  # within 3 hours
    ({"hseapp": {"error": "HTTP 502", "ok_at": "2026-10-21T11:00:00"}}, "the university app unavailable"),
    ({"hseapp": {"error": "HTTP 502", "ok_at": None}}, "the university app unavailable"),
])
async def test_deadlines_problem(fake, changes, problem):
    fake["answers"]["status"] = status(**changes)
    src, _, _ = make_source(fake["url"])
    await src.poll()
    assert src.deadlines_problem() == problem
    assert src.login_needed() == (problem == "HSE login needed")


async def test_grades_and_news_problems(fake):
    sheets = status()["grades"]["sheets"]
    fake["answers"]["status"] = status(grades={"sheets": {**sheets, "s1": {**sheets["s1"], "error": "HTTP 403"}}},
                                       batches={"error": "LLM limit", "ok_at": "2026-10-21T10:00:00"})
    src, _, _ = make_source(fake["url"])
    await src.poll()
    assert src.grades_problem() == "1 sheet(s) failing"
    assert src.news_problem() == "news unavailable"
    fake["answers"]["status"] = status(grades={"sheets": {k: {**v, "error": "x"} for k, v in sheets.items()}})
    await src.poll()
    assert src.grades_problem() == "sheets unavailable" and src.news_problem() is None
