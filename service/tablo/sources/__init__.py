"""Data sources: each fetches on its own schedule and keeps its last good data (§6.2)."""

import asyncio


async def nap(wake: asyncio.Event, seconds: float) -> None:
    """Sleep until the next poll, or less if `tablo.refresh_data` asks for one now (§8.4).

    Cleared after waking, not before: a request that comes during a poll gives one more poll.
    """
    try:
        await asyncio.wait_for(wake.wait(), seconds)
    except asyncio.TimeoutError:
        pass
    wake.clear()
