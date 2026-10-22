"""Deadlines, news and grades from infomaster (§7).

infomaster collects the university app, mail, Telegram chats and the grade sheets, merges
and ranks them, and gives the result over its internal API: every answer is the
full current state, in screen order. Tablo only shows it. Each good answer is
kept in the store, so a restart or infomaster being down still shows the last
known lists; past DOWN_AFTER without a good poll the status line says so (§2).
"""

import asyncio
import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import aiohttp

from ..config import Config
from ..model import Deadline, Grade, NewsItem
from ..store import Store
from . import nap

log = logging.getLogger(__name__)

ENDPOINTS = ("deadlines", "news", "grades", "status")
DOWN_AFTER = dt.timedelta(minutes=10)  # no good poll this long: the screen shows old data (§11)
HSEAPP_STALE_AFTER = dt.timedelta(hours=3)  # the university app failing longer than this shows up on screen
NEWS_STALE_AFTER = dt.timedelta(hours=3)


class BadAnswer(ValueError):
    """infomaster answered, but not with what Tablo can show."""


class Unauthorized(BadAnswer):
    """infomaster does not take our token."""


def _key(name: str) -> str:
    return f"infomaster.{name}"


def deadlines(data: dict) -> tuple[Deadline, ...]:
    return tuple(Deadline(str(d["title"]), dt.date.fromisoformat(d["due"]), d["category"], d["source"])
                 for d in data["items"])


def news(data: dict) -> tuple[NewsItem, ...]:
    return tuple(NewsItem(text=str(n["full"]), short=str(n.get("short") or ""), source=n["source"],
                          importance=int(n["importance"]), study=bool(n["study"]))
                 for n in data["items"])


def grades(data: dict) -> tuple[Grade, ...]:
    return tuple(Grade(str(g["label"]), float(g["value"]), None if g.get("bonus") is None else float(g["bonus"]))
                 for g in data["items"])


PARSERS = {"deadlines": deadlines, "news": news, "grades": grades, "status": lambda data: dict(data)}


def _check(name: str, data) -> None:
    """A malformed answer fails here, not at render time."""
    if not isinstance(data, dict):
        raise BadAnswer(f"{name}: not a JSON object")
    try:
        PARSERS[name](data)
    except (KeyError, TypeError, ValueError) as e:
        raise BadAnswer(f"{name}: {type(e).__name__}: {e}") from e


def _stale(item: dict, now: dt.datetime, after: dt.timedelta) -> bool:
    """A source that is failing now and has not worked for `after` (or not since infomaster started)."""
    if not item.get("error"):
        return False
    ok_at = item.get("ok_at")
    return not ok_at or now - dt.datetime.fromisoformat(ok_at) > after


@dataclass
class Status:
    ok_at: str | None = None  # the last poll in which all four answers were good
    error: str | None = None


@dataclass
class InfomasterSource:
    get_cfg: Callable[[], Config]
    store: Store
    on_change: Callable[[], None]
    now: Callable[[], dt.datetime]
    status: Status = field(default_factory=Status)
    _wake: asyncio.Event = field(default_factory=asyncio.Event)
    _was: tuple | None = None  # (error, down) after the last poll: DOWN_AFTER passes between polls

    @property
    def cfg(self):
        return self.get_cfg().infomaster

    @property
    def token(self) -> str:
        return self.get_cfg().infomaster_token

    def refetch(self) -> None:
        self._wake.set()

    def _saved(self, name: str) -> dict | None:
        return self.store.get_json(_key(name))

    def _data(self, name: str):
        saved = self._saved(name)
        return PARSERS[name](saved["data"]) if saved else PARSERS[name]({"items": []})

    def deadlines(self) -> tuple[Deadline, ...]:
        """Already picked and ordered as the block shows them (§7.2): the block takes the first rows."""
        return self._data("deadlines")

    def news(self) -> tuple[NewsItem, ...]:
        return self._data("news")

    def grades(self) -> tuple[Grade, ...]:
        return self._data("grades")

    def source_status(self) -> dict:
        """infomaster's own status of its sources, as last fetched."""
        saved = self._saved("status")
        return saved["data"] if saved else {}

    # --- problems on screen (§11) ---------------------------------------------

    def down(self) -> bool:
        """infomaster has not answered well for DOWN_AFTER: the screen shows the last saved data."""
        if self.status.error is None and self.status.ok_at is not None:
            return False
        fetched = [s["fetched_at"] if s else None for s in map(self._saved, ENDPOINTS)]
        if None in fetched:
            return True
        return self.now() - dt.datetime.fromisoformat(min(fetched)) > DOWN_AFTER

    def login_needed(self) -> bool:
        return bool(self.source_status().get("hseapp", {}).get("login_needed"))

    def deadlines_problem(self) -> str | None:
        hseapp = self.source_status().get("hseapp", {})
        if hseapp.get("login_needed"):
            return "HSE login needed"
        if _stale(hseapp, self.now(), HSEAPP_STALE_AFTER):
            return "the university app unavailable"
        return None

    def grades_problem(self) -> str | None:
        sheets = self.source_status().get("grades", {}).get("sheets") or {}
        failing = [s for s in sheets.values() if s.get("error")]
        if not failing:
            return None
        return "sheets unavailable" if len(failing) == len(sheets) else f"{len(failing)} sheet(s) failing"

    def news_problem(self) -> str | None:
        """Reading of new messages has been failing for a while: shown instead of "no news"."""
        if _stale(self.source_status().get("batches", {}), self.now(), NEWS_STALE_AFTER):
            return "news unavailable"
        return None

    # --- polling ----------------------------------------------------------------

    async def _get(self, session: aiohttp.ClientSession, name: str):
        async with session.get(f"{self.cfg.url.rstrip('/')}/api/{name}",
                               headers={"Authorization": f"Bearer {self.token}"}) as resp:
            if resp.status == 401:
                raise Unauthorized("401: infomaster refused TABLO_INFOMASTER_TOKEN")
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        _check(name, data)
        return data

    async def poll(self) -> bool:
        """One round of the four requests; returns whether anything on screen may have changed."""
        changed = False
        errors = []
        if not self.token:
            errors.append("TABLO_INFOMASTER_TOKEN not set")
        else:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                for name in ENDPOINTS:
                    try:
                        data = await self._get(session, name)
                    except Unauthorized as e:
                        errors.append(str(e))
                        break  # the same token for all four
                    except BadAnswer as e:
                        errors.append(str(e))
                        continue
                    except aiohttp.ClientResponseError as e:
                        errors.append(f"{name}: HTTP {e.status}")
                        continue
                    except (aiohttp.ClientConnectionError, asyncio.TimeoutError, OSError) as e:
                        errors.append(f"{name}: {type(e).__name__}: {e}")
                        break  # not reachable: the other three would only wait as long
                    except (aiohttp.ClientError, ValueError) as e:
                        errors.append(f"{name}: {type(e).__name__}: {e}")
                        continue
                    saved = self._saved(name)
                    changed |= saved is None or saved["data"] != data
                    self.store.put_json(_key(name), {"fetched_at": self.now().isoformat(), "data": data})
        if errors:
            self.status.error = "; ".join(errors)
            log.warning("infomaster failed: %s", self.status.error)
        else:
            self.status.error, self.status.ok_at = None, self.now().isoformat()
        state = (self.status.error, self.down())
        changed |= state != self._was
        self._was = state
        if changed:
            self.on_change()
        return changed

    async def run(self) -> None:
        while True:
            await self.poll()
            await nap(self._wake, max(10, self.cfg.poll_seconds))
