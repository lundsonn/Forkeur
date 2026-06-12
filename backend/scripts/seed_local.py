"""Local-only dev seed for the self-hosted Postgres (~/.forkeur-pg16).

Why this exists: UberEats Phase 2 workers spawn fresh sibling pages and
`goto(listing_url)`. Locally that renders 0 store anchors — UberEats only
builds the feed DOM from the *interactive* address-select flow, not from a
`goto` with the `pl=` param (even with shared cookies). So the normal scraper
saves listings but 0 menus locally. Prod's worker path renders anchors, so the
real scraper is left untouched.

This script drives the MAIN page (which DOES have anchors after select) and
click-navs serially, intercepting getStoreV1, reusing the scraper's parse + db
helpers. Throwaway dev tool — not wired into the app.

Run:  uv run python scripts/seed_local.py [N]   (N = restaurants, default 10)
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
from models import ScraperConfig
from scrapers import ubereats as U
from scrapers.base import new_browser, new_page

ADDRESS = ScraperConfig().address  # DEFAULT_ADDRESS


async def main(limit: int) -> None:
    feed_pages: list[list] = []
    feed_event = asyncio.Event()

    browser = await new_browser(lang="fr-BE")
    page = await new_page(browser, lang="fr-BE")

    async def on_feed(response):
        if "getFeedV1" in response.url:
            try:
                parsed = json.loads(await response.text())
                items = parsed.get("data", {}).get("feedItems", [])
                if items:
                    feed_pages.append(items)
                    feed_event.set()
            except Exception:
                pass

    page.on("response", on_feed)

    # ── interactive address select (the only path that renders feed anchors) ──
    await page.goto("https://www.ubereats.com/be", wait_until="domcontentloaded", timeout=60000)
    sel = "#location-typeahead-home-input"
    await page.wait_for_selector(sel, timeout=20000)
    await page.click(sel)
    await page.type(sel, ADDRESS, delay=60)
    await asyncio.sleep(3)
    try:
        await page.wait_for_selector('[role="option"]', timeout=5000)
    except Exception:
        pass
    await page.keyboard.press("ArrowDown")
    await asyncio.sleep(0.5)
    await page.keyboard.press("Enter")
    try:
        async with asyncio.timeout(25):
            await feed_event.wait()
    except asyncio.TimeoutError:
        print("no feed captured; aborting")
        await browser.close()
        return
    await asyncio.sleep(2)
    # scroll a little to load more cards
    for _ in range(3):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)

    # ── Phase 1: save restaurants + listings (mirrors ubereats.run) ──
    seen: set[str] = set()
    stores = []
    for feed in feed_pages:
        for item in feed:
            if item.get("type") != "REGULAR_STORE":
                continue
            uuid = (item.get("store") or {}).get("storeUuid") or item.get("uuid") or ""
            if uuid and uuid in seen:
                continue
            seen.add(uuid)
            stores.append(item)
    print(f"feed: {len(stores)} unique restaurants")

    # Only restaurants whose anchors are actually rendered in the feed DOM can
    # be click-opened. Read rendered store paths and prioritise those.
    rendered_paths: list[str] = await page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/store/"]'))
            .map(a => { const m = a.href.split('/store/')[1]; return m ? m.split('?')[0].replace(/\\/$/, '') : ''; })
            .filter(Boolean)"""
    )
    rendered_set = set(rendered_paths)
    print(f"rendered anchors: {len(rendered_set)}")

    def _path(item):
        s = item.get("store", {})
        au = s.get("actionUrl") or ""
        return au.split("/store/")[-1].split("?")[0].strip("/") if "/store/" in au else ""

    stores.sort(key=lambda it: _path(it) not in rendered_set)  # rendered first

    saved: list[tuple[dict, str, str]] = []
    for item in stores[:limit]:
        s = item.get("store", {})
        meta = s.get("meta", []) or []
        eta_meta = next((m for m in meta if m.get("badgeType") == "ETD"), None)
        fare = ((s.get("tracking") or {}).get("storePayload") or {}).get("fareInfo") or {}
        marker = s.get("mapMarker") or {}
        url = f"https://www.ubereats.com{s['actionUrl'].split('?')[0]}" if s.get("actionUrl") else None
        name = (s.get("title") or {}).get("text", "Unknown")
        try:
            slug = (url or "").split("/store/")[-1].strip("/") or name.lower().replace(" ", "-")
            rid = db.upsert_restaurant({
                "name": name, "slug": slug,
                "lat": marker.get("latitude"), "lng": marker.get("longitude"),
                "image_url": U._extract_store_image(s), "geo_source": "uber_eats",
            })
        except ValueError:
            continue
        hours = U._parse_regular_hours(s)
        lid = db.upsert_listing({
            "restaurant_id": rid, "platform": "uber_eats", "url": url,
            "rating": U._parse_float((s.get("rating") or {}).get("text", "N/A")),
            "eta_min": U._parse_eta_min((eta_meta or {}).get("text", "N/A")),
            "eta_max": U._parse_eta_max((eta_meta or {}).get("text", "N/A")),
            "delivery_fee": fare.get("serviceFee"),
            **({"opening_hours": hours} if hours else {}),
        })
        saved.append(({"name": name, "url": url}, lid, rid))
    print(f"phase 1: {len(saved)} listings saved")

    # ── Phase 2: open each store in a NEW TAB from the rendered feed ──
    # Direct goto(store_url) never fires getStoreV1 (bot defense). go_back
    # doesn't re-render the SPA feed anchors either. So: keep the feed page
    # intact and open each store via target=_blank click → real click-nav in a
    # fresh tab that DOES fire getStoreV1, while the feed keeps its anchors.
    pending: dict = {"raw": None, "evt": None}

    # Context-level route catches getStoreV1 with no listener-timing race.
    async def route_store(route):
        try:
            resp = await route.fetch()
            body = await resp.text()
            if pending["raw"] is not None and not pending["raw"]:
                pending["raw"].append(body)
                pending["evt"].set()
            await route.fulfill(response=resp)
        except Exception:
            try:
                await route.continue_()
            except Exception:
                pass

    await page.context.route("**/getStoreV1**", route_store)

    menus = 0
    for r, lid, rid in saved:
        url = r["url"]
        name = r["name"]
        if not url or "/store/" not in url:
            continue
        store_path = url.split("/store/")[-1].strip("/")
        slug_only = store_path.split("/")[0]
        pending["raw"] = []
        pending["evt"] = asyncio.Event()
        try:
            # Uber's SPA router navigates the page on anchor click (target=_blank
            # is ignored), so after each store we must return to the feed and
            # re-render its anchors before the next click.
            if "/feed" not in page.url:
                try:
                    await page.go_back(wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(2)
                    for _ in range(4):
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(0.8)
                    await page.evaluate("window.scrollTo(0, 0)")
                except Exception:
                    pass
            opened = False
            for _ in range(8):
                opened = await page.evaluate(
                    """([sp, so]) => {
                        const links = Array.from(document.querySelectorAll('a[href]'));
                        const a = links.find(l => l.href.includes('/store/'+sp) || l.href.includes('/store/'+so));
                        if (a) { a.click(); return true; }
                        return false;
                    }""",
                    [store_path, slug_only],
                )
                if opened:
                    break
                await page.evaluate("window.scrollBy(0, 3000)")
                await asyncio.sleep(0.6)
            if not opened:
                print(f"  {name}: anchor not found, skip")
                continue
            try:
                async with asyncio.timeout(15):
                    await pending["evt"].wait()
            except asyncio.TimeoutError:
                print(f"  {name}: no getStoreV1, skip")
                continue
            store_data = json.loads(pending["raw"][0])
            items = U._parse_menu_items(store_data)
            store_obj = store_data.get("data") or {}
            n = db.insert_menu_items(lid, items)
            menus += n
            if store_obj:
                addr = U._parse_address(store_obj)
                patch = {}
                if addr["street_address"]:
                    patch["street_address"] = addr["street_address"]
                if addr["postal_code"]:
                    patch["postal_code"] = addr["postal_code"]
                rich_hours = U._parse_section_hours(store_obj) or U._parse_regular_hours(store_obj)
                if rich_hours:
                    patch["opening_hours"] = rich_hours
                if patch:
                    db.patch_listing(lid, patch)
                phone = U._parse_phone(store_obj)
                if phone:
                    db.patch_restaurant_phone(rid, phone)
            print(f"  {name}: {n} items")
        except Exception as exc:
            print(f"  {name}: error {exc}")

    print(f"DONE — {len(saved)} listings, {menus} menu items")
    await browser.close()


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    asyncio.run(main(n))
