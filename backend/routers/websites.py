"""Router for the website-finder scraper."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from routers.auth_router import require_auth

router = APIRouter(prefix="/find-websites", tags=["websites"], dependencies=[Depends(require_auth)])

_running: bool = False
_state_lock = asyncio.Lock()
# Hold a strong ref to the background task so it isn't garbage-collected
# mid-run (a bare create_task() result can be reaped if nothing references it).
_bg_tasks: set[asyncio.Task] = set()


def _track_bg(task: asyncio.Task) -> None:
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


@router.post("")
async def trigger_find_websites(limit: int | None = None):
    """Trigger the website-finder scraper in the background.

    Query params:
        limit (int, optional): Process only N restaurants (useful for testing).
    """
    global _running
    # Atomic check-and-set: without the lock two near-simultaneous requests can
    # both read _running == False and both launch the scraper.
    async with _state_lock:
        if _running:
            return {"status": "already_running"}
        _running = True

    from scrapers.website_finder import run

    async def _bg():
        global _running
        try:
            await run(log=print, limit=limit)
        finally:
            async with _state_lock:
                _running = False

    _track_bg(asyncio.create_task(_bg()))
    return {"status": "started", "limit": limit}


@router.get("/status")
async def find_websites_status():
    """Return whether the website-finder is currently running."""
    return {"running": _running}
