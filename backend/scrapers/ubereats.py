from __future__ import annotations
import asyncio
import json
from typing import Callable
from models import ScraperConfig, ScraperResult
from scrapers.base import browser_session, new_page, check_cloudflare, noop_log
from scrapers.promos import classify_promo, extract_min_order, parse_promo_texts
import db


async def run(config: ScraperConfig, log_fn: Callable[[str], None] = noop_log) -> ScraperResult:
    log_fn("Starting UberEats scraper")
    records_saved = 0

    async with browser_session(lang="fr-BE") as browser:
        page = await new_page(browser, lang="fr-BE")

        feed_pages: list[str] = []

        async def on_response(response):
            if "getFeedV1" in response.url:
                try:
                    text = await response.text()
                    feed_pages.append(text)
                except Exception:
                    pass

        page.on("response", on_response)

        log_fn("Loading ubereats.com...")
        # /be-fr is a dead URL — navigate to root which redirects to /be-en with address input
        await page.goto("https://www.ubereats.com/", wait_until="domcontentloaded", timeout=60000)
        check_cloudflare(await page.title())
        log_fn(f"Page loaded: {page.url}")

        # Address input is already visible on the homepage — no "Find food" click needed
        input_sel = "#location-typeahead-home-input"
        await page.wait_for_selector(input_sel, timeout=20000)
        log_fn(f"Input found: {input_sel}")
        await page.click(input_sel)
        await page.type(input_sel, config.address, delay=60)
        log_fn(f"Typed address: {config.address}")
        await asyncio.sleep(3)

        # Wait for suggestions dropdown to appear
        try:
            await page.wait_for_selector('[role="option"], li[role="option"], .uber-cache, [data-testid*="suggestion"]', timeout=5000)
            log_fn("Suggestions dropdown appeared")
        except Exception:
            log_fn("No suggestions dropdown, trying direct Enter")

        await page.keyboard.press("ArrowDown")
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        log_fn(f"Pressed ArrowDown+Enter, page URL: {page.url}")

        # Wait for URL to change or navigation to complete
        try:
            await page.wait_for_url("**/restaurants**", timeout=10000)
        except Exception:
            log_fn("URL didn't change to /restaurants, may still work")

        await asyncio.sleep(2)

        log_fn("Waiting for first feed API response...")
        deadline = asyncio.get_event_loop().time() + 15
        while not feed_pages and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)

        if not feed_pages:
            raise TimeoutError("Feed API not captured")

        # Scroll to load all pages — UberEats uses infinite scroll with getFeedV1 per batch
        log_fn("Scrolling to load all restaurants...")
        prev_count = 0
        stale_ticks = 0
        max_stale = 4  # stop after 4 scroll cycles with no new responses
        while stale_ticks < max_stale:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2.5)
            cur_count = len(feed_pages)
            if cur_count == prev_count:
                stale_ticks += 1
            else:
                log_fn(f"Scroll: {cur_count} feed responses so far")
                stale_ticks = 0
            prev_count = cur_count

        page.remove_listener("response", on_response)

        # Aggregate all stores across all pages, dedup by storeUuid
        seen_uuids: set[str] = set()
        stores = []
        for raw in feed_pages:
            try:
                feed = json.loads(raw)
            except Exception:
                continue
            feed_items = feed.get("data", {}).get("feedItems", [])
            for item in feed_items:
                if item.get("type") != "REGULAR_STORE":
                    continue
                uuid = (item.get("store") or {}).get("storeUuid") or item.get("uuid") or ""
                if uuid and uuid in seen_uuids:
                    continue
                seen_uuids.add(uuid)
                stores.append(item)

        log_fn(f"Feed: {len(stores)} unique restaurants across {len(feed_pages)} pages")

        restaurants = []
        for item in stores:
            s = item.get("store", {})
            meta = s.get("meta", []) or []
            eta_meta = next((m for m in meta if m.get("badgeType") == "ETD"), None)
            tracking = s.get("tracking") or {}
            payload = tracking.get("storePayload") or {}
            fare_info = payload.get("fareInfo") or {}
            marker = s.get("mapMarker") or {}
            signposts = s.get("signposts") or []
            # Keep first label for backward-compat discount_label; full promos parsed separately
            discount = signposts[0].get("text") if signposts else None
            restaurants.append({
                "name": (s.get("title") or {}).get("text", "Unknown"),
                "url": f"https://www.ubereats.com{s['actionUrl'].split('?')[0]}" if s.get("actionUrl") else None,
                "store_uuid": s.get("storeUuid") or item.get("uuid"),
                "rating": (s.get("rating") or {}).get("text", "N/A"),
                "delivery_fee": fare_info.get("serviceFee"),
                "eta": (eta_meta or {}).get("text", "N/A"),
                "lat": marker.get("latitude"),
                "lng": marker.get("longitude"),
                "discount": discount,
                "image_url": _extract_store_image(s),
                "_store": s,
            })

        if config.target:
            restaurants = [r for r in restaurants if config.target.lower() in r["name"].lower()]

        log_fn(f"Saving {len(restaurants)} restaurants...")
        saved_listings: list[tuple[dict, str]] = []  # (restaurant_dict, listing_id)
        promo_total = 0
        for r in (restaurants[:config.max_items] if config.max_items else restaurants):
            try:
                slug = (r.get("url") or "").split("/store/")[-1].strip("/") or r["name"].lower().replace(" ", "-")
                rid = db.upsert_restaurant({
                    "name": r["name"],
                    "slug": slug,
                    "lat": r.get("lat"),
                    "lng": r.get("lng"),
                    "image_url": r.get("image_url"),
                })
            except ValueError:
                continue  # junk entry filtered by db._is_junk
            hours = _parse_regular_hours(r.get("_store") or {})
            lid = db.upsert_listing({
                "restaurant_id": rid,
                "platform": "uber_eats",
                "url": r.get("url"),
                "rating": _parse_float(r.get("rating")),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
                "delivery_fee": r.get("delivery_fee"),
                "discount_label": r.get("discount"),
                **({"opening_hours": hours} if hours else {}),
            })
            promos = _parse_promotions(r.get("_store") or {})
            promo_total += db.upsert_promotions(lid, promos)
            saved_listings.append((r, lid))
            records_saved += 1

        log_fn(f"Phase 1 done — {records_saved} listings, {promo_total} promotions saved")

        if config.listing_only:
            return ScraperResult(records_saved=records_saved)

        # ── Phase 2: menu scraping via click-nav ─────────────────────────────
        # Direct goto(restaurant_url) triggers Uber bot-defense/reCAPTCHA.
        # Clicking from within the trusted listing session avoids detection.
        listing_url = page.url
        menu_items_saved = 0
        n = len(saved_listings)
        for i, (r, lid) in enumerate(saved_listings):
            url = r.get("url")
            name = r.get("name", "?")
            if not url:
                log_fn(f"Menu: {i+1}/{n} — {name} — no URL, skipping")
                continue

            log_fn(f"Menu: {i+1}/{n} — {name}")

            # Extract the path-unique slug from URL for selector matching
            # e.g. "https://www.ubereats.com/be/store/mcdonald-s/UUID" → "mcdonald-s/UUID"
            store_path = url.split("/store/")[-1].strip("/") if "/store/" in url else ""
            if not store_path:
                log_fn(f"Menu: {i+1}/{n} — {name} — bad URL, skipping")
                continue

            store_raw: list[str] = []

            async def on_store_response(response, _buf=store_raw):
                if "getStoreV1" in response.url and not _buf:
                    try:
                        text = await response.text()
                        _buf.append(text)
                    except Exception:
                        pass

            page.on("response", on_store_response)
            try:
                # Ensure we're on the listing page (go_back preserves scroll state)
                if listing_url not in page.url:
                    await page.go_back(wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(2)

                # Scroll until page height stabilises — ensures all infinite-scroll
                # cards are in the DOM before we try to click one.
                prev_h = 0
                for _ in range(40):
                    h = await page.evaluate("document.body.scrollHeight")
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(1.2)
                    if h == prev_h:
                        break
                    prev_h = h
                await page.evaluate("window.scrollTo(0, 0)")
                await asyncio.sleep(0.5)

                # Click restaurant anchor; scroll-retry if not yet in DOM.
                # Also try locale-agnostic href match (strip leading /be/ prefix).
                slug_only = store_path.split("/")[0] if "/" in store_path else store_path
                clicked = False
                for _attempt in range(5):
                    clicked = await page.evaluate(f"""
                        (() => {{
                            // Exact match first
                            let a = document.querySelector('a[href*="/store/{store_path}"]');
                            if (!a) {{
                                // Fallback: match by slug only (ignores locale prefix differences)
                                a = document.querySelector('a[href*="/store/{slug_only}"]');
                            }}
                            if (a) {{ a.click(); return true; }}
                            return false;
                        }})()
                    """)
                    if clicked:
                        break
                    await page.evaluate("window.scrollBy(0, 4000)")
                    await asyncio.sleep(1.2)

                if not clicked:
                    # Fallback: navigate directly if click failed (go_back() depleted cards)
                    if url:
                        log_fn(f"Menu: {i+1}/{n} — {name} — click failed, trying direct nav")
                        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    else:
                        log_fn(f"Menu: {i+1}/{n} — {name} — no URL, skipping")
                        page.remove_listener("response", on_store_response)
                        continue
                else:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception as exc:
                log_fn(f"Menu: {i+1}/{n} — {name} — click/nav failed: {exc}")
                page.remove_listener("response", on_store_response)
                continue

            deadline = asyncio.get_event_loop().time() + 12
            while not store_raw and asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.5)

            page.remove_listener("response", on_store_response)

            if not store_raw:
                log_fn(f"Menu: {i+1}/{n} — {name} — getStoreV1 not captured, skipping")
                continue

            try:
                store_data = json.loads(store_raw[0])
                items = _parse_menu_items(store_data)
                count = db.insert_menu_items(lid, items)
                menu_items_saved += count
                # getStoreV1 often has richer promotion detail — overwrite feed promos
                store_obj = (store_data.get("data") or {}).get("storeInfo") or {}
                if store_obj:
                    rich_promos = _parse_promotions(store_obj)
                    if rich_promos:
                        db.upsert_promotions(lid, rich_promos)
                    rich_hours = _parse_regular_hours(store_obj)
                    if rich_hours:
                        db.patch_listing(lid, {"opening_hours": rich_hours})
                log_fn(f"Menu: {i+1}/{n} — {name} — {count} items saved")
            except Exception as exc:
                log_fn(f"Menu: {i+1}/{n} — {name} — parse/save error: {exc}")

        log_fn(f"Done — {records_saved} listings, {menu_items_saved} menu items saved")
        return ScraperResult(
            records_saved=records_saved,
            restaurants=restaurants,
            menu_items_saved=menu_items_saved,
        )


