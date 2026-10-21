"""HTTP client of the Tablo service (§6.4)."""

from __future__ import annotations

from typing import Any

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=15)


class TabloError(Exception):
    """The service is down or refused the request."""


class TabloAuthError(TabloError):
    """Wrong api token."""


class TabloApi:
    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self._session = session
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        try:
            async with self._session.request(method, self.url + path, json=body, headers=self._headers,
                                             timeout=TIMEOUT) as resp:
                if resp.status == 401:
                    raise TabloAuthError("bad api token")
                if resp.status >= 400:
                    raise TabloError((await resp.text()).strip() or f"HTTP {resp.status}")
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as e:
            raise TabloError(f"service unavailable: {type(e).__name__}: {e}") from e

    async def get_config(self) -> dict:
        return await self._request("GET", "/api/config")

    async def put_config(self, config: dict) -> None:
        await self._request("PUT", "/api/config", config)

    async def status(self) -> dict:
        return await self._request("GET", "/api/status")

    async def show_qr(self, networks: list[str] | None, duration_s: int | None) -> None:
        await self._request("POST", "/api/overlay/qr", {"networks": networks, "duration_s": duration_s})

    async def show_message(self, title: str, text: str, icon: str | None, duration_s: int | None) -> None:
        await self._request("POST", "/api/overlay/message",
                            {"title": title, "text": text, "icon": icon, "duration_s": duration_s})

    async def refresh(self, full: bool = False, sources: list[str] | None = None, refetch: bool = False) -> None:
        body: dict[str, Any] = {"full": full, "refetch": refetch}
        if sources:
            body["sources"] = sources
        await self._request("POST", "/api/refresh", body)
