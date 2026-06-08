"""
DOM menu scraper — hybrid dispatcher.
Covers platform_listings where platform='direct' and url_type IN ('website','menu').

Strategy per URL:
  1. Check sites/ registry for a domain-specific adapter (reliable, hand-tuned)
  2. Fall back to generic.py (JSON-LD → price-proximity heuristic)

To add a site-specific adapter:
  1. Create scrapers/dom_menu/sites/mysite.py with async scrape(url, browser, log)
  2. Register it in scrapers/dom_menu/sites/__init__.py _REGISTRY
"""
from __future__ import annotations

import asyncio
from typing import Callable
from urllib.parse import urlparse

from models import ScraperConfig, ScraperResult
from scrapers.base import browser_session, new_context, noop_log
from scrapers.dom_menu import generic
from scrapers.dom_menu.sites import get_adapter
import db


async def run(config: ScraperConfig | None = None, log: Callable = noop_log) -> ScraperResult:
    """Scrape menus from direct listings with url_type in ('website', 'menu')."""
    client = db.get_client()
    listings = (
        client.table("platform_listings")
        .select("id, url, url_type")
        .eq("platform", "direct")
        .in_("url_type", ["website", "menu"])
        .not_.is_("url", "null")
        .execute()
    ).data

    log(f"dom_menu: {len(listings)} website/menu listings")

    max_items = config.max_items if config else None
    if max_items:
        listings = listings[:max_items]

    # 5 concurrent pages on shared browser. 5 (not 8) because dom_menu overlaps
    # the parallel ube/del menu workers during the batch — 8 pages here pushed
    # batch peak to 6.7GB / 1.1GB free. 5 frees ~1.5GB at the overlap; dom_menu
    # only slows ~3.5→5.5min (it's never the batch long pole). ~5× vs sequential.
    sem = asyncio.Semaphore(5)

    async with browser_session(headed=False) as browser:
        ctx = await new_context(browser)
        try:
            async def _scrape_one(listing: dict) -> int:
                async with sem:
                    url = listing["url"]
                    host = urlparse(url).netloc.lower()
                    log(f"  → {url[:70]}")
                    adapter = get_adapter(host)
                    try:
                        if adapter:
                            log(f"    [site-specific]")
                            items = await adapter(url, ctx, log)
                        else:
                            items = await generic.scrape_url(url, ctx, log)
                    except Exception as e:
                        log(f"     error: {e}")
                        return 0
                    if not items:
                        return 0
                    saved = db.insert_menu_items(listing["id"], items)
                    log(f"     {saved} items saved")
                    return saved

            results = await asyncio.gather(*[_scrape_one(l) for l in listings], return_exceptions=True)
            total_saved = sum(r for r in results if isinstance(r, int))
        finally:
            await ctx.close()

    log(f"\ndone — {total_saved} total items")
    return ScraperResult(records_saved=total_saved)
