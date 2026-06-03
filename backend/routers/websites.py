"""Router for the website-finder scraper."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

router = APIRouter(prefix="/find-websites", tags=["websites"])

_running: bool = False


@router.post("")
async def trigger_find_websites(limit: int | None = None):
    """Trigger the website-finder scraper in the background.

    Query params:
        limit (int, optional): Process only N restaurants (useful for testing).
    """
    global _running
    if _running:
        return {"status": "already_running"}

    from scrapers.website_finder import run

    async def _bg():
        global _running
        _running = True
        try:
            await run(log=print, limit=limit)
        finally:
            _running = False

    asyncio.create_task(_bg())
    return {"status": "started", "limit": limit}


@router.get("/status")
async def find_websites_status():
    """Return whether the website-finder is currently running."""
    return {"running": _running}
