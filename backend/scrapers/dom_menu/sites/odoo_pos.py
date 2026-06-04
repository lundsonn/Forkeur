"""
Odoo POS self-order adapter for dom_menu.

Newer Odoo versions (17+) load product data via:
  GET /pos-self/data/{config_id}

The response is a JSON-RPC envelope:
  { result: {
      "product.template": [...],   // products with list_price, pos_categ_ids
      "pos.category": [...],       // POS menu categories
      ...
  }}

Strategy: load pos-self/{id} with Playwright and capture the /pos-self/data/
response via a response listener.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Callable

from scrapers.base import new_page


def _strip_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _parse_items(result: dict[str, Any]) -> list[dict]:
    categories: dict[int, str] = {
        c["id"]: (c.get("name") or "").strip()
        for c in (result.get("pos.category") or [])
        if c.get("id")
    }

    items = []
    for tmpl in result.get("product.template") or []:
        if not tmpl.get("available_in_pos"):
            continue
        title = (tmpl.get("display_name") or tmpl.get("name") or "").strip()
        if not title:
            continue
        try:
            price = round(float(tmpl["list_price"]), 2)
        except (KeyError, TypeError, ValueError):
            continue

        categ_ids: list[int] = tmpl.get("pos_categ_ids") or []
        cat_name = categories.get(categ_ids[0]) if categ_ids else None

        item: dict[str, Any] = {
            "title": title,
            "price": price,
            "catalog_name": cat_name,
        }
        desc = _strip_html(tmpl.get("description_sale") or tmpl.get("public_description") or "") or None
        if desc:
            item["description"] = desc
        items.append(item)
    return items


async def scrape(url: str, browser, log: Callable) -> list[dict]:
    page = await new_page(browser)
    captured: list[dict] = []
    done = asyncio.Event()

    async def on_response(response):
        if done.is_set():
            return
        if "/pos-self/data/" in response.url and response.status == 200:
            try:
                body = await response.json()
                result = body.get("result") or {}
                if result.get("product.template"):
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
            log(f"    odoo_pos: no /pos-self/data/ response from {url[:60]}")
            return []
        items = _parse_items(captured[0])
        log(f"    odoo_pos: {len(items)} items")
        return items
    except Exception as e:
        log(f"    odoo_pos: error loading {url[:60]}: {e}")
        return []
    finally:
        await page.close()
