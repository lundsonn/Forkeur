from __future__ import annotations
import asyncio
import json
import os
import re
from typing import Callable
from constants import DEFAULT_ADDRESS
from models import ScraperConfig, ScraperResult
from scrapers.metrics import RunMetrics
from scrapers.base import browser_session, new_page, check_cloudflare, noop_log
from scrapers.promos import classify_promo, extract_min_order, parse_promo_texts
import db


_RUN_TIMEOUT_S = int(os.getenv("UBEREATS_RUN_TIMEOUT_S", "14400"))  # 4h; 20-zone run ~3h

# One representative address per Brussels postal code.
LISTING_ZONES = [
    "Place Royale 1, 1000 Bruxelles",
    "Place de Laeken 1, 1020 Bruxelles",
    "Place Colignon 1, 1030 Bruxelles",
    "Chaussée d'Etterbeek 100, 1040 Bruxelles",
    "Chaussée d'Ixelles 100, 1050 Bruxelles",
    "Parvis de Saint-Gilles 1, 1060 Bruxelles",
    "Place de la Vaillance 1, 1070 Bruxelles",
    "Chaussée de Gand 100, 1080 Bruxelles",
    "Parvis de la Basilique 1, 1081 Bruxelles",
    "Rue au Bois 100, 1082 Bruxelles",
    "Avenue Charles-Quint 100, 1083 Bruxelles",
    "Rue du Prêtre 100, 1090 Bruxelles",
    "Rue de Fiennes 1, 1140 Bruxelles",
    "Avenue de Tervuren 1, 1150 Bruxelles",
    "Chaussée de Wavre 1, 1160 Bruxelles",
    "Drève du Caporal 1, 1170 Bruxelles",
    "Avenue Brugmann 100, 1180 Bruxelles",
    "Rue de Forest 100, 1190 Bruxelles",
    "Avenue de Tervuren 200, 1200 Bruxelles",
    "Rue Royale 100, 1210 Bruxelles",
]

