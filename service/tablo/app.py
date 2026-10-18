"""aiohttp application: device WebSocket, HTTP API, emulator (§6.4)."""

import asyncio
import contextlib
import io
import logging
from pathlib import Path
from urllib.parse import urlencode

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
PAGES_DIR = ROOT / "pages"

HUB = web.AppKey("hub", Hub)


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
    cfg.demo = hub.cfg.demo  # demo switches are a runtime choice, not part of the pushed config
    hub.cfg = cfg
    if hub.data_dir:
        hub.data_dir.mkdir(parents=True, exist_ok=True)
        (hub.data_dir / "config.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    await hub.broadcast(hub.config_message())
    await hub.push_base()
    return web.json_response({"ok": True})


async def get_demo(request: web.Request) -> web.Response:
    return web.json_response(_hub(request).cfg.demo)


async def put_demo(request: web.Request) -> web.Response:
    _require_api_token(request)
    data = await _json(request)
    try:
        demo = await _hub(request).set_demo(data)
    except ConfigError as e:
        raise web.HTTPBadRequest(text=str(e))
    return web.json_response(demo)


async def hseapp_page(request: web.Request) -> web.FileResponse:
    return web.FileResponse(PAGES_DIR / "hseapp.html", headers={"Cache-Control": "no-store"})


async def hseapp_login_url(request: web.Request) -> web.Response:
    _require_api_token(request)
    hub = _hub(request)
    # HSE's client accepts any return address: the browser comes straight back here.
    callback = f"{request.scheme}://{request.host}/hseapp/callback"
    return web.json_response({"url": hub.hseapp.auth.login_url(callback), "logged_in": hub.hseapp.auth.logged_in})


async def hseapp_login(request: web.Request) -> web.Response:
    """The return address pasted by hand, when the browser could not reach the service."""
    _require_api_token(request)
    data = await _json(request)
    try:
        await _hub(request).hseapp.login(str(data.get("url", "")))
    except ValueError as e:
        raise web.HTTPBadRequest(text=str(e))
    return web.json_response({"ok": True})


async def hseapp_callback(request: web.Request) -> web.Response:
    """No api token here: only a browser that started the login knows its state (PKCE)."""
    try:
        await _hub(request).hseapp.login(str(request.url))
    except ValueError as e:
        raise web.HTTPFound("/hseapp?" + urlencode({"error": str(e)}))
    raise web.HTTPFound("/hseapp?login=ok")


async def emulator_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(EMULATOR_DIR / "index.html", headers={"Cache-Control": "no-store"})


async def root(request: web.Request) -> web.Response:
    raise web.HTTPFound("/emu")


def create_app(cfg: Config, ha=None, data_dir: Path | None = None, periodic: bool = True) -> web.Application:
    """data_dir keeps the config last pushed by HA and the demo switches."""
    app = web.Application()
    hub = Hub(cfg, ha or FakeHA(), data_dir)
    app[HUB] = hub

    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/overlay/qr", overlay_qr)
    app.router.add_post("/api/overlay/message", overlay_message)
    app.router.add_post("/api/refresh", refresh)
    app.router.add_put("/api/config", put_config)
    app.router.add_get("/api/demo", get_demo)
    app.router.add_put("/api/demo", put_demo)
    app.router.add_get("/frame.png", frame_png)
    app.router.add_get("/hseapp", hseapp_page)
    app.router.add_get("/api/hseapp/login", hseapp_login_url)
    app.router.add_post("/api/hseapp/login", hseapp_login)
    app.router.add_get("/hseapp/callback", hseapp_callback)
    app.router.add_get("/", root)
    app.router.add_get("/emu", emulator_index)
    app.router.add_static("/emu/static", EMULATOR_DIR)
    app.router.add_static("/fonts", FONTS_DIR)
    app.router.add_static("/mdi", MDI_DIR)

    async def close_devices(app: web.Application) -> None:
        # Otherwise shutdown waits for open device sockets to time out.
        for dev in list(hub.devices.values()):
            await dev.ws.close(code=1001, message=b"service shutting down")

    app.on_shutdown.append(close_devices)

    if periodic:
        async def background(app: web.Application):
            runs = (hub.run_periodic(), hub.grades.run(), hub.university.examplen(), hub.ical.run(),
                    hub.telegram.run(), hub.mail.run(), hub.news.run())
            tasks = [asyncio.create_task(c) for c in runs]
            yield
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        app.cleanup_ctx.append(background)
    return app
