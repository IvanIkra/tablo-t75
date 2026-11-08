"""Classes from infomaster's tablo.ics feed (docs/software §7.3).

The feed has the RUZ classes, consultations and events from the chats, with
English names already (SUMMARY is shown as it is). Optional events (STATUS:TENTATIVE
or X-INFOMASTER-OPTIONAL:TRUE) are shown with a mark, as are classes moved ("Moved from …"
in DESCRIPTION) or cancelled. Interim assessments reach Deadlines from infomaster's
API, not from here.
"""

import asyncio
import datetime as dt
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import aiohttp
import icalendar

from ..config import Config
from ..model import ClassItem
from ..store import Store
from . import nap

log = logging.getLogger(__name__)

EVENTS_KEY = "ical.events"
STALE_AFTER = dt.timedelta(hours=12)  # failing longer than this shows up on screen
MAX_CLASSES = 5  # as many rows as the Classes block has
LINK = re.compile(r"https?://")
MOVED = "Moved from"  # infomaster's note under the type: the time is already the new one


@dataclass(frozen=True)
class Event:
    uid: str
    start: dt.datetime  # local time, naive
    end: dt.datetime
    subject: str  # SUMMARY: the English name from infomaster's dictionary
    room: str  # "R609", "online" or ""
    kind: str  # first line of DESCRIPTION: "Lecture", "Seminar", "Consultation", "Event"
    mark: str | None = None  # "cancelled" | "moved" | "optional" (§7.3: how each is drawn)

    def to_json(self) -> dict:
        return {"uid": self.uid, "start": self.start.isoformat(), "end": self.end.isoformat(),
                "subject": self.subject, "room": self.room, "kind": self.kind, "mark": self.mark}

    @classmethod
    def from_json(cls, d: dict) -> "Event":
        return cls(d["uid"], dt.datetime.fromisoformat(d["start"]), dt.datetime.fromisoformat(d["end"]),
                   d["subject"], d["room"], d["kind"], d.get("mark"))


def room(location: str, description: str, url: str) -> str:
    """'R609, ул. Примерная, д. 1' -> 'R609'; a meeting link -> 'online'."""
    location = location.strip()
    if location and not LINK.match(location):
        return location.split(",")[0].strip()
    if location or LINK.search(description) or url:
        return "online"
    return ""


def _local(value, tz: ZoneInfo) -> dt.datetime:
    if not isinstance(value, dt.datetime):  # all-day event
        value = dt.datetime.combine(value, dt.time())
    if value.tzinfo is not None:
        value = value.astimezone(tz).replace(tzinfo=None)
    return value


def mark(ev, description: str) -> str | None:
    """Cancelled first, then moved, then optional: a class gets one mark."""
    status = str(ev.get("STATUS", "")).upper()
    if status == "CANCELLED":
        return "cancelled"
    if any(line.strip().startswith(MOVED) for line in description.splitlines()[1:]):
        return "moved"
    if status == "TENTATIVE" or str(ev.get("X-INFOMASTER-OPTIONAL", "")).upper() == "TRUE":
        return "optional"
    return None


def parse(text: str | bytes, tz: ZoneInfo) -> list[Event]:
    events = []
    for ev in icalendar.Calendar.from_ical(text).walk("VEVENT"):
        subject = " ".join(str(ev.get("SUMMARY", "")).split())
        if not subject or ev.get("DTSTART") is None:
            continue
        start = _local(ev.decoded("DTSTART"), tz)
        end = _local(ev.decoded("DTEND"), tz) if ev.get("DTEND") is not None else start
        description = str(ev.get("DESCRIPTION", ""))
        kind = description.split("\n", 1)[0].strip()
        where = room(str(ev.get("LOCATION", "")), description, str(ev.get("URL", "")))
        events.append(Event(str(ev.get("UID", "")), start, end, subject, where, kind, mark(ev, description)))
    events.sort(key=lambda e: (e.start, e.subject))
    return events


def pick(events: list[Event], now: dt.datetime) -> tuple[list[Event], str]:
    """The next classes not over yet today; else those of the next day with classes, and the header label."""
    today = now.date()
    left = [e for e in events if e.start.date() == today and e.end > now]
    if left:
        return left[:MAX_CLASSES], "today"
    later = [e for e in events if e.start.date() > today]
    if not later:
        return [], ""
    day = later[0].start.date()
    days = (day - today).days
    if days == 1:
        label = "tomorrow"
    elif days < 7:
        label = day.strftime("%a")
    else:
        label = day.strftime("%b %d").replace(" 0", " ")
    return [e for e in later if e.start.date() == day][:MAX_CLASSES], label


@dataclass
class Status:
    ok_at: str | None = None
    error: str | None = None
    events: int = 0


@dataclass
class IcalSource:
    get_cfg: Callable[[], Config]
    store: Store
    on_change: Callable[[], None]
    now: Callable[[], dt.datetime]
    status: Status = field(default_factory=Status)
    _wake: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def cfg(self):
        return self.get_cfg().ical

    def refetch(self) -> None:
        self._wake.set()

    def events(self) -> list[Event]:
        """Last known feed, kept in the store so a restart shows it before the first poll."""
        saved = self.store.get_json(EVENTS_KEY) or {}
        return [Event.from_json(d) for d in saved.get("events", [])]

    def classes(self) -> tuple[tuple[ClassItem, ...], str]:
        items, label = pick(self.events(), self.now())
        return tuple(ClassItem(e.start.time(), e.subject, e.room, e.mark) for e in items), label

    def problem(self) -> str | None:
        if not self.cfg.url:
            return "calendar link not set"
        if self.status.error:
            saved = (self.store.get_json(EVENTS_KEY) or {}).get("fetched_at")
            if not saved or self.now() - dt.datetime.fromisoformat(saved) > STALE_AFTER:
                return "timetable unavailable"
        return None

    async def poll(self) -> bool:
        """One fetch; returns whether the events changed."""
        saved = self.store.get_json(EVENTS_KEY) or {}
        headers = {"If-None-Match": saved["etag"]} if saved.get("etag") and saved.get("events") else {}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
                async with session.get(self.cfg.url, headers=headers) as resp:
                    if resp.status == 304:
                        body, etag = None, saved["etag"]
                    else:
                        resp.raise_for_status()
                        body, etag = await resp.read(), resp.headers.get("ETag")
            events = self.events() if body is None else parse(body, ZoneInfo(self.get_cfg().display.tz_name))
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError) as e:
            self.status.error = f"{type(e).__name__}: {e}"
            log.warning("timetable failed: %s", self.status.error)
            self.on_change()
            return False

        new = [e.to_json() for e in events]
        changed = new != saved.get("events")
        self.store.put_json(EVENTS_KEY, {"fetched_at": self.now().isoformat(), "etag": etag, "events": new})
        self.status.error, self.status.ok_at, self.status.events = None, self.now().isoformat(), len(new)
        if changed:
            log.info("timetable: %d events", len(new))
        self.on_change()
        return changed

    async def run(self) -> None:
        while True:
            if self.cfg.url:
                await self.poll()
            await nap(self._wake, max(1, self.cfg.poll_minutes) * 60)
