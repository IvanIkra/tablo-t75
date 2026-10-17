"""aiohttp application: device WebSocket, HTTP API, emulator (§6.4)."""

import asyncio
import contextlib
import io
import logging
from pathlib import Path

import yaml
from aiohttp import web

from . import config as config_mod
from .config import Config, ConfigError
from .ha import FakeHA
from .hub import Hub
from .render.canvas import unpack

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
EMULATOR_DIR = ROOT / "emulator"
FONTS_DIR = ROOT / "assets" / "fonts"
MDI_DIR = ROOT / "assets" / "mdi"

HUB = web.AppKey("hub", Hub)
SAVED_CONFIG = web.AppKey("saved_config", Path)


def _hub(request: web.Request) -> Hub:
    return request.app[HUB]


def _require_api_token(request: web.Request) -> None:
    expected = f"Bearer {_hub(request).cfg.api_token}"
    if request.headers.get("Authorization") != expected:
        raise web.HTTPUnauthorized(text="bad api token")


async def _json(request: web.Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="body must be JSON")
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="body must be a JSON object")
    return data


async def ws_handler(request: web.Request) -> web.StreamResponse:
    return await _hub(request).handle_ws(request)


async def status(request: web.Request) -> web.Response:
    return web.json_response(_hub(request).status())


async def frame_png(request: web.Request) -> web.Response:
    hub = _hub(request)
    frame = hub.base or await hub.render_base()
    buf = io.BytesIO()
    unpack(frame.payload).save(buf, "PNG")
    return web.Response(body=buf.getvalue(), content_type="image/png", headers={"Cache-Control": "no-store"})


async def overlay_qr(request: web.Request) -> web.Response:
    _require_api_token(request)
    data = await _json(request)
    await _hub(request).show_qr(data.get("networks"), data.get("duration_s"))
    return web.json_response({"ok": True})


async def overlay_message(request: web.Request) -> web.Response:
    _require_api_token(request)
    data = await _json(request)
    await _hub(request).show_message(
        str(data.get("title", "")), str(data.get("text", "")), data.get("icon"), data.get("duration_s")
    )
    return web.json_response({"ok": True})


async def refresh(request: web.Request) -> web.Response:
    _require_api_token(request)
    data = await _json(request) if request.can_read_body else {}
    hub = _hub(request)
    await hub.push_base(force=True)
    if data.get("full"):
        await hub.broadcast({"type": "full_refresh"})
    return web.json_response({"ok": True})


async def put_config(request: web.Request) -> web.Response:
    _require_api_token(request)
    data = await _json(request)
    hub = _hub(request)
    try:
        cfg = config_mod.from_dict(data)
    except (ConfigError, TypeError, ValueError) as e:
        raise web.HTTPBadRequest(text=f"bad config: {e}")
    # Secrets and the listening address are not set through the API.
    cfg.device_token, cfg.api_token = hub.cfg.device_token, hub.cfg.api_token
    cfg.host, cfg.port = hub.cfg.host, hub.cfg.port
    hub.cfg = cfg
    saved = request.app.get(SAVED_CONFIG)
    if saved:
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    await hub.broadcast(hub.config_message())
    await hub.push_base()
    return web.json_response({"ok": True})


async def emulator_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(EMULATOR_DIR / "index.html", headers={"Cache-Control": "no-store"})


async def root(request: web.Request) -> web.Response:
    raise web.HTTPFound("/emu")


def create_app(cfg: Config, ha=None, saved_config: Path | None = None, periodic: bool = True) -> web.Application:
    app = web.Application()
    hub = Hub(cfg, ha or FakeHA())
    app[HUB] = hub
    if saved_config:
        app[SAVED_CONFIG] = saved_config

    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/overlay/qr", overlay_qr)
    app.router.add_post("/api/overlay/message", overlay_message)
    app.router.add_post("/api/refresh", refresh)
    app.router.add_put("/api/config", put_config)
    app.router.add_get("/frame.png", frame_png)
    app.router.add_get("/", root)
    app.router.add_get("/emu", emulator_index)
    app.router.add_static("/emu/static", EMULATOR_DIR)
    app.router.add_static("/fonts", FONTS_DIR)
    app.router.add_static("/mdi", MDI_DIR)

    if periodic:
        async def background(app: web.Application):
            task = asyncio.create_task(hub.run_periodic())
            yield
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        app.cleanup_ctx.append(background)
    return app