_DAY_MAP = {
    "MONDAY": "mon", "TUESDAY": "tue", "WEDNESDAY": "wed",
    "THURSDAY": "thu", "FRIDAY": "fri", "SATURDAY": "sat", "SUNDAY": "sun",
}

def _parse_regular_hours(store: dict) -> dict | None:
    """Extract weekly opening hours from a UberEats store/storeInfo object.

    Tries multiple known field names since the API has varied them over time.
    Returns {"mon": ["11:00", "22:30"], ...} or None if unavailable.
    """
    slots = (
        store.get("regularHours")
        or store.get("storeHours")
        or store.get("operatingHours")
        or store.get("hoursV2")
    )
    if not slots or not isinstance(slots, list):
        return None
    result: dict[str, list[str]] = {}
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        day_raw = slot.get("dayOfWeek") or slot.get("day") or ""
        day = _DAY_MAP.get(str(day_raw).upper())
        if not day:
            continue
        start = slot.get("startTime") or slot.get("open") or slot.get("from") or ""
        end = slot.get("endTime") or slot.get("close") or slot.get("to") or ""
        if not start or not end:
            continue
        result[day] = [str(start)[:5], str(end)[:5]]
    return result or None


def _extract_store_image(store: dict) -> str | None:
    """Extract best restaurant hero/thumbnail image from a UberEats store object."""
    for key in ("heroImageUrls", "thumbnailImageUrls", "coverImageUrls"):
        imgs = store.get(key)
        if imgs and isinstance(imgs, list):
            url = (imgs[0] or {}).get("url")
            if url:
                return url
    return store.get("trackingImageUrl") or store.get("imageUrl") or None


