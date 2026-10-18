"""Weather from Open-Meteo (tablo-software.md §7.4).

No key. One request gives the current weather and the hours ahead; the answer
is kept in the store, so a restart or a failing poll still shows the forecast,
shifted hour by hour, for up to three hours (STALE_AFTER).
"""

import asyncio
import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import aiohttp

from ..config import Config
from ..model import HourForecast, WeatherNow
from ..store import Store
from . import nap

log = logging.getLogger(__name__)

URL = "https://api.open-meteo.com/v1/forecast"
SAVED_KEY = "weather"
STALE_AFTER = dt.timedelta(hours=3)
FORECAST_HOURS = 8
CURRENT = ("temperature_2m", "apparent_temperature", "weather_code", "is_day", "precipitation")
HOURLY = ("temperature_2m", "apparent_temperature", "precipitation", "precipitation_probability",
          "weather_code", "is_day")
# Enough hours to fill the forecast after three stale hours.
FETCH_HOURS = FORECAST_HOURS + 4

FOG = {45, 48}
SNOW = {71, 73, 75, 77, 85, 86}
STORM = {95, 96, 99}
RAIN_CHANCE = 40  # %


def icon(code: int, is_day: bool, mm: float, chance: float | None) -> str:
    """Icon key for one hour (§7.4): the code first for snow, storm and fog, then rain by chance and amount."""
    if code in STORM:
        return "storm"
    if code in SNOW:
        return "snow"
    if code in FOG:
        return "fog"
    if chance is not None and chance >= RAIN_CHANCE:
        return "rain1" if mm < 2.5 else "rain2" if mm <= 7.6 else "rain3"
    if code <= 1:
        return "sun" if is_day else "moon"
    return "cloud"


def _hours(saved: dict) -> list[dict]:
    h = saved["hourly"]
    return [{"time": dt.datetime.fromisoformat(t), **{k: h[k][i] for k in HOURLY}} for i, t in enumerate(h["time"])]


def _hour_icon(row: dict) -> str:
    return icon(row["weather_code"], bool(row["is_day"]), row["precipitation"] or 0,
                row["precipitation_probability"])


def build(saved: dict | None, now: dt.datetime) -> tuple[WeatherNow | None, tuple[HourForecast, ...]]:
    """The screen's weather from a saved answer; nothing once it is older than STALE_AFTER."""
    if not saved or now - dt.datetime.fromisoformat(saved["fetched_at"]) > STALE_AFTER:
        return None, ()
    hour = now.replace(minute=0, second=0, microsecond=0)
    ahead = [r for r in _hours(saved) if r["time"] >= hour][:FORECAST_HOURS]
    if not ahead:
        return None, ()
    forecast = tuple(HourForecast(r["time"].hour, r["temperature_2m"], _hour_icon(r)) for r in ahead)

    cur = saved["current"]
    if dt.datetime.fromisoformat(cur["time"]) >= hour:
        # "current" has no probability of its own: rain falling now counts as certain, else the hour's chance.
        chance = 100 if cur["precipitation"] else ahead[0]["precipitation_probability"]
        now_icon = icon(cur["weather_code"], bool(cur["is_day"]), cur["precipitation"] or 0, chance)
        weather = WeatherNow(cur["temperature_2m"], cur["apparent_temperature"], now_icon)
    else:
        # A stale answer: the hour's forecast stands in for "now".
        r = ahead[0]
        weather = WeatherNow(r["temperature_2m"], r["apparent_temperature"], forecast[0].icon)
    return weather, forecast


@dataclass
class Status:
    ok_at: str | None = None
    error: str | None = None


@dataclass
class WeatherSource:
    get_cfg: Callable[[], Config]
    store: Store
    on_change: Callable[[], None]
    now: Callable[[], dt.datetime]
    status: Status = field(default_factory=Status)
    _wake: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def cfg(self):
        return self.get_cfg().weather

    def refetch(self) -> None:
        self._wake.set()

    def current(self) -> tuple[WeatherNow | None, tuple[HourForecast, ...]]:
        return build(self.store.get_json(SAVED_KEY), self.now())

    async def poll(self) -> None:
        params = {
            "latitude": self.cfg.latitude,
            "longitude": self.cfg.longitude,
            "timezone": self.get_cfg().display.tz_name,
            "current": ",".join(CURRENT),
            "hourly": ",".join(HOURLY),
            "forecast_hours": FETCH_HOURS,
        }
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(URL, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            saved = {"fetched_at": self.now().isoformat(),
                     "current": {k: data["current"][k] for k in ("time", *CURRENT)},
                     "hourly": {k: data["hourly"][k] for k in ("time", *HOURLY)}}
            build(saved, self.now())  # a malformed answer fails here, not at render time
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, TypeError, ValueError, OSError) as e:
            self.status.error = f"{type(e).__name__}: {e}"
            log.warning("weather failed: %s", self.status.error)
            self.on_change()  # the saved forecast may have just gone stale
            return
        self.store.put_json(SAVED_KEY, saved)
        self.status.error, self.status.ok_at = None, self.now().isoformat()
        self.on_change()

    async def run(self) -> None:
        while True:
            await self.poll()
            await nap(self._wake, max(1, self.cfg.poll_minutes) * 60)
