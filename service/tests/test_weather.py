"""Weather from Open-Meteo: icons, the stale forecast, polling against a fake server."""

import datetime as dt
import json
from pathlib import Path

import pytest
from aiohttp import web

from tablo import config
from tablo.sources import weather
from tablo.store import Store

ANSWER = json.loads((Path(__file__).parent / "fixtures" / "open-meteo.json").read_text())
FETCHED = dt.datetime(2026, 10, 18, 6, 20)  # the answer's "current" is 06:15, hours start at 06:00


def _saved(fetched=FETCHED, **current):
    return {"fetched_at": fetched.isoformat(), "current": {**ANSWER["current"], **current},
            "hourly": ANSWER["hourly"]}


@pytest.mark.parametrize("code, day, mm, chance, expected", [
    (0, True, 0, 0, "sun"),
    (1, False, 0, 10, "moon"),
    (3, True, 0, 30, "cloud"),
    (61, True, 0.4, 30, "cloud"),  # rain in the code, but unlikely
    (61, True, 0.4, 40, "rain1"),
    (63, True, 2.5, 80, "rain2"),
    (65, True, 7.6, 80, "rain2"),
    (82, True, 9, 90, "rain3"),
    (73, True, 1, 90, "snow"),
    (95, True, 5, 90, "storm"),
    (45, False, 0, 0, "fog"),
])
def test_icon(code, day, mm, chance, expected):
    assert weather.icon(code, day, mm, chance) == expected


def test_build_from_fresh_answer():
    now, forecast = weather.build(_saved(), FETCHED)
    assert (now.temp, now.feels, now.icon) == (9.2, 8.6, "fog")
    assert [h.hour for h in forecast] == list(range(6, 14))
    assert [h.icon for h in forecast[4:6]] == ["fog", "cloud"]


def test_rain_falling_now_shows_whatever_the_chance():
    now, _ = weather.build(_saved(weather_code=61, precipitation=0.6), FETCHED)
    assert now.icon == "rain1"


def test_stale_answer_shifts_by_the_hour_then_goes():
    now, forecast = weather.build(_saved(), FETCHED + dt.timedelta(hours=2))
    assert forecast[0].hour == 8 and len(forecast) == 8
    assert now.temp == ANSWER["hourly"]["temperature_2m"][2]
    assert weather.build(_saved(), FETCHED + dt.timedelta(hours=3, minutes=1)) == (None, ())
    assert weather.build(None, FETCHED) == (None, ())


async def test_poll_saves_and_keeps_the_last_answer_on_failure(aiohttp_server, monkeypatch):
    calls = []

    async def forecast(request):
        calls.append(dict(request.query))
        if len(calls) > 1:
            raise web.HTTPServiceUnavailable()
        return web.json_response(ANSWER)

    app = web.Application()
    app.router.add_get("/v1/forecast", forecast)
    server = await aiohttp_server(app)
    monkeypatch.setattr(weather, "URL", str(server.make_url("/v1/forecast")))

    cfg = config.Config()
    changes = []
    source = weather.WeatherSource(get_cfg=lambda: cfg, store=Store(), on_change=lambda: changes.append(1),
                                   now=lambda: FETCHED)
    await source.poll()
    assert calls[0]["timezone"] == "Europe/Moscow" and calls[0]["latitude"] == "55.7558"
    assert "precipitation_probability" in calls[0]["hourly"]
    assert source.status.error is None and source.current()[0].icon == "fog"

    await source.poll()
    assert "503" in source.status.error
    assert source.current()[0].temp == 9.2 and len(changes) == 2
