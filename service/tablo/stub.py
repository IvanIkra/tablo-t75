"""Demo data for blocks whose real sources come in later stages.

Dates are relative to `now`, so the screen looks plausible on any day.
"""

import datetime as dt

from .model import ClassItem, Deadline, Grade, HourForecast, NewsItem, WeatherNow

_FORECAST_ICONS = ("cloud", "rain1", "rain2", "rain3", "rain1", "rain1", "cloud", "moon")
_FORECAST_TEMPS = (7, 7, 6, 6, 5, 5, 4, 4)


def weather(now: dt.datetime) -> tuple[WeatherNow, tuple[HourForecast, ...]]:
    forecast = tuple(
        HourForecast(hour=(now.hour + i) % 24, temp=t, icon=icon)
        for i, (t, icon) in enumerate(zip(_FORECAST_TEMPS, _FORECAST_ICONS))
    )
    return WeatherNow(temp=9, feels=6, icon="rain1"), forecast


def deadlines(now: dt.datetime) -> tuple[Deadline, ...]:
    d = now.date()
    return (
        Deadline("Calc HW 5", d + dt.timedelta(days=1), "study", "hseapp"),
        Deadline("Physics lab report", d + dt.timedelta(days=3), "study", "mail"),
        Deadline("Renew passport photo", d + dt.timedelta(days=5), "personal", "ha"),
        Deadline("English essay", d + dt.timedelta(days=6), "study", "tg"),
        Deadline("DM HW 4", d + dt.timedelta(days=8), "study", "hseapp"),
        Deadline("Midterm: Calculus", d + dt.timedelta(days=12), "study", "ical"),
        Deadline("Algebra HW 6", d - dt.timedelta(days=1), "study", "hseapp"),
    )


def grades() -> tuple[Grade, ...]:
    return (
        Grade("DM HW 1A", 8.4),
        Grade("DM HW 1B", 9.5, bonus=1),
        Grade("Calc Quiz 2", 6),
        Grade("Algebra Sem 4", 6),
        Grade("Calc HW Oct 8", 10),
        Grade("DM Test 1", 7.5),
    )


def news() -> tuple[NewsItem, ...]:
    return (
        NewsItem("SE program: Discrete Math HW 3 deadline moved to Friday 23:59", "tg"),
        NewsItem("Dean's office: student ID renewal opens Monday, bring a photo", "mail"),
        NewsItem("Moscow: Pokrovsky Blvd closed for traffic this weekend", "tg"),
        NewsItem("Another messenger slowed down in Russia, VPN demand up", "tg"),
        NewsItem("Metro: Kitay-Gorod exit 4 closed until November", "tg"),
    )


def classes(now: dt.datetime) -> tuple[tuple[ClassItem, ...], str]:
    items = (
        ClassItem(dt.time(9, 30), "Calculus", "D208"),
        ClassItem(dt.time(11, 10), "Algebra", "R401", mark="moved"),
        ClassItem(dt.time(13, 0), "Career talk", "online", mark="optional"),
    )
    label = "today" if now.hour < 15 else "tomorrow"
    return items, label
