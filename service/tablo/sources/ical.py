"""Classes from the RUZ timetable in iCal (tablo-software.md §7.3).

The feed covers about five weeks and answers 304 to a matching ETag, so an
hourly poll costs almost nothing. Events keep the course name as given (Russian
with "(рус)" or long English); the subject dictionary turns it into a short
English title when the screen is built, so an edit of the dictionary shows at
once. "Ongoing interim assessment" (Текущий рубежный контроль) events also go to
Deadlines as Midterm (§7.2).
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
from ..llm import LLMError
from ..model import ClassItem, Deadline
from ..store import Store
from ..subjects import Subjects, clean

log = logging.getLogger(__name__)

EVENTS_KEY = "ical.events"
STALE_AFTER = dt.timedelta(hours=12)  # failing longer than this shows up on screen
MAX_CLASSES = 3
MIDTERM_KINDS = ("рубежный контроль", "interim assessment")
LINK = re.compile(r"https?://")


@dataclass(frozen=True)
class Event:
    uid: str
    start: dt.datetime  # local time, naive
    end: dt.datetime
    subject: str  # course name as the feed gives it, without "(рус)"
    room: str  # "R609", "online" or ""
    kind: str  # first line of DESCRIPTION: "Lecture", "Seminar", "Ongoing interim assessment"

    @property
    def midterm(self) -> bool:
        kind = self.kind.casefold()
        return any(k in kind for k in MIDTERM_KINDS)

    def to_json(self) -> dict:
        return {"uid": self.uid, "start": self.start.isoformat(), "end": self.end.isoformat(),
                "subject": self.subject, "room": self.room, "kind": self.kind}

    @classmethod
    def from_json(cls, d: dict) -> "Event":
        return cls(d["uid"], dt.datetime.fromisoformat(d["start"]), dt.datetime.fromisoformat(d["end"]),
                   d["subject"], d["room"], d["kind"])


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


def parse(text: str | bytes, tz: ZoneInfo) -> list[Event]:
    events = []
    for ev in icalendar.Calendar.from_ical(text).walk("VEVENT"):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        subject = clean(ev.get("SUMMARY"))
        if not subject or ev.get("DTSTART") is None:
            continue
        start = _local(ev.decoded("DTSTART"), tz)
        end = _local(ev.decoded("DTEND"), tz) if ev.get("DTEND") is not None else start
        description = str(ev.get("DESCRIPTION", ""))
        kind = description.split("\n", 1)[0].strip()
        where = room(str(ev.get("LOCATION", "")), description, str(ev.get("URL", "")))
        events.append(Event(str(ev.get("UID", "")), start, end, subject, where, kind))
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
    subjects_error: str | None = None


@dataclass
class IcalSource:
    get_cfg: Callable[[], Config]
    store: Store
    subjects: Subjects
    on_change: Callable[[], None]
    now: Callable[[], dt.datetime]
    status: Status = field(default_factory=Status)
    _wake: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def cfg(self):
        return self.get_cfg().ical

    def events(self) -> list[Event]:
        """Last known feed, kept in the store so a restart shows it before the first poll."""
        saved = self.store.get_json(EVENTS_KEY) or {}
        return [Event.from_json(d) for d in saved.get("events", [])]

    def _title(self, name: str) -> str:
        s = self.subjects.get(name)
        return s.title if s else name

    def classes(self) -> tuple[tuple[ClassItem, ...], str]:
        items, label = pick(self.events(), self.now())
        return tuple(ClassItem(e.start.time(), self._title(e.subject), e.room) for e in items), label

    def deadlines(self) -> tuple[Deadline, ...]:
        result = []
        for e in self.events():
            if e.midterm:
                s = self.subjects.get(e.subject)
                result.append(Deadline(f"{s.abbr if s else e.subject} Midterm", e.start.date(), "study", "ical",
                                       course=s.abbr if s else None))
        return tuple(result)

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

        # Every poll, not only on a new feed: names left untranslated while Haiku was down get another try.
        try:
            await self.subjects.resolve(e.subject for e in events)
            self.status.subjects_error = None
        except LLMError as e:
            self.status.subjects_error = str(e)
            log.warning("subject names: %s; showing the names from the feed", e)

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
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), max(1, self.cfg.poll_minutes) * 60)
            except asyncio.TimeoutError:
                pass