async def run(config: ScraperConfig, log_fn: Callable[[str], None] = noop_log, run_id: str | None = None, metrics: RunMetrics | None = None) -> ScraperResult:
    log_fn("Starting UberEats scraper")
    records_saved = 0

    zones = LISTING_ZONES if config.address == DEFAULT_ADDRESS else [config.address]

    async with browser_session(lang="fr-BE") as browser:
        try:
            async with asyncio.timeout(_RUN_TIMEOUT_S):
                page = await new_page(browser, lang="fr-BE")

                # ── Phase 1: collect restaurant listings across all zones ──────────
                # Global dedup across zones — same restaurant may appear in multiple zones.
                seen_uuids: set[str] = set()
                # 4-tuple: (restaurant_dict, listing_id, restaurant_id, zone_listing_url)
                saved_listings: list[tuple[dict, str, str, str]] = []
                promo_total = 0
                if metrics: metrics.phase_start("phase1")
                log_fn("Loading ubereats.com...")
                # Navigate directly to /be to avoid GeoIP redirect to /de (server is in Germany).
                # Use "load" so React fully hydrates before we probe the address input —
                # domcontentloaded fires before the SPA bootstraps.
                await page.goto("https://www.ubereats.com/be", wait_until="load", timeout=60000)
                check_cloudflare(await page.title())
                log_fn(f"Page loaded: {page.url}")

                for zone_idx, zone_addr in enumerate(zones):
                    log_fn(f"Zone {zone_idx + 1}/{len(zones)}: {zone_addr}")

                    feed_event = asyncio.Event()
                    feed_pages: list[dict] = []

                    async def on_response(response, _fe=feed_event, _fp=feed_pages):
                        if "getFeedV1" in response.url:
                            try:
                                text = await response.text()
                                parsed = json.loads(text)
                                # Extract only feed data to avoid accumulating 4-10MB of raw dicts
                                feed_data = parsed.get("data", {}).get("feedItems", [])
                                if feed_data:
                                    _fp.append(feed_data)
                                    _fe.set()
                            except Exception:
                                pass

                    page.on("response", on_response)

                    # Address input: on first zone the homepage is already loaded;
                    # on subsequent zones we navigate back to the homepage first.
                    if zone_idx > 0:
                        # Use "load" (not "domcontentloaded") so React hydrates before we probe
                        # for the input — domcontentloaded fires before the SPA bootstraps.
                        await page.goto("https://www.ubereats.com/be", wait_until="load", timeout=60000)
                        check_cloudflare(await page.title())

                    # Address input is already visible on the homepage — no "Find food" click needed
                    # Multiple selectors as fallback in case UberEats A/B-tests the input ID.
                    input_sel = (
                        "#location-typeahead-home-input, "
                        "[data-testid='location-typeahead-home-input'], "
                        "input[id*='typeahead'][id*='home'], "
                        "input[placeholder*='adresse' i], input[placeholder*='address' i]"
                    )
                    try:
                        await page.wait_for_selector(input_sel, timeout=40000)
                    except Exception as sel_err:
                        log_fn(f"Input selector timed out (title={await page.title()!r}, url={page.url!r}): {sel_err}")
                        raise
                    # Normalise: use the first matching element's actual locator for click/type
                    matched = await page.query_selector(input_sel)
                    input_sel = "#" + await matched.get_attribute("id") if matched and await matched.get_attribute("id") else input_sel
                    log_fn(f"Input found: {input_sel}")
                    await page.click(input_sel)
                    await page.type(input_sel, zone_addr, delay=60)
                    log_fn(f"Typed address: {zone_addr}")
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
                    try:
                        async with asyncio.timeout(25):
                            await feed_event.wait()
                    except asyncio.TimeoutError:
                        pass

                    if not feed_pages:
                        # NOT a bare TimeoutError: that aliases asyncio.TimeoutError, which
                        # the router treats as a wall-clock run timeout and mislabels as
                        # "timed out after N min". This is a distinct, retryable condition —
                        # UberEats never returned a restaurant feed (address not selected or
                        # an anti-bot interstitial). Raise a plain RuntimeError so the run is
                        # labelled accurately and the router's transient-retry path engages.
                        if len(zones) == 1:
                            raise RuntimeError("Feed API not captured (no restaurant feed returned)")
                        log_fn(f"Zone {zone_idx + 1}: no feed captured, skipping")
                        page.remove_listener("response", on_response)
                        continue

                    # Capture the zone listing URL after address selection (used for Phase 2 click-nav)
                    zone_listing_url = page.url

                    # Scroll to load all pages — UberEats uses infinite scroll with getFeedV1 per batch
                    log_fn("Scrolling to load all restaurants...")
                    prev_count = 0
                    stale_ticks = 0
                    max_stale = 3  # stop after 3 scroll cycles with no new responses
                    while stale_ticks < max_stale:
                        try:
                            await asyncio.wait_for(page.evaluate("window.scrollTo(0, document.body.scrollHeight)"), timeout=5)
                        except asyncio.TimeoutError:
                            pass
                        await asyncio.sleep(0.5)
                        cur_count = len(feed_pages)
                        if cur_count == prev_count:
                            stale_ticks += 1
                        else:
                            log_fn(f"Scroll: {cur_count} feed responses so far")
                            stale_ticks = 0
                        prev_count = cur_count

                    page.remove_listener("response", on_response)

                    # Aggregate stores for this zone, dedup globally by storeUuid
                    zone_stores = []
                    for feed in feed_pages:
                        feed_items = feed if isinstance(feed, list) else []
                        for item in feed_items:
                            if item.get("type") != "REGULAR_STORE":
                                continue
                            uuid = (item.get("store") or {}).get("storeUuid") or item.get("uuid") or ""
                            if uuid and uuid in seen_uuids:
                                continue
                            seen_uuids.add(uuid)
                            zone_stores.append(item)

                    log_fn(f"Zone {zone_idx + 1}: {len(zone_stores)} new unique restaurants (total seen: {len(seen_uuids)})")

                    zone_restaurants = []
                    for item in zone_stores:
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
                        zone_restaurants.append({
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
                        zone_restaurants = [r for r in zone_restaurants if config.target.lower() in r["name"].lower()]

                    log_fn(f"Saving {len(zone_restaurants)} restaurants from zone {zone_idx + 1}...")
                    zone_cap = config.max_items - records_saved if config.max_items else None
                    for r in (zone_restaurants[:zone_cap] if zone_cap is not None else zone_restaurants):
                        try:
                            slug = (r.get("url") or "").split("/store/")[-1].strip("/") or r["name"].lower().replace(" ", "-")
                            rid = db.upsert_restaurant({
                                "name": r["name"],
                                "slug": slug,
                                "lat": r.get("lat"),
                                "lng": r.get("lng"),
                                "image_url": r.get("image_url"),
                                "geo_source": "uber_eats",
                            })
                        except ValueError:
                            continue  # junk entry filtered by db._is_junk
                        hours = _parse_regular_hours(r.get("_store") or {})
                        eta_min = _parse_eta_min(r.get("eta"))
                        eta_max = _parse_eta_max(r.get("eta"))
                        delivery_fee = r.get("delivery_fee")
                        min_order = _parse_min_order(r.get("_store") or {})
                        lid = db.upsert_listing({
                            "restaurant_id": rid,
                            "platform": "uber_eats",
                            "url": r.get("url"),
                            "rating": _parse_float(r.get("rating")),
                            "discount_label": r.get("discount"),
                            **({"eta_min": eta_min} if eta_min is not None else {}),
                            **({"eta_max": eta_max} if eta_max is not None else {}),
                            **({"delivery_fee": delivery_fee} if delivery_fee is not None else {}),
                            **({"min_order": min_order} if min_order is not None else {}),
                            **({"opening_hours": hours} if hours else {}),
                        })
                        promos = _parse_promotions(r.get("_store") or {})
                        promo_total += db.upsert_promotions(lid, promos)
                        saved_listings.append((r, lid, rid, zone_listing_url))
                        records_saved += 1
                        if config.max_items and records_saved >= config.max_items:
                            break

                    log_fn(f"Zone {zone_idx + 1} done — {records_saved} total listings so far")
                    if run_id:
                        db.update_run_progress(run_id, records_saved)
                    if config.max_items and records_saved >= config.max_items:
                        break

                log_fn(f"Phase 1 done — {records_saved} listings, {promo_total} promotions saved")
                if metrics: metrics.phase_end("phase1")

                if config.listing_only:
                    return ScraperResult(records_saved=records_saved)

                # ── Phase 2: menu scraping via click-nav (parallel workers) ──────────
                # Direct goto(restaurant_url) triggers Uber bot-defense/reCAPTCHA.
                # Clicking from within the trusted listing session avoids detection.
                # We fan out across N sibling pages (same context = same delivery-address
                # session + cookies) so the menu loop runs ~N× faster. Each worker owns a
                # contiguous slice and click-navs within its own page independently.
                # Workers are grouped by zone so each worker page navigates back to the
                # correct zone listing (different zone URLs serve different restaurant sets).
                menu_items_saved = 0
                n = len(saved_listings)
                if metrics: metrics.phase_start("phase2"); metrics.attempt(n)
                failed_listings: list[tuple[dict, str, str, str]] = []
                _fail_lock = asyncio.Lock()
                from scrapers.base import new_sibling_page

                async def _scroll_listing(wp) -> None:
                    """Scroll the listing page to bottom until height stabilises, loading all cards."""
                    prev_h = 0
                    for _ in range(15):
                        try:
                            h = await asyncio.wait_for(
                                wp.evaluate("(function(){var h=document.body.scrollHeight;window.scrollTo(0,h);return h;})()"),
                                timeout=5,
                            )
                        except asyncio.TimeoutError:
                            break
                        await asyncio.sleep(0.8)
                        if h == prev_h:
                            break
                        prev_h = h
                    try:
                        await asyncio.wait_for(wp.evaluate("window.scrollTo(0, 0)"), timeout=5)
                    except asyncio.TimeoutError:
                        pass

                async def _scrape_one(wpage, r, lid, rid, zone_url: str) -> None:
                    """Scrape one restaurant's menu on `wpage` (already on the listing).

                    Click-navs to the store, captures getStoreV1, parses + saves.
                    On capture/click failure, queues (r, lid, rid, zone_url) for the retry pass.
                    Re-raises only on a page crash so the worker can recreate its page.
                    """
                    nonlocal menu_items_saved
                    url = r.get("url")
                    name = r.get("name", "?")
                    if not url:
                        return
                    store_path = url.split("/store/")[-1].strip("/") if "/store/" in url else ""
                    if not store_path:
                        return

                    store_raw: list[str] = []
                    store_event = asyncio.Event()

                    async def on_store_response(response, _buf=store_raw, _evt=store_event):
                        if "getStoreV1" in response.url and not _buf:
                            try:
                                _buf.append(await response.text())
                                _evt.set()
                            except Exception:
                                pass

                    wpage.on("response", on_store_response)
                    try:
                        # Ensure we're on the listing page (go_back preserves scroll state)
                        if zone_url not in wpage.url:
                            try:
                                await asyncio.wait_for(
                                    wpage.go_back(wait_until="domcontentloaded", timeout=15000),
                                    timeout=20,
                                )
                            except (asyncio.TimeoutError, Exception):
                                await wpage.goto(zone_url, wait_until="domcontentloaded", timeout=20000)
                            await asyncio.sleep(2)

                        # Click restaurant anchor; scroll-retry if not yet in DOM.
                        slug_only = store_path.split("/")[0] if "/" in store_path else store_path
                        clicked = False
                        for _attempt in range(5):
                            clicked = await asyncio.wait_for(wpage.evaluate(
                                """([storePath, slugOnly]) => {
                                    const needle1 = '/store/' + storePath;
                                    const needle2 = '/store/' + slugOnly;
                                    const links = Array.from(document.querySelectorAll('a[href]'));
                                    const a = links.find(l => l.href.includes(needle1) || l.href.includes(needle2));
                                    if (a) { a.click(); return true; }
                                    return false;
                                }""",
                                [store_path, slug_only],
                            ), timeout=10)
                            if clicked:
                                break
                            await asyncio.wait_for(wpage.evaluate("window.scrollBy(0, 4000)"), timeout=5)
                            await asyncio.sleep(0.6)

                        if not clicked:
                            # Fallback: navigate directly if click failed (go_back depleted cards)
                            await wpage.goto(url, wait_until="domcontentloaded", timeout=15000)
                        else:
                            await wpage.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception as exc:
                        try:
                            wpage.remove_listener("response", on_store_response)
                        except Exception:
                            pass
                        async with _fail_lock:
                            failed_listings.append((r, lid, rid, zone_url))
                        if "crashed" in str(exc).lower():
                            raise  # bubble up so the worker recreates its page
                        return

                    try:
                        async with asyncio.timeout(12):
                            await store_event.wait()
                    except asyncio.TimeoutError:
                        pass

                    try:
                        wpage.remove_listener("response", on_store_response)
                    except Exception:
                        pass

                    if not store_raw:
                        async with _fail_lock:
                            failed_listings.append((r, lid, rid, zone_url))
                        return

                    try:
                        store_data = json.loads(store_raw[0])
                        items = _parse_menu_items(store_data)
                        store_obj = store_data.get("data") or {}
                        tasks: list = [asyncio.to_thread(db.insert_menu_items, lid, items)]
                        if store_obj:
                            rich_promos = _parse_promotions(store_obj)
                            if rich_promos:
                                tasks.append(asyncio.to_thread(db.upsert_promotions, lid, rich_promos))
                            rich_hours = _parse_section_hours(store_obj) or _parse_regular_hours(store_obj)
                            addr = _parse_address(store_obj)
                            phone = _parse_phone(store_obj)
                            patch: dict = {}
                            if rich_hours:
                                patch["opening_hours"] = rich_hours
                            if addr["street_address"]:
                                patch["street_address"] = addr["street_address"]
                            if addr["postal_code"]:
                                patch["postal_code"] = addr["postal_code"]
                            min_order_val = _parse_min_order(store_obj)
                            if min_order_val is not None:
                                patch["min_order"] = min_order_val
                            if patch:
                                tasks.append(asyncio.to_thread(db.patch_listing, lid, patch))
                            if phone:
                                tasks.append(asyncio.to_thread(db.patch_restaurant_phone, rid, phone))
                        results = await asyncio.gather(*tasks)
                        count = results[0]
                        menu_items_saved += count
                        log_fn(f"Menu: {name} — {count} items saved")
                    except Exception as exc:
                        log_fn(f"Menu: {name} — parse/save error: {exc}")

                async def _fresh_worker_page(zone_url: str):
                    """Recreate a worker's sibling page on `zone_url`, bounded so a wedged/poisoned
                    context can't hang the worker forever. Returns the page or None."""
                    try:
                        wp = await asyncio.wait_for(new_sibling_page(page), timeout=30)
                        await wp.goto(zone_url, wait_until="domcontentloaded", timeout=20000)
                        await asyncio.sleep(2)
                        await _scroll_listing(wp)
                        return wp
                    except Exception:
                        return None

                async def _worker(wid: int, slice_items: list, zone_url: str) -> None:
                    wpage = await new_sibling_page(page)
                    try:
                        await wpage.goto(zone_url, wait_until="domcontentloaded", timeout=20000)
                        await asyncio.sleep(2)
                        await _scroll_listing(wpage)
                        for k, (r, lid, rid, _zu) in enumerate(slice_items):
                            # Recycle the worker page every 30 restaurants — reusing one page
                            # across a whole slice of heavy menu loads leaks renderer RSS
                            # (full-batch creep drove free RAM to ~300MB). Close+reopen caps it.
                            if k > 0 and k % 30 == 0:
                                try:
                                    await wpage.close()
                                except Exception:
                                    pass
                                wpage = await _fresh_worker_page(zone_url)
                                if wpage is None:
                                    remaining = slice_items[k:]
                                    log_fn(f"Menu worker {wid}: recycle failed, abandoning {len(remaining)} to retry")
                                    async with _fail_lock:
                                        failed_listings.extend(remaining)
                                    return
                            needs_recover = False
                            try:
                                # Hard per-restaurant wall cap — a page crash can poison the
                                # shared context and wedge Playwright past its own timeouts.
                                await asyncio.wait_for(_scrape_one(wpage, r, lid, rid, zone_url), timeout=45)
                            except asyncio.TimeoutError:
                                log_fn(f"Menu worker {wid}: {r.get('name','?')} timed out, requeuing")
                                async with _fail_lock:
                                    failed_listings.append((r, lid, rid, zone_url))
                                needs_recover = True  # page likely wedged
                            except Exception:
                                # Crash bubbled from _scrape_one (already queued the item).
                                log_fn(f"Menu worker {wid}: page crashed, recreating")
                                needs_recover = True
                            if needs_recover:
                                try:
                                    await wpage.close()
                                except Exception:
                                    pass
                                wpage = await _fresh_worker_page(zone_url)
                                if wpage is None:
                                    # Context unrecoverable — hand the rest to the retry pass.
                                    remaining = slice_items[k + 1:]
                                    log_fn(f"Menu worker {wid}: unrecoverable, abandoning {len(remaining)} to retry")
                                    async with _fail_lock:
                                        failed_listings.extend(remaining)
                                    return
                    finally:
                        if wpage is not None:
                            try:
                                await wpage.close()
                            except Exception:
                                pass

                # Group saved_listings by zone_url, then run 3 parallel workers per zone serially.
                # Serial zones: each zone needs its own listing page (different address context);
                # parallel across zones would require separate browser contexts or race on page.
                # 3 (not 4) keeps batch peak RAM well clear of the 8GB ceiling.
                WORKERS = 3
                from itertools import groupby
                zone_groups: dict[str, list] = {}
                for item in saved_listings:
                    zu = item[3]
                    zone_groups.setdefault(zu, []).append(item)

                log_fn(f"Phase 2: {n} menus across {len(zone_groups)} zones, {WORKERS} workers/zone")
                for zone_url, zone_items in zone_groups.items():
                    slices = [zone_items[w::WORKERS] for w in range(WORKERS)]
                    log_fn(f"Phase 2: zone {zone_url} — {len(zone_items)} menus")
                    await asyncio.gather(
                        *[_worker(w, s, zone_url) for w, s in enumerate(slices) if s],
                        return_exceptions=True,
                    )

                log_fn(f"Phase 2 done — {menu_items_saved} menu items; {len(failed_listings)} queued for retry")
                if metrics: metrics.phase_end("phase2")
                if run_id:
                    db.update_run_progress(run_id, records_saved)

                # ── Phase 3: retry pass via listing click (direct goto doesn't trigger getStoreV1)
                if failed_listings:
                    if metrics: metrics.phase_start("phase3")
                    log_fn(f"Retry pass: {len(failed_listings)} restaurants missed in Phase 2")

                    retry_zone_groups: dict[str, list] = {}
                    for item in failed_listings:
                        zu = item[3]
                        retry_zone_groups.setdefault(zu, []).append(item)

                    for zone_url, retry_items in retry_zone_groups.items():
                        try:
                            await page.goto(zone_url, wait_until="domcontentloaded", timeout=20000)
                            await asyncio.sleep(3)
                            # Scroll to load all cards
                            prev_h = 0
                            for _ in range(15):
                                try:
                                    h = await asyncio.wait_for(page.evaluate("document.body.scrollHeight"), timeout=5)
                                    await asyncio.wait_for(page.evaluate("window.scrollTo(0, document.body.scrollHeight)"), timeout=5)
                                except asyncio.TimeoutError:
                                    break
                                await asyncio.sleep(0.6)
                                if h == prev_h:
                                    break
                                prev_h = h
                        except Exception as _e:
                            log_fn(f"Retry pass: failed to load zone listing {zone_url}: {_e}")

                        for r, lid, rid, _zu in retry_items:
                            url = r.get("url")
                            name = r.get("name", "?")
                            if not url:
                                continue
                            store_path = url.split("/store/")[-1].strip("/") if "/store/" in url else ""
                            if not store_path:
                                continue
                            retry_buf: list[str] = []
                            retry_event = asyncio.Event()
                            async def on_retry_response(response, _buf=retry_buf, _evt=retry_event):
                                if "getStoreV1" in response.url and not _buf:
                                    try:
                                        text = await response.text()
                                        _buf.append(text)
                                        _evt.set()
                                    except Exception:
                                        pass
                            page.on("response", on_retry_response)
                            try:
                                log_fn(f"Retry: {name}")
                                slug_only = store_path.split("/")[0] if "/" in store_path else store_path
                                clicked = await asyncio.wait_for(page.evaluate(
                                    """([storePath, slugOnly]) => {
                                        const needle1 = '/store/' + storePath;
                                        const needle2 = '/store/' + slugOnly;
                                        const links = Array.from(document.querySelectorAll('a[href]'));
                                        const a = links.find(l => l.href.includes(needle1) || l.href.includes(needle2));
                                        if (a) { a.click(); return true; }
                                        return false;
                                    }""",
                                    [store_path, slug_only],
                                ), timeout=10)
                                if not clicked:
                                    log_fn(f"Retry: {name} — not in DOM, skipping")
                                    page.remove_listener("response", on_retry_response)
                                    continue
                                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                                try:
                                    async with asyncio.timeout(15):
                                        await retry_event.wait()
                                except asyncio.TimeoutError:
                                    pass
                            except Exception as exc:
                                import traceback
                                log_fn(f"Retry: {name} — failed: {exc}\n{traceback.format_exc()}")
                                if "crashed" in str(exc).lower():
                                    try:
                                        page = await new_page(browser, lang="fr-BE")
                                        await page.goto(zone_url, wait_until="domcontentloaded", timeout=20000)
                                        await asyncio.sleep(2)
                                    except Exception:
                                        pass
                            page.remove_listener("response", on_retry_response)
                            if not retry_buf:
                                log_fn(f"Retry: {name} — still no getStoreV1, giving up")
                                continue
                            try:
                                store_data = json.loads(retry_buf[0])
                                items = _parse_menu_items(store_data)
                                count = db.insert_menu_items(lid, items)
                                menu_items_saved += count
                                store_obj = store_data.get("data") or {}
                                if store_obj:
                                    rich_promos = _parse_promotions(store_obj)
                                    if rich_promos:
                                        db.upsert_promotions(lid, rich_promos)
                                    rich_hours = _parse_section_hours(store_obj) or _parse_regular_hours(store_obj)
                                    addr = _parse_address(store_obj)
                                    phone = _parse_phone(store_obj)
                                    patch: dict = {}
                                    if rich_hours:
                                        patch["opening_hours"] = rich_hours
                                    if addr["street_address"]:
                                        patch["street_address"] = addr["street_address"]
                                    if addr["postal_code"]:
                                        patch["postal_code"] = addr["postal_code"]
                                    if patch:
                                        db.patch_listing(lid, patch)
                                    if phone:
                                        db.patch_restaurant_phone(rid, phone)
                                log_fn(f"Retry: {name} — {count} items saved")
                            except Exception as exc:
                                log_fn(f"Retry: {name} — parse/save error: {exc}")
                            await asyncio.sleep(2)

                if failed_listings and metrics: metrics.phase_end("phase3")
                log_fn(f"Done — {records_saved} listings, {menu_items_saved} menu items saved")
                return ScraperResult(
                    records_saved=records_saved,
                    restaurants=[r for r, lid, rid, z in saved_listings],
                    menu_items_saved=menu_items_saved,
                )
        except asyncio.TimeoutError:
            log_fn(f"UberEats: run exceeded {_RUN_TIMEOUT_S}s watchdog, returning partial ({records_saved} records)")
            return ScraperResult(records_saved=records_saved)


_DAY_MAP = {
    "MONDAY": "mon", "TUESDAY": "tue", "WEDNESDAY": "wed",
    "THURSDAY": "thu", "FRIDAY": "fri", "SATURDAY": "sat", "SUNDAY": "sun",
}

# Localized day names used in getStoreV1 data.hours (locale follows server IP, not browser lang)
_LOCALIZED_DAY_MAP: dict[str, str] = {
    # English
    **_DAY_MAP,
    # German (VPS in Nuremberg → localeCode=de)
    "MONTAG": "mon", "DIENSTAG": "tue", "MITTWOCH": "wed",
    "DONNERSTAG": "thu", "FREITAG": "fri", "SAMSTAG": "sat", "SONNTAG": "sun",
    # French
    "LUNDI": "mon", "MARDI": "tue", "MERCREDI": "wed",
    "JEUDI": "thu", "VENDREDI": "fri", "SAMEDI": "sat", "DIMANCHE": "sun",
    # Dutch
    "MAANDAG": "mon", "DINSDAG": "tue", "WOENSDAG": "wed",
    "DONDERDAG": "thu", "VRIJDAG": "fri", "ZATERDAG": "sat", "ZONDAG": "sun",
}
_DAY_ORDER = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]


def _minutes_to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _parse_section_hours(store: dict) -> dict | None:
    """Parse hours from the current getStoreV1 format (data.hours).

    Format: [{"dayRange": "Montag - Mittwoch", "sectionHours": [{"startTime": 510, "endTime": 1170}]}]
    startTime/endTime are minutes since midnight. dayRange is localized.
    Collects ALL slots per day (e.g. lunch + dinner).
    Returns {"mon": [["08:30", "19:30"]], ...} (list of [start, end] pairs) or None.
    """
    hours_list = store.get("hours")
    if not hours_list or not isinstance(hours_list, list):
        return None
    result: dict[str, list[list[str]]] = {}
    for entry in hours_list:
        if not isinstance(entry, dict):
            continue
        day_range = entry.get("dayRange", "")
        slots = entry.get("sectionHours") or []
        # Collect every slot in this entry (a day can have multiple time ranges)
        pairs: list[list[str]] = []
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            start_min = slot.get("startTime")
            end_min = slot.get("endTime")
            if start_min is None or end_min is None:
                continue
            pairs.append([_minutes_to_hhmm(start_min), _minutes_to_hhmm(end_min)])
        if not pairs:
            continue
        # dayRange is either "Montag" or "Montag - Mittwoch"
        parts = [p.strip() for p in day_range.split(" - ")]
        if len(parts) == 1:
            day = _LOCALIZED_DAY_MAP.get(parts[0].upper())
            if day:
                result.setdefault(day, []).extend(pairs)
        elif len(parts) == 2:
            start_day = _LOCALIZED_DAY_MAP.get(parts[0].upper())
            end_day = _LOCALIZED_DAY_MAP.get(parts[1].upper())
            if start_day and end_day:
                si = _DAY_ORDER.index(start_day)
                ei = _DAY_ORDER.index(end_day)
                idxs = range(si, ei + 1) if ei >= si else list(range(si, 7)) + list(range(0, ei + 1))
                for i in idxs:
                    result.setdefault(_DAY_ORDER[i], []).extend(pairs)
    return result or None

def _parse_regular_hours(store: dict) -> dict | None:
    """Extract weekly opening hours from a UberEats store/storeInfo object.

    Tries multiple known field names since the API has varied them over time.
    Collects ALL slots per day (e.g. lunch + dinner).
    Returns {"mon": [["11:00", "22:30"]], ...} (list of [start, end] pairs) or None.
    """
    slots = (
        store.get("regularHours")
        or store.get("storeHours")
        or store.get("operatingHours")
        or store.get("hoursV2")
    )
    if not slots or not isinstance(slots, list):
        return None
    result: dict[str, list[list[str]]] = {}
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
        result.setdefault(day, []).append([str(start)[:5], str(end)[:5]])
    return result or None


def _parse_min_order(store: dict) -> float | None:
    """Best-effort minimum-order extraction from a getStoreV1 store object.

    The exact key has varied / is unconfirmed against a live store dump, so we
    probe a list of plausible paths and take the first numeric hit. Values are
    expected in integer cents (Uber's money format) → divide by 100.

    NOTE (needs live confirmation): the candidate paths below are educated
    guesses. Confirm against a real getStoreV1 store dump and prune to the
    real key once known.
    """
    candidates = [
        ("minimumOrder",),
        ("minOrderAmount",),
        ("fareInfo", "minimumOrder"),
        ("fareInfo", "minOrder"),
        ("feeInfo", "minimumOrder"),
        ("deliveryFee", "minimumSubtotal"),
        ("meta", "minSpend"),
    ]
    for path in candidates:
        cur: object = store
        for key in path:
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(key)
        if isinstance(cur, (int, float)) and cur > 0:
            return round(float(cur) / 100, 2)
    return None


def _parse_phone(store: dict) -> str | None:
    """Extract phone number from a UberEats getStoreV1 store object."""
    raw = (
        store.get("phoneNumber")
        or store.get("phone")
        or (store.get("contactInfo") or {}).get("phoneNumber")
        or (store.get("contactInfo") or {}).get("phone")
        or (store.get("location") or {}).get("phoneNumber")
    )
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _parse_address(store: dict) -> dict:
    """Extract street address + postal code from a UberEats getStoreV1 store object.

    The address lives under store["location"], whose shape has varied. Handles
    both a flat `{"streetAddress": ..., "postalCode": ...}` and a nested
    `{"address": {...}}` form, trying the most common key aliases. Returns
    {"street_address": str|None, "postal_code": str|None}; never raises.
    """
    loc = store.get("location")
    if not isinstance(loc, dict):
        return {"street_address": None, "postal_code": None}

    # Some shapes nest the real fields one level down under "address".
    nested = loc.get("address")
    src = nested if isinstance(nested, dict) else loc

    def _first_str(d: dict, keys: tuple[str, ...]) -> str | None:
        for k in keys:
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    street = _first_str(src, ("streetAddress", "address", "address1", "street"))
    # Postal code may sit alongside the street or back up on the flat location obj.
    postal = (
        _first_str(src, ("postalCode", "postal_code", "zipCode", "zip"))
        or _first_str(loc, ("postalCode", "postal_code", "zipCode", "zip"))
    )
    return {"street_address": street, "postal_code": postal}


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
                    item: dict = {
                        "title": title,
                        "price": price_eur,
                        "catalog_name": catalog_name,
                        "image_url": image_url,
                        "description": description,
                    }
                    items.append(item)
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
    m = re.search(r"[\d.]+", str(val))
    return float(m.group()) if m else None


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
