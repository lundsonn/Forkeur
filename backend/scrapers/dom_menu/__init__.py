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
from scrapers.base import new_browser, noop_log
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

    total_saved = 0
    browser = await new_browser(headed=False)
    try:
        for listing in listings:
            url = listing["url"]
            host = urlparse(url).netloc.lower()
            log(f"  → {url[:70]}")

            adapter = get_adapter(host)
            if adapter:
                log(f"    [site-specific adapter]")
                items = await adapter(url, browser, log)
            else:
                items = await generic.scrape_url(url, browser, log)

            if not items:
                continue

            saved = db.insert_menu_items(listing["id"], items)
            total_saved += saved
            log(f"     {saved} items saved")
            await asyncio.sleep(1.0)
    finally:
        await browser.close()

    log(f"\ndone — {total_saved} total items")
    return ScraperResult(records_saved=total_saved)