def _parse_menu_items(store_data: dict) -> list[dict]:
    """Extract menu items from a getStoreV1 API response.

    Real structure:
      data.catalogSectionsMap = {store_uuid: [section, ...]}
      section = {type, catalogSectionUUID, payload}
      payload.standardItemsPayload.{title.text, catalogItems[]}
      catalogItems[].{title, price (int cents), uuid}
    """
    items: list[dict] = []
    sections_map: dict = (
        store_data.get("data", {}).get("catalogSectionsMap") or {}
    )
    for sections_list in sections_map.values():
        if not isinstance(sections_list, list):
            continue
        for section in sections_list:
            payload = section.get("payload") or {}
            std = payload.get("standardItemsPayload") or {}
            if not std:
                continue
            catalog_name: str | None = (std.get("title") or {}).get("text")
            for ci in std.get("catalogItems") or []:
                price_cents = ci.get("price")
                price_eur = price_cents / 100 if isinstance(price_cents, (int, float)) else None
                title = ci.get("title", "")
                image_url = ci.get("imageUrl") or None
                description = ci.get("itemDescription") or ci.get("description") or None
                if title:
                    items.append({
                        "title": title,
                        "price": price_eur,
                        "catalog_name": catalog_name,
                        "image_url": image_url,
                        "description": description,
                    })
    return items


