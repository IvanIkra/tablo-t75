"""Device hub: WebSocket connections, frames and button actions (§3, §4)."""

import asyncio
import datetime as dt
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import WSMsgType, web

from . import builder, news, protocol
from .config import Config, parse_demo
from .model import Deadline
from .llm import Haiku
from .sources import hseapp, ical, mail, telegram, weather
from .sources.grades import GradesSource, LayoutProvider
from .store import Store
from .subjects import Subjects
from .todo import Todo, uid
from .render import overlays, screen
from .render.canvas import Canvas, pack

log = logging.getLogger(__name__)

ACTION_TIMEOUT_S = 10
RENDER_DEBOUNCE_S = 2.0
HEALTH_INTERVAL_S = 60
CHANGED_EVENT = "tablo_changed"  # the HA integration reads status or deadlines again (§8.1)
REFETCH = ("grades", "hseapp", "ical", "news", "weather")


@dataclass
class Device:
    id: str
    ws: web.WebSocketResponse
    connected_at: float = field(default_factory=time.time)
    status: dict = field(default_factory=dict)
    fw: str | None = None
    last_seen: float = field(default_factory=time.time)


class Hub:
    def __init__(self, cfg: Config, ha, data_dir: Path | None = None, llm=None, real_ha=None):
        """ha: the fake house behind the "fake HA" demo switch; real_ha: HomeAssistant, if a token is set."""
        self.cfg = cfg
        self.ha = ha
        self.real_ha = real_ha
        self.data_dir = data_dir
        self.store = Store(data_dir / "tablo.db" if data_dir else ":memory:")
        self.llm = llm or Haiku()
        if hasattr(self.llm, "on_run"):
            self.llm.on_run = self._on_llm_run
        self.grades = GradesSource(
            get_cfg=lambda: self.cfg,
            store=self.store,
            layouts=LayoutProvider(self.llm, self.store),
            on_change=lambda: self.schedule_render(0.5),
            now=self.now,
        )
        self.subjects = Subjects(self.llm, self.store, budget=round(screen.class_subject_width() / 8.1),
                                 fits=screen.class_subject_fits)
        self.hseapp = hseapp.HseAppSource(
            get_cfg=lambda: self.cfg,
            store=self.store,
            auth=hseapp.Auth(self.store),
            labels=hseapp.LabelProvider(self.llm, self.store, budget=round(screen.deadline_title_width() / 8.1),
                                        fits=screen.deadline_title_fits),
            on_change=lambda: self.schedule_render(0.5),
            now=self.now,
            subjects=self.subjects,
        )
        self.ical = ical.IcalSource(
            get_cfg=lambda: self.cfg,
            store=self.store,
            subjects=self.subjects,
            on_change=lambda: self.schedule_render(0.5),
            now=self.now,
        )
        self.news = news.NewsSource(
            get_cfg=lambda: self.cfg,
            llm=self.llm,
            store=self.store,
            subjects=self.subjects,
            budget=news.screen_budget(),
            on_change=lambda: self.schedule_render(0.5),
            now=self.now,
        )
        # Saves new posts only; they reach the screen once Haiku has read them.
        self.telegram = telegram.TelegramSource(get_cfg=lambda: self.cfg, store=self.store, now=self.now,
                                                on_new=self.news.wake)
        self.mail = mail.MailSource(get_cfg=lambda: self.cfg, store=self.store, now=self.now, on_new=self.news.wake)
        self.weather = weather.WeatherSource(get_cfg=lambda: self.cfg, store=self.store,
                                             on_change=lambda: self.schedule_render(0.5), now=self.now)
        self.todo = Todo(self.store)
        self.subjects.set_manual((s.name, s.title, s.abbr) for s in cfg.subjects)
        self.devices: dict[str, Device] = {}
        self._signature: tuple | None = None
        self.last_seen: float | None = None  # last message from any panel; kept after it goes offline
        self.last_rssi: int | None = None
        self.base: protocol.Frame | None = None
        self.synced_at: dt.datetime | None = None
        self._frame_id = 0
        self._render_lock = asyncio.Lock()
        self._render_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        for h in (ha, real_ha):
            if h is not None:
                h.add_listener(lambda entity, old, new: self.schedule_render())
                h.add_status_listener(self._on_ha_status)
        self._set_home_templates()
        self._load_demo()

    def _set_home_templates(self) -> None:
        """HA keeps the Home rows rendered and pushes new results as their entities change (§8.3)."""
        templates = [row.template for row in self.cfg.home.rows]
        for h in (self.ha, self.real_ha):
            if h is not None:
                h.set_templates(templates)

    def set_config(self, cfg: Config) -> None:
        """A config from HA. A source whose links changed polls at once, not on its schedule."""
        old, self.cfg = self.cfg, cfg
        self.subjects.set_manual((s.name, s.title, s.abbr) for s in cfg.subjects)
        self._set_home_templates()
        changed = {"grades": (old.grades.sheets, old.grades.student) != (cfg.grades.sheets, cfg.grades.student),
                   "ical": old.ical.url != cfg.ical.url,
                   "news": old.news.channels != cfg.news.channels,
                   "hseapp": old.hseapp.enabled != cfg.hseapp.enabled,
                   "weather": (old.weather.latitude, old.weather.longitude)
                   != (cfg.weather.latitude, cfg.weather.longitude)}
        if any(changed.values()):
            self.refetch([name for name, yes in changed.items() if yes])

    # --- demo data switches ---------------------------------------------------

    @property
    def active_ha(self):
        """The fake HA while its demo switch is on, else the real one (None without a token)."""
        return self.ha if self.cfg.demo["ha"] else self.real_ha

    def _on_ha_status(self) -> None:
        """Connection to HA came or went: the house icon in the status line follows at once."""
        self._spawn(self.broadcast(self.health_message()))
        self.schedule_render(0.5)

    def _demo_path(self) -> Path | None:
        return self.data_dir / "demo.json" if self.data_dir else None

    def _load_demo(self) -> None:
        path = self._demo_path()
        if path and path.exists():
            try:
                self.cfg.demo.update(parse_demo(json.loads(path.read_text())))
            except ValueError as e:
                log.warning("ignoring %s: %s", path, e)

    async def set_demo(self, changes: dict[str, bool]) -> dict[str, bool]:
        self.cfg.demo.update(parse_demo(changes))
        path = self._demo_path()
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.cfg.demo, indent=2))
        await self.broadcast(self.health_message())
        await self.push_base()
        return dict(self.cfg.demo)

    # --- time -----------------------------------------------------------------

    def now(self) -> dt.datetime:
        return dt.datetime.now(ZoneInfo(self.cfg.display.tz_name)).replace(tzinfo=None)

    # --- frames ---------------------------------------------------------------

    def _next_id(self) -> int:
        self._frame_id = (self._frame_id + 1) & 0xFFFFFFFF
        return self._frame_id

    async def render_base(self) -> protocol.Frame:
        """Render the main screen; returns the current base frame (new or unchanged)."""
        async with self._render_lock:
            classes, classes_label = self.ical.classes()
            deadlines = self.deadlines()
            self._check_changed(deadlines)
            model = builder.build(self.now(), self.cfg, self.active_ha, weather=self.weather.current(),
                                  grades=self.grades.current(),
                                  grades_problem=self.grades.problem(),
                                  deadlines=deadlines,
                                  news=self.news.current(),
                                  deadlines_problem=self.hseapp.problem(),
                                  classes=classes, classes_label=classes_label,
                                  classes_problem=self.ical.problem())
            canvas = await asyncio.to_thread(screen.render, model, self.cfg.display.font_mode)
            payload = await asyncio.to_thread(_payload, canvas)
            self.synced_at = self.now()
            if self.base and protocol.payload_crc(payload) == self.base.crc:
                return self.base
            self.base = protocol.Frame(protocol.KIND_BASE, 0, self._next_id(), payload)
            return self.base

    def deadlines(self) -> tuple[Deadline, ...]:
        """All sources merged, without what is done in the university app or hidden in HA (§7.2)."""
        merged = builder.merge_deadlines(self.hseapp.current(), self.ical.deadlines(),
                                         # Each news deadline on its own: two posts may carry the same one.
                                         *((d,) for d in self.news.deadlines()), self.todo.own())
        return builder.drop_hidden(builder.drop_done(merged, self.hseapp.done()), self.todo.hidden())

    def todo_items(self) -> list[dict]:
        """The to-do lists in HA: what the Deadlines block would show, also past its 5 rows (§8.4)."""
        today = self.now().date()
        return [{"uid": uid(d), "title": d.title, "due": d.due.isoformat(), "category": d.category,
                 "source": d.source, "overdue": d.due < today}
                for d in screen.visible_deadlines(self.deadlines(), today)]

    def find_deadline(self, item_uid: str) -> Deadline | None:
        return next((d for d in self.deadlines() if uid(d) == item_uid), None)

    async def deadlines_changed(self) -> None:
        """A to-do list changed from HA: the screen follows at once."""
        self.todo.prune(self.now().date())
        await self.push_base()

    def _check_changed(self, deadlines: tuple[Deadline, ...]) -> None:
        """Tell HA when the to-do lists or the HSE login state changed (§8.4)."""
        signature = (tuple((uid(d), d.title, d.due, d.category) for d in deadlines), self.hseapp.problem())
        if signature != self._signature:
            kinds = []
            if self._signature is None or signature[0] != self._signature[0]:
                kinds.append("deadlines")
            if self._signature is None or signature[1] != self._signature[1]:
                kinds.append("status")
            self._signature = signature
            for kind in kinds:
                self.notify(kind)

    def notify(self, kind: str) -> None:
        """`tablo_changed` to the real HA (the fake one in tests); missed ones are caught by the integration's poll."""
        ha = self.real_ha or self.ha
        if ha is not None and ha.connected:
            self._spawn(self._fire(ha, CHANGED_EVENT, {"kind": kind}))

    async def _fire(self, ha, event: str, data: dict) -> None:
        try:
            await ha.fire_event(event, data)
        except Exception as e:  # noqa: BLE001 - the integration polls as well
            log.info("%s event failed: %s", event, e)

    def refetch(self, sources: list[str] | None = None) -> None:
        """`tablo.refresh_data`: poll the sources now instead of on their schedule."""
        for name in sources or REFETCH:
            match name:
                case "grades":
                    self.grades.refetch()
                case "hseapp":
                    self.hseapp.refetch()
                case "ical":
                    self.ical.refetch()
                case "news":
                    self.telegram.refetch()
                    self.mail.refetch()
                case "weather":
                    self.weather.refetch()
                case _:
                    raise ValueError(f"unknown source {name!r}; known: {', '.join(REFETCH)}")

    async def push_base(self, force: bool = False) -> None:
        """Render and send to devices whose last frame differs (or all, if force)."""
        old = self.base
        frame = await self.render_base()
        if force or frame is not old:
            await self._broadcast_frame(frame)

    def schedule_render(self, delay: float = RENDER_DEBOUNCE_S) -> None:
        """Debounced re-render: many changes within `delay` give one frame (§3.2)."""
        if self._render_task and not self._render_task.done():
            return

        async def run():
            await asyncio.sleep(delay)
            await self.push_base()

        self._render_task = self._spawn(run())

    async def send_overlay(self, canvas: Canvas, ttl_s: int) -> None:
        payload = await asyncio.to_thread(_payload, canvas)
        frame = protocol.Frame(protocol.KIND_OVERLAY, max(1, min(ttl_s, 0xFFFF)), self._next_id(), payload)
        await self._broadcast_frame(frame)

    async def show_qr(self, ssids: list[str] | None = None, duration_s: int | None = None) -> None:
        nets = self.cfg.wifi_networks
        if ssids:
            nets = [n for n in nets if n.ssid in ssids]
        canvas = await asyncio.to_thread(overlays.wifi_qr, nets, self.cfg.display.font_mode)
        await self.send_overlay(canvas, duration_s or self.cfg.qr_duration_s)

    async def show_message(self, title: str, text: str, icon: str | None = None,
                           duration_s: int | None = None) -> None:
        canvas = await asyncio.to_thread(overlays.message, title, text, icon, self.cfg.display.font_mode)
        await self.send_overlay(canvas, duration_s or self.cfg.message_duration_s)

    async def _broadcast_frame(self, frame: protocol.Frame) -> None:
        data = protocol.encode_frame(frame)
        for dev in list(self.devices.values()):
            await self._send(dev, data)

    # --- messages -------------------------------------------------------------

    def config_message(self) -> dict:
        d = self.cfg.display
        return {
            "type": "config",
            "tz": d.tz,
            "tz_name": d.tz_name,
            "ntp": d.ntp,
            "semester_start": d.semester_start.isoformat(),
            "zones": protocol.zones_message(),
            "long_press_ms": d.long_press_ms,
            "full_refresh": {"at": d.full_refresh_at, "max_partials": d.max_partials},
            "offline_after_s": d.offline_after_s,
            "diag_ttl_s": d.diag_ttl_s,
        }

    def health_message(self) -> dict:
        synced = self.synced_at.strftime("%H:%M") if self.synced_at else None
        ha = self.active_ha
        message = {"type": "health", "ha": bool(ha and ha.connected), "synced_at": synced}
        status = self.llm_status()
        message["llm"] = {  # the LLM block of the diagnostics screen (§4)
            "model": status["model"],
            "available": status["available"],
            "today": status["today"],
            "days30": status["days30"],
            "last": self._llm_short(status["last"]),
            "failure": self._llm_short(status["failure"]),
        }
        return message

    def _llm_short(self, run: dict | None) -> dict | None:
        """A run as the panel shows it: HH:MM today, "Oct 18 00:41" before; a short error."""
        if run is None:
            return None
        at = self._local(run["at"])
        when = f"{at:%H:%M}" if at.date() == self.now().date() else f"{at:%b} {at.day} {at:%H:%M}"
        return {"at": when, "task": run["task"], "ok": run["ok"],
                "tokens": _run_tokens(run), "cost_usd": run["cost_usd"], "duration_s": run["duration_s"],
                "error": (run["error"] or "")[:80] or None}

    # --- LLM runs (§6.6) ------------------------------------------------------

    def _local(self, utc_iso: str) -> dt.datetime:
        return dt.datetime.fromisoformat(utc_iso).astimezone(ZoneInfo(self.cfg.display.tz_name))

    def _on_llm_run(self, run: dict) -> None:
        """Every Haiku call goes to SQLite; the panel's diagnostics and HA learn of it at once."""
        self.store.add_llm_run(run)
        log.info("llm run: %s %s, %d+%d tokens, $%s, %.1f s", run["task"], "ok" if run["ok"] else run["error"],
                 run["input_tokens"], run["output_tokens"], run["cost_usd"], run["duration_s"])
        self._spawn(self.broadcast(self.health_message()))
        self.notify("llm")

    def llm_status(self) -> dict:
        midnight = self.now().replace(hour=0, minute=0, second=0, microsecond=0)
        since = midnight.replace(tzinfo=ZoneInfo(self.cfg.display.tz_name)).astimezone(dt.UTC)
        runs = self.store.llm_runs(limit=1)
        return {
            "available": self.llm.available,
            "model": getattr(self.llm, "model", None),
            "last": runs[0] if runs else None,
            "failure": self.store.llm_failing(),  # set while the calls keep failing
            "tasks": self.store.llm_last_by_task(),
            "today": self.store.llm_totals(since.isoformat(timespec="seconds")),
            "days30": self.store.llm_totals((since - dt.timedelta(days=29)).isoformat(timespec="seconds")),
        }

    async def broadcast(self, message: dict) -> None:
        for dev in list(self.devices.values()):
            await self._send(dev, message)

    async def _send(self, dev: Device, message: dict | bytes) -> None:
        try:
            if isinstance(message, bytes):
                await dev.ws.send_bytes(message)
            else:
                await dev.ws.send_str(json.dumps(message))
        except (ConnectionError, RuntimeError) as e:
            log.info("send to %s failed: %s", dev.id, e)

    # --- websocket ------------------------------------------------------------

    async def handle_ws(self, request: web.Request) -> web.StreamResponse:
        if request.query.get("token") != self.cfg.device_token:
            raise web.HTTPUnauthorized(text="bad device token")
        device_id = request.query.get("device") or "tablo"
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1 << 20)
        await ws.prepare(request)

        old = self.devices.get(device_id)
        if old:
            await old.ws.close(message=b"replaced by a new connection")
        dev = Device(id=device_id, ws=ws)
        self.devices[device_id] = dev
        log.info("device %s connected from %s", device_id, request.remote)
        self.notify("status")
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._on_text(dev, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    log.warning("device %s ws error: %s", device_id, ws.exception())
        finally:
            if self.devices.get(device_id) is dev:
                del self.devices[device_id]
                self.notify("status")
            log.info("device %s disconnected", device_id)
        return ws

    async def _on_text(self, dev: Device, data: str) -> None:
        dev.last_seen = self.last_seen = time.time()
        try:
            msg = json.loads(data)
            kind = msg["type"]
        except (ValueError, KeyError, TypeError):
            log.warning("device %s sent a bad message: %.200s", dev.id, data)
            return
        if kind == "hello":
            dev.fw = msg.get("fw")
            dev.status.update({k: msg[k] for k in ("rssi", "uptime_s") if k in msg})
            self._keep_rssi(dev)
            await self._send(dev, self.config_message())
            frame = self.base or await self.render_base()
            await self._send(dev, self.health_message())
            if msg.get("last_crc") != frame.crc:
                await self._send(dev, protocol.encode_frame(frame))
        elif kind == "status":
            dev.status.update({k: v for k, v in msg.items() if k != "type"})
            self._keep_rssi(dev)
        elif kind == "button":
            self._spawn(self._on_button(dev, msg))
        elif kind in ("overlay_closed", "frame_ack"):
            log.debug("device %s: %s", dev.id, msg)
        else:
            log.info("device %s: unknown message type %r", dev.id, kind)

    def _keep_rssi(self, dev: Device) -> None:
        """The Wi-Fi level stays known in HA after the panel goes offline (§8.4)."""
        if isinstance(dev.status.get("rssi"), int):
            self.last_rssi = dev.status["rssi"]

    async def _on_button(self, dev: Device, msg: dict) -> None:
        button_id, press, seq = msg.get("id"), msg.get("press"), msg.get("seq")
        if press not in ("short", "long") or not isinstance(button_id, int):
            return
        ha = self.active_ha
        if ha and ha.connected:
            try:
                await ha.fire_event("tablo_button", {"button": button_id, "press": press})
            except Exception as e:  # noqa: BLE001 - the button's own action still runs
                log.warning("tablo_button event failed: %s", e)
        ok, error = True, None
        try:
            if button_id == 8:
                # Firmware handles 8 itself; a short press also asks for a fresh frame.
                if press == "short":
                    await self.push_base(force=True)
            else:
                await self._run_action(button_id, press)
                await self.push_base()
        except Exception as e:  # noqa: BLE001 - any failure goes back to the device
            ok, error = False, str(e) or type(e).__name__
            log.warning("button %s %s failed: %s", button_id, press, error)
        result = {"type": "button_result", "seq": seq, "ok": ok}
        if error:
            result["error"] = error
        await self._send(dev, result)

    async def _run_action(self, button_id: int, press: str) -> None:
        button = self.cfg.button(button_id)
        if not button:
            return
        action = button.short if press == "short" else button.long
        ha = self.active_ha
        if action.action in ("toggle", "script") and not (ha and ha.connected):
            raise RuntimeError("Home Assistant is not connected")
        match action.action:
            case "toggle":
                await asyncio.wait_for(ha.toggle(action.entity), ACTION_TIMEOUT_S)
            case "script":
                await asyncio.wait_for(ha.run_script(action.entity), ACTION_TIMEOUT_S)
            case "qr":
                await self.show_qr(action.networks, action.duration_s)
            case "message":
                await self.show_message(action.title or "", action.text or "", None, action.duration_s)
            case "event" | "none":
                pass

    # --- background -----------------------------------------------------------

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def run_periodic(self) -> None:
        """Re-render every minute (forecast hour, relative dates) and send health."""
        last_health = 0.0
        while True:
            try:
                await self.push_base()
                if time.monotonic() - last_health >= HEALTH_INTERVAL_S:
                    await self.broadcast(self.health_message())
                    last_health = time.monotonic()
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("periodic render failed")
            await asyncio.sleep(60 - dt.datetime.now().second + 1)

    def status(self) -> dict:
        seen = dt.datetime.fromtimestamp(self.last_seen, dt.UTC).isoformat() if self.last_seen else None
        return {
            # What the entities in HA show (§8.4).
            "panel": {"connected": bool(self.devices), "last_seen": seen, "rssi": self.last_rssi},
            "devices": {
                d.id: {"connected_at": d.connected_at, "last_seen": d.last_seen, "fw": d.fw, **d.status}
                for d in self.devices.values()
            },
            "frame": {"id": self.base.frame_id, "crc": self.base.crc} if self.base else None,
            "ha": {
                "fake": self.cfg.demo["ha"],
                "connected": bool(self.active_ha and self.active_ha.connected),
                "real": {"url": self.real_ha.ws_url, "connected": self.real_ha.connected,
                         "ready": self.real_ha.ready, "error": self.real_ha.error} if self.real_ha else None,
            },
            "weather": vars(self.weather.status),
            "demo": dict(self.cfg.demo),
            "grades": {
                "llm": self.llm.available,
                "sheets": {sid: vars(s) for sid, s in self.grades.status.items()},
            },
            "hseapp": {**vars(self.hseapp.status), "problem": self.hseapp.problem(),
                       "login_needed": self.hseapp.problem() == "HSE login needed"},
            "ical": vars(self.ical.status),
            "news": vars(self.news.status),
            "mail": {"configured": self.mail.configured, **vars(self.mail.status)},
            "telegram": {
                "waiting": self.telegram.waiting(),
                "channels": {name: vars(st) for name, st in self.telegram.status.items()},
            },
            "synced_at": self.synced_at.isoformat() if self.synced_at else None,
            "llm": self.llm_status(),
        }


def _run_tokens(run: dict) -> int:
    return run["input_tokens"] + run["output_tokens"] + run["cache_write"] + run["cache_read"]


def _payload(canvas: Canvas) -> bytes:
    return pack(canvas.to_bw())
