"""
sq_menu / foodbooking site adapter for dom_menu.

Both platforms share the same SPA. When loaded the SPA calls
  GET /api/menu/{code}
with a session token set by the frontend's init sequence — meaning plain
httpx requests are now rejected (403 invalid_token).

Strategy: load the URL with Playwright and capture the /api/menu/ (or
/api/catalog/) response via a response listener. The browser has the
session token so the API call succeeds automatically.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from scrapers.base import new_page


def _parse_items(data: dict[str, Any]) -> list[dict]:
    items = []
    for cat in data.get("categories") or []:
        cat_name = (cat.get("name") or "").strip() or None
        for prod in cat.get("products") or []:
            title = (prod.get("name") or "").strip()
            if not title:
                continue
            try:
                price = round(float(prod["price"]), 2)
            except (KeyError, TypeError, ValueError):
                continue
            item: dict[str, Any] = {
                "title": title,
                "price": price,
                "catalog_name": cat_name,
            }
            desc = (prod.get("description") or "").strip() or None
            if desc:
                item["description"] = desc
            img = (prod.get("imageUrl") or "").strip() or None
            if img:
                item["image_url"] = img
            items.append(item)
    return items


async def scrape(url: str, browser, log: Callable) -> list[dict]:
    page = await new_page(browser)
    captured: list[dict] = []
    done = asyncio.Event()

    async def on_response(response):
        if done.is_set():
            return
        ru = response.url
        if ("/api/menu/" in ru or "/api/catalog/" in ru) and response.status == 200:
            try:
                data = await response.json()
                if data.get("categories"):
                    captured.append(data)
                    done.set()
            except Exception:
                pass

    page.on("response", on_response)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        try:
            await asyncio.wait_for(done.wait(), timeout=12)
        except asyncio.TimeoutError:
            log(f"    sq_menu: no menu API response captured from {url[:60]}")
            return []
        items = _parse_items(captured[0])
        log(f"    sq_menu: {len(items)} items")
        return items
    except Exception as e:
        log(f"    sq_menu: error loading {url[:60]}: {e}")
        return []
    finally:
        await page.close()
