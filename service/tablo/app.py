"""aiohttp application: device WebSocket, HTTP API, emulator (§6.4)."""

import asyncio
import contextlib
import datetime as dt
import io
import logging
from pathlib import Path
from urllib.parse import urlencode

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


# --- to-do lists in HA (§8.4) -------------------------------------------------

def _date(value) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        raise web.HTTPBadRequest(text="due must be a date like 2026-10-20")


async def list_deadlines(request: web.Request) -> web.Response:
    _require_api_token(request)
    return web.json_response({"items": _hub(request).todo_items()})


async def add_deadline(request: web.Request) -> web.Response:
    _require_api_token(request)
    data = await _json(request)
    hub = _hub(request)
    try:
        d = hub.todo.add(str(data.get("title", "")), _date(data.get("due")), str(data.get("category", "")))
    except ValueError as e:
        raise web.HTTPBadRequest(text=str(e))
    await hub.deadlines_changed()
    return web.json_response({"uid": d.key})


def _deadline(request: web.Request):
    d = _hub(request).find_deadline(request.match_info["uid"])
    if d is None:
        raise web.HTTPNotFound(text="no such deadline on the screen")
    return d


async def edit_deadline(request: web.Request) -> web.Response:
    """{done: true} hides it; {title, due} changes it (a deadline from a source becomes an own copy)."""
    _require_api_token(request)
    data = await _json(request)
    hub = _hub(request)
    d = _deadline(request)
    if data.get("done"):
        hub.todo.remove(d)
        await hub.deadlines_changed()
        return web.json_response({"uid": None})
    title = data.get("title")
    due = _date(data["due"]) if data.get("due") else None
    try:
        new = hub.todo.edit(d, None if title is None else str(title), due)
    except ValueError as e:
        raise web.HTTPBadRequest(text=str(e))
    await hub.deadlines_changed()
    return web.json_response({"uid": new.key})


async def delete_deadline(request: web.Request) -> web.Response:
    _require_api_token(request)
    hub = _hub(request)
    hub.todo.remove(_deadline(request))
    await hub.deadlines_changed()
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
    app.router.add_get("/api/deadlines", list_deadlines)
    app.router.add_post("/api/deadlines", add_deadline)
    app.router.add_patch("/api/deadlines/{uid}", edit_deadline)
    app.router.add_delete("/api/deadlines/{uid}", delete_deadline)
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
    app.on_response_prepare.append(revalidate_static)

    async def close_devices(app: web.Application) -> None:
        # Otherwise shutdown waits for open device sockets to time out.
        for dev in list(hub.devices.values()):
            await dev.ws.close(code=1001, message=b"service shutting down")

    app.on_shutdown.append(close_devices)

    if periodic:
        async def background(app: web.Application):
            runs = [hub.run_periodic(), hub.grades.run(), hub.university.examplen(), hub.ical.run(),
                    hub.telegram.run(), hub.mail.run(), hub.news.run(), hub.weather.run()]
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
