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

from . import builder, protocol
from .config import Config, parse_demo
from .render import overlays, screen
from .render.canvas import Canvas, pack

log = logging.getLogger(__name__)

ACTION_TIMEOUT_S = 10
RENDER_DEBOUNCE_S = 2.0
HEALTH_INTERVAL_S = 60


@dataclass
class Device:
    id: str
    ws: web.WebSocketResponse
    connected_at: float = field(default_factory=time.time)
    status: dict = field(default_factory=dict)
    fw: str | None = None


class Hub:
    def __init__(self, cfg: Config, ha, data_dir: Path | None = None):
        self.cfg = cfg
        self.ha = ha
        self.data_dir = data_dir
        self.devices: dict[str, Device] = {}
        self.base: protocol.Frame | None = None
        self.synced_at: dt.datetime | None = None
        self._frame_id = 0
        self._render_lock = asyncio.Lock()
        self._render_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        ha.add_listener(lambda entity, old, new: self.schedule_render())
        self._load_demo()

    # --- demo data switches ---------------------------------------------------

    @property
    def active_ha(self):
        """The HA to use, or None: the fake HA can be switched off to see the real state."""
        return self.ha if self.cfg.demo["ha"] else None

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
            model = builder.build(self.now(), self.cfg, self.active_ha)
            canvas = await asyncio.to_thread(screen.render, model, self.cfg.display.font_mode)
            payload = await asyncio.to_thread(_payload, canvas)
            self.synced_at = self.now()
            if self.base and protocol.payload_crc(payload) == self.base.crc:
                return self.base
            self.base = protocol.Frame(protocol.KIND_BASE, 0, self._next_id(), payload)
            return self.base

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
        return {"type": "health", "ha": bool(ha and ha.connected), "synced_at": synced}

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
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._on_text(dev, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    log.warning("device %s ws error: %s", device_id, ws.exception())
        finally:
            if self.devices.get(device_id) is dev:
                del self.devices[device_id]
            log.info("device %s disconnected", device_id)
        return ws

    async def _on_text(self, dev: Device, data: str) -> None:
        try:
            msg = json.loads(data)
            kind = msg["type"]
        except (ValueError, KeyError, TypeError):
            log.warning("device %s sent a bad message: %.200s", dev.id, data)
            return
        if kind == "hello":
            dev.fw = msg.get("fw")
            dev.status.update({k: msg[k] for k in ("rssi", "uptime_s") if k in msg})
            await self._send(dev, self.config_message())
            frame = self.base or await self.render_base()
            await self._send(dev, self.health_message())
            if msg.get("last_crc") != frame.crc:
                await self._send(dev, protocol.encode_frame(frame))
        elif kind == "status":
            dev.status.update({k: v for k, v in msg.items() if k != "type"})
        elif kind == "button":
            self._spawn(self._on_button(dev, msg))
        elif kind in ("overlay_closed", "frame_ack"):
            log.debug("device %s: %s", dev.id, msg)
        else:
            log.info("device %s: unknown message type %r", dev.id, kind)

    async def _on_button(self, dev: Device, msg: dict) -> None:
        button_id, press, seq = msg.get("id"), msg.get("press"), msg.get("seq")
        if press not in ("short", "long") or not isinstance(button_id, int):
            return
        if self.active_ha:
            await self.active_ha.fire_event("tablo_button", {"button": button_id, "press": press})
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
        if action.action in ("toggle", "script") and ha is None:
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
        return {
            "devices": {
                d.id: {"connected_at": d.connected_at, "fw": d.fw, **d.status} for d in self.devices.values()
            },
            "frame": {"id": self.base.frame_id, "crc": self.base.crc} if self.base else None,
            "ha": {"mode": self.cfg.ha_mode, "connected": bool(self.active_ha and self.active_ha.connected)},
            "demo": dict(self.cfg.demo),
            "synced_at": self.synced_at.isoformat() if self.synced_at else None,
        }


def _payload(canvas: Canvas) -> bytes:
    return pack(canvas.to_bw())
