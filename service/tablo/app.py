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
from .ha import FakeHA, HomeAssistant
from .hub import Hub
from .render.canvas import unpack

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
EMULATOR_DIR = ROOT / "emulator"
FONTS_DIR = ROOT / "assets" / "fonts"
MDI_DIR = ROOT / "assets" / "mdi"

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
    if data.get("refetch") or data.get("sources"):
        sources = data.get("sources")
        if sources is not None and not (isinstance(sources, list) and all(isinstance(s, str) for s in sources)):
            raise web.HTTPBadRequest(text="sources must be a list of names")
        try:
            hub.refetch(sources)
        except ValueError as e:
            raise web.HTTPBadRequest(text=str(e))
    await hub.push_base(force=True)
    if data.get("full"):
        await hub.broadcast({"type": "full_refresh"})
    return web.json_response({"ok": True})


async def get_config(request: web.Request) -> web.Response:
    """For the HA integration to start from the config the service has now (§8.1)."""
    _require_api_token(request)
    return web.json_response(config_mod.to_dict(_hub(request).cfg))


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
    cfg.infomaster_token = hub.cfg.infomaster_token
    cfg.host, cfg.port = hub.cfg.host, hub.cfg.port
    cfg.demo = hub.cfg.demo  # demo switches are a runtime choice, not part of the pushed config
    cfg.ha = hub.cfg.ha  # the service's own connection to HA is set up once, at start
    hub.set_config(cfg)
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


async def emulator_index(request: web.Request) -> web.Response:
    """The page links emu.js and emu.css with their mtime, so a browser never runs a stale copy after a deploy."""
    html = (EMULATOR_DIR / "index.html").read_text(encoding="utf-8")
    for name in ("emu.js", "emu.css"):
        version = int((EMULATOR_DIR / name).stat().st_mtime)
        html = html.replace(f"/emu/static/{name}\"", f"/emu/static/{name}?v={version}\"")
    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})


async def root(request: web.Request) -> web.Response:
    raise web.HTTPFound("/emu")


STATIC_PREFIXES = ("/emu/static/", "/fonts/", "/mdi/")


async def revalidate_static(request: web.Request, response: web.StreamResponse) -> None:
    """Emulator code and fonts: the browser asks again each time (304 if unchanged), so a reload picks up a deploy."""
    if request.path.startswith(STATIC_PREFIXES):
        response.headers["Cache-Control"] = "no-cache"


def create_app(cfg: Config, ha=None, data_dir: Path | None = None, periodic: bool = True) -> web.Application:
    """data_dir keeps the config last pushed by HA and the demo switches.

    ha replaces the fake house (tests); the real HA is used only when none is given and a token is set.
    """
    app = web.Application()
    real_ha = HomeAssistant(cfg.ha.url, cfg.ha.token) if ha is None and cfg.ha.token else None
    hub = Hub(cfg, ha or FakeHA(), data_dir, real_ha=real_ha)
    app[HUB] = hub

    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/overlay/qr", overlay_qr)
    app.router.add_post("/api/overlay/message", overlay_message)
    app.router.add_post("/api/refresh", refresh)
    app.router.add_get("/api/config", get_config)
    app.router.add_put("/api/config", put_config)
    app.router.add_get("/api/demo", get_demo)
    app.router.add_put("/api/demo", put_demo)
    app.router.add_get("/frame.png", frame_png)
    app.router.add_get("/", root)
    app.router.add_get("/emu", emulator_index)
    app.router.add_static("/emu/static", EMULATOR_DIR)
    app.router.add_static("/fonts", FONTS_DIR)
    app.router.add_static("/mdi", MDI_DIR)
    app.on_response_prepare.append(revalidate_static)

    async def close_devices(app: web.Application) -> None:
        # Otherwise shutdown waits for open device sockets to time out.
        for dev in list(hub.devices.values()):
            await dev.ws.close(code=1001, message=b"service shutting down")

    app.on_shutdown.append(close_devices)

    if periodic:
        async def background(app: web.Application):
            runs = [hub.run_periodic(), hub.infomaster.run(), hub.ical.run(), hub.weather.run()]
            if hub.real_ha:
                runs.append(hub.real_ha.run())
            tasks = [asyncio.create_task(c) for c in runs]
            yield
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        app.cleanup_ctx.append(background)
    return app