def _parse_promotions(store: dict) -> list[dict]:
    """Extract all structured promotions from a UberEats store object.

    Sources:
      1. store.signposts[]                — feed-level badges (all, not just index 0)
      2. store.promotionInfo.promotions[] — structured objects with numeric values
      3. store.fareInfo.serviceFeeDeal    — delivery fee deal
    """
    seen: set[str] = set()
    promos: list[dict] = []

    def _add(text: str, override: dict | None = None) -> None:
        text = text.strip()
        if not text or text.lower() in seen:
            return
        seen.add(text.lower())
        p = classify_promo(text)
        if override:
            p.update({k: v for k, v in override.items() if v is not None})
        promos.append(p)

    for sp in store.get("signposts") or []:
        _add(sp.get("text", ""))

    for p in (store.get("promotionInfo") or {}).get("promotions") or []:
        title = (p.get("title") or "").strip()
        if not title:
            continue
        override: dict = {}
        if p.get("discountValue") is not None:
            override["value"] = float(p["discountValue"])
        if p.get("minOrderValue") is not None:
            override["min_order"] = round(p["minOrderValue"] / 100, 2)
        _add(title, override)

    fare = store.get("fareInfo") or {}
    deal = fare.get("serviceFeeDeal") or {}
    deal_label = deal.get("label") or deal.get("title") or ""
    if deal_label:
        # Extract numeric threshold from serviceFeeDeal if available
        threshold_cents = deal.get("minOrderSubtotal") or deal.get("minSubtotal") or deal.get("minOrder")
        override_fee: dict = {}
        if threshold_cents is not None:
            override_fee["min_order"] = round(float(threshold_cents) / 100, 2)
        _add(deal_label, override_fee or None)

    return promos


def _parse_fee(val: str | None) -> float | None:
    if not val:
        return None
    import re
    low = val.lower()
    if any(w in low for w in ("gratuit", "free", "gratis")):
        return 0.0
    m = re.search(r"(\d+)[,.](\d+)", val)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"(\d+)", val)
    return float(m.group(1)) if m else None


def _parse_float(val: str | None) -> float | None:
    if not val:
        return None
    import re
    m = re.search(r"[\d.]+", str(val))
    return float(m.group()) if m else None


def _parse_eta_min(eta: str | None) -> int | None:
    if not eta:
        return None
    import re
    m = re.match(r"(\d+)", eta.strip())
    return int(m.group(1)) if m else None


def _parse_eta_max(eta: str | None) -> int | None:
    if not eta:
        return None
    import re
    m = re.search(r"-(\d+)", eta.strip())
    return int(m.group(1)) if m else None


def _parse_ue_menu(json_resp: dict, catalog_name: str) -> list[dict]:
    """Parse menu items from getSectionFeedV1 or getStoreLayoutV1 JSON response.

    Supports two formats:
    1. Simple catalogSectionsMap with catalogItems (getSectionFeedV1):
       {
           "catalogSectionsMap": {
               "section_key": {
                   "catalogItems": [
                       {"title": "...", "price": int (cents), ...}
                   ]
               }
           }
       }

    2. Nested structure with standardItemsPayload (getStoreV1):
       {
           "data": {
               "catalogSectionsMap": {
                   "store_uuid": [
                       {
                           "payload": {
                               "standardItemsPayload": {
                                   "catalogItems": [...]
                               }
                           }
                       }
                   ]
               }
           }
       }

    UberEats API returns prices in cents (1199 = €11.99).
    """
    items = []

    # Try nested format first (getStoreV1)
    sections_map: dict = json_resp.get("data", {}).get("catalogSectionsMap", {})

    if sections_map and isinstance(next(iter(sections_map.values()), None), list):
        # Nested format: values are lists of sections
        for sections_list in sections_map.values():
            if not isinstance(sections_list, list):
                continue
            for section in sections_list:
                payload = section.get("payload") or {}
                std = payload.get("standardItemsPayload") or {}
                if not std:
                    continue
                for ci in std.get("catalogItems") or []:
                    price_cents = ci.get("price")
                    price = price_cents / 100 if isinstance(price_cents, (int, float)) else None
                    title = ci.get("title", "").strip()
                    if title:
                        items.append({
                            "title": title,
                            "price": price,
                            "catalog_name": catalog_name,
                        })
    else:
        # Try simple format (getSectionFeedV1)
        sections_map = json_resp.get("catalogSectionsMap", {})
        for section_key, section_data in sections_map.items():
            if not isinstance(section_data, dict):
                continue
            catalog_items = section_data.get("catalogItems", [])
            for item in catalog_items:
                title = item.get("title", "").strip()
                price_cents = item.get("price")

                # Convert cents to euros if present
                price = None
                if price_cents is not None and isinstance(price_cents, (int, float)):
                    price = round(price_cents / 100, 2)

                if title:
                    items.append({
                        "title": title,
                        "price": price,
                        "catalog_name": catalog_name,
                    })

    return items
