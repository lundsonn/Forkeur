"""
Odoo POS self-order adapter for dom_menu.

The pos-self SPA calls  POST /web/dataset/call_kw  to fetch products.
A plain httpx session returns SessionExpiredException even after priming
because Odoo 17+ requires a full browser-based session init.

Strategy: load the pos-self URL with Playwright and capture the
call_kw JSON-RPC response via a response listener.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from scrapers.base import new_page


def _parse_items(products: list[dict[str, Any]]) -> list[dict]:
    items = []
    for prod in products:
        title = (prod.get("name") or "").strip()
        if not title:
            continue
        try:
            price = round(float(prod["list_price"]), 2)
        except (KeyError, TypeError, ValueError):
            continue
        categ = prod.get("categ_id")
        cat_name = (
            str(categ[1]).strip() if isinstance(categ, (list, tuple)) and len(categ) == 2 else None
        )
        item: dict[str, Any] = {
            "title": title,
            "price": price,
            "catalog_name": cat_name,
        }
        desc = (prod.get("description_sale") or "").strip() or None
        if desc:
            item["description"] = desc
        items.append(item)
    return items


async def scrape(url: str, browser, log: Callable) -> list[dict]:
    page = await new_page(browser)
    captured: list[list] = []
    done = asyncio.Event()

    async def on_response(response):
        if done.is_set():
            return
        if "call_kw" in response.url and response.status == 200:
            try:
                body = await response.json()
                result = body.get("result")
                if isinstance(result, list) and result:
                    captured.append(result)
                    done.set()
            except Exception:
                pass

    page.on("response", on_response)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        try:
            await asyncio.wait_for(done.wait(), timeout=12)
        except asyncio.TimeoutError:
            log(f"    odoo_pos: no call_kw response captured from {url[:60]}")
            return []
        items = _parse_items(captured[0])
        log(f"    odoo_pos: {len(items)} items")
        return items
    except Exception as e:
        log(f"    odoo_pos: error loading {url[:60]}: {e}")
        return []
    finally:
        await page.close()
