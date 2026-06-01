from __future__ import annotations
import asyncio
import os
import re
from typing import Callable
import httpx
from models import ScraperConfig, ScraperResult
from scrapers.base import noop_log, parse_menu_price
import db

_APIFY_BASE = "https://api.apify.com/v2"
_LISTING_ACTOR = "scrapepilot~just-eat-scraper----restaurant-data-delivery-intelligence"
_MENU_ACTOR = "easyapi~just-eat-restaurant-menu-scraper"
_BRUSSELS_URL = "https://www.just-eat.be/restaurants?postCode=1000"


def _token() -> str:
    t = os.environ.get("APIFY_TOKEN", "")
    if not t:
        raise RuntimeError("APIFY_TOKEN not set in environment")
    return t


async def _run_actor(client: httpx.AsyncClient, actor: str, payload: dict, timeout_s: int = 300) -> list[dict]:
    """Run Apify actor synchronously, return dataset items."""
    token = _token()
    url = f"{_APIFY_BASE}/acts/{actor}/run-sync-get-dataset-items"
    resp = await client.post(
        url,
        params={"token": token, "timeout": timeout_s},
        json=payload,
        timeout=timeout_s + 30,
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"Apify error: {data['error']}")
    return data if isinstance(data, list) else []


def _parse_listing_items(items: list[dict]) -> list[dict]:
    """Normalise scrapepilot actor output to internal restaurant dicts."""
    restaurants = []
    for r in items:
        name = r.get("name") or r.get("restaurantName") or ""
        if not name:
            continue
        addr = r.get("address") or {}
        url = r.get("url") or r.get("menuUrl") or r.get("restaurantUrl") or ""
        unique_name = r.get("uniqueName") or r.get("slug") or ""
        rating_obj = r.get("rating") or {}
        rating = rating_obj.get("average") or rating_obj.get("starRating") or r.get("rating")
        if isinstance(rating, dict):
            rating = None
        eta = r.get("deliveryEtaMinutes") or r.get("etaMinutes") or ""
        eta_str = f"{eta}" if eta else None
        fee_raw = r.get("deliveryCost") or r.get("deliveryFee") or r.get("deliveryCostLabel")
        restaurants.append({
            "name": name,
            "unique_name": unique_name,
            "url": url,
            "lat": addr.get("latitude") or addr.get("lat"),
            "lng": addr.get("longitude") or addr.get("lng"),
            "rating": float(rating) if rating else None,
            "eta": eta_str,
            "delivery_fee_raw": str(fee_raw) if fee_raw else None,
        })
    return restaurants


def _parse_menu_items(items: list[dict]) -> list[dict]:
    """Normalise easyapi menu actor output to internal menu_items dicts."""
    result = []
    for item in items:
        name = item.get("name") or item.get("title") or ""
        if not name:
            continue
        # Price: may be in variations[0].basePrice (cents) or price field
        price = None
        variations = item.get("variations") or []
        if variations and isinstance(variations[0], dict):
            bp = variations[0].get("basePrice")
            if bp is not None:
                price = parse_menu_price(bp, is_cents=True)
        if price is None:
            raw = item.get("price") or item.get("basePrice")
            price = parse_menu_price(raw, is_cents=isinstance(raw, int))
        category = item.get("category") or item.get("sectionName") or "Menu"
        result.append({"title": name, "price": price, "catalog_name": category})
    return result


async def run(config: ScraperConfig, log_fn: Callable[[str], None] = noop_log) -> ScraperResult:
    log_fn("Starting Takeaway scraper (Apify just-eat.be)")

    records_saved = 0
    menu_items_saved = 0

    async with httpx.AsyncClient() as client:
        # Phase 1: restaurant listing
        log_fn(f"Fetching restaurants from just-eat.be (Brussels 1000)...")
        try:
            raw_items = await _run_actor(client, _LISTING_ACTOR, {
                "searchUrl": _BRUSSELS_URL,
                "maxItems": config.max_items or 100,
            }, timeout_s=180)
        except Exception as exc:
            log_fn(f"Listing actor failed: {exc}")
            return ScraperResult(records_saved=0, restaurants=[], menu_items_saved=0)

        restaurants = _parse_listing_items(raw_items)
        log_fn(f"Found {len(restaurants)} restaurants")

        if config.target:
            restaurants = [r for r in restaurants if config.target.lower() in r["name"].lower()]

        saved_listings: list[tuple[dict, str]] = []
        for r in restaurants:
            slug = r["unique_name"] or r["name"].lower().replace(" ", "-")
            rid = db.upsert_restaurant({
                "name": r["name"],
                "slug": slug,
                "lat": r.get("lat"),
                "lng": r.get("lng"),
            })
            lid = db.upsert_listing({
                "restaurant_id": rid,
                "platform": "takeaway",
                "url": r.get("url"),
                "rating": r.get("rating"),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
                "delivery_fee": parse_menu_price(r.get("delivery_fee_raw")),
                "discount_label": None,
            })
            records_saved += 1
            saved_listings.append((r, lid))

        log_fn(f"Phase 1 done — {records_saved} listings saved")

        # Phase 2: menu per restaurant
        n = len(saved_listings)
        for i, (r, lid) in enumerate(saved_listings):
            url = r.get("url")
            if not url:
                log_fn(f"Menu: {i+1}/{n} — {r['name']} — no URL, skipping")
                continue
            log_fn(f"Menu: {i+1}/{n} — {r['name']}")
            try:
                menu_raw = await _run_actor(client, _MENU_ACTOR, {
                    "restaurantUrl": url,
                    "maxItems": 500,
                }, timeout_s=120)
                items = _parse_menu_items(menu_raw)
                if items:
                    count = db.insert_menu_items(lid, items)
                    menu_items_saved += count
                    log_fn(f"  {count} items saved")
                else:
                    log_fn(f"  No items found")
            except Exception as exc:
                log_fn(f"  Error: {exc}")
            await asyncio.sleep(1)

    log_fn(f"Done — {records_saved} listings, {menu_items_saved} menu items saved")
    return ScraperResult(records_saved=records_saved, restaurants=restaurants, menu_items_saved=menu_items_saved)


def _parse_eta_min(eta: str | None) -> int | None:
    if not eta:
        return None
    m = re.match(r"(\d+)", eta.strip())
    return int(m.group(1)) if m else None


def _parse_eta_max(eta: str | None) -> int | None:
    if not eta:
        return None
    m = re.search(r"-(\d+)", eta.strip())
    return int(m.group(1)) if m else None
