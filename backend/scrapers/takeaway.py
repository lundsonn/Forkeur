from __future__ import annotations
import asyncio
import re
from typing import Callable
from models import ScraperConfig, ScraperResult
from scrapers.base import new_browser, new_page, check_cloudflare, CloudflareBlockedError, noop_log, parse_menu_price, wait_for_cf_clear
import db

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"


def _parse_dom_items(dom_output: dict) -> list[dict]:
    """Parse menu items from Takeaway DOM eval output.

    Structure:
    {
        "sections": [
            {
                "heading": "Section Name",
                "items": [
                    {"title": "Item Name", "price": "8,99 €"}
                ]
            }
        ]
    }
    """
    items = []
    sections = dom_output.get("sections", [])

    for section in sections:
        catalog_name = section.get("heading", "Menu")
        if any(noise in catalog_name.lower() for noise in _HEADING_NOISE):
            continue
        section_items = section.get("items", [])

        for item in section_items:
            title = item.get("title", "").strip()
            price_str = item.get("price", "")

            # Use shared price parser (handles both € suffix and prefix)
            price = parse_menu_price(price_str)

            items.append({
                "title": title,
                "price": price,
                "catalog_name": catalog_name,
            })

    return items


# Section headings that are not menu categories (cart, business info, restaurant name).
_HEADING_NOISE = ("business details", "panier", "basket", "cart", "horaires", "informations")


async def _extract_menu_items(page, listing_id: str) -> tuple[str, list[dict]]:
    """Extract menu items from an already-loaded Takeaway menu page.

    Expects `[data-qa="card-element"]` to be present. Scrolls to load lazy sections.
    Returns: (listing_id, items)
    """
    items: list[dict] = []
    try:
        await page.wait_for_selector('[data-qa="card-element"]', timeout=20000)
    except Exception:
        return (listing_id, items)

    _count_js = "document.querySelectorAll('[data-qa=\"card-element\"]').length"

    # Scroll by height until stable.
    prev_height = 0
    for _ in range(25):
        height = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(600)
        if height == prev_height:
            break
        prev_height = height

    # Item-count-based scroll handles lazy categories that load after height stabilises.
    prev_count = 0
    for _ in range(15):
        cur_count = await page.evaluate(_count_js)
        if cur_count == prev_count:
            break
        prev_count = cur_count
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(700)
    await page.wait_for_timeout(500)

    dom_output = await page.evaluate("""
    () => {
        const sections = [];
        const nodes = Array.from(document.querySelectorAll(
            '[data-qa="heading"], [data-qa="card-element"]'
        ));
        let heading = 'Menu';
        let cur = null;
        for (const node of nodes) {
            const qa = node.getAttribute('data-qa');
            if (qa === 'heading') {
                heading = (node.innerText || '').trim() || 'Menu';
                continue;
            }
            const nameEl = node.querySelector('[data-qa="item-name"]');
            const priceEl = node.querySelector('[data-qa="item-price"]');
            if (!nameEl || !priceEl) continue;
            const title = (nameEl.innerText || '').trim();
            const price = (priceEl.innerText || '').trim();
            if (!title) continue;
            if (!cur || cur.heading !== heading) {
                cur = { heading, items: [] };
                sections.push(cur);
            }
            cur.items.push({ title, price });
        }
        return { sections };
    }
    """)

    items = _parse_dom_items(dom_output)
    return (listing_id, items)


async def scrape_menu_page(page, listing_id: str, url: str) -> tuple[str, list[dict]]:
    """Navigate to a Takeaway menu page via goto and extract items.

    Uses SPA click navigation from the current page if possible (avoids CF retrigger).
    Falls back to page.goto when no matching anchor is visible.

    Returns: (listing_id, items)
    """
    slug = url.split("/menu/")[-1].split("?")[0].rstrip("/")

    # Try SPA click first — client-side routing doesn't retrigger CF.
    clicked = False
    for _attempt in range(3):
        clicked = await page.evaluate(f"""
            (() => {{
                const a = document.querySelector('a[href*="/menu/{slug}"]');
                if (a) {{ a.scrollIntoView({{block:'center'}}); a.click(); return true; }}
                return false;
            }})()
        """)
        if clicked:
            break
        await page.evaluate("window.scrollBy(0, 3000)")
        await asyncio.sleep(0.8)

    if clicked:
        try:
            await page.wait_for_url("**/menu/**", timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(1)
        title = await page.title()
        if "instant" in title.lower() or "moment" in title.lower():
            cleared = await wait_for_cf_clear(page, timeout_s=45)
            if not cleared:
                raise CloudflareBlockedError("CF on menu page after SPA click")
    else:
        # Fallback: full goto. CF may retrigger; attempt to clear.
        cleared = False
        for attempt in range(2):
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            cleared = await wait_for_cf_clear(page, timeout_s=90)
            if cleared:
                break
            await asyncio.sleep(3 + attempt * 2)
        if not cleared:
            raise CloudflareBlockedError("menu page CF not cleared after goto")

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    return await _extract_menu_items(page, listing_id)


async def run(config: ScraperConfig, log_fn: Callable[[str], None] = noop_log) -> ScraperResult:
    log_fn("Starting Takeaway scraper")
    browser = await new_browser(lang="fr-BE", headed=True)
    records_saved = 0

    try:
        page = await new_page(browser, lang="fr-BE")

        log_fn(f"Loading {LISTING_URL}...")
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)

        log_fn("Waiting for Cloudflare challenge (human mouse simulation)...")
        cleared = await wait_for_cf_clear(page, timeout_s=90)
        if not cleared:
            check_cloudflare(await page.title())
        log_fn("CF cleared — waiting for restaurant cards to render...")

        # SPA needs a moment after CF clears before the restaurant fetch starts.
        await asyncio.sleep(3)

        # Title changes when CF passes, but the SPA still needs to fetch + render
        # the restaurant list. Wait for the first card before scrolling/eval.
        try:
            await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=60000)
        except Exception:
            log_fn("No restaurant-card selector after 60s — page may not have loaded")
        log_fn("Page loaded")

        log_fn("Scrolling to load restaurants...")
        for _ in range(8):
            await page.evaluate("window.scrollBy(0, 3000)")
            await asyncio.sleep(0.8)
        await asyncio.sleep(1)

        restaurants = await page.eval_on_selector_all('[data-qa="restaurant-card"]', """cards => {
            return cards.map(card => {
                const link = card.querySelector('a[href*="/menu/"]');
                const url = link ? link.href : '';
                const slug = (url.match(/\\/menu\\/([^?#]+)/) || [])[1] || '';
                const nameEl = card.querySelector('h2, h3, [data-qa*="name"]');
                const name = (nameEl && nameEl.textContent.trim()) || (link && link.textContent.trim()) || slug;
                const lines = (card.innerText || '').split('\\n').map(l => l.trim()).filter(Boolean);
                const rating = lines.find(l => /^\\d[,.]\\d$/.test(l)) || 'N/A';
                const reviewCount = (lines.find(l => /^\\(\\d[\\d.,]*\\+?\\)$/.test(l)) || '').replace(/[()]/g, '');
                const eta = lines.find(l => /\\d+-\\d+\\s*min/.test(l)) || 'N/A';
                const feeLine = lines.find(l => /^[€$]|livraison|bezorg|frais de livraison/i.test(l) && /\\d[,.]\\d/.test(l)) || null;
                const discountLine = lines.find(l =>
                    /spend|get|free|gratuit|promo|off|réduction|korting|-%|bonus/i.test(l) && l !== name
                ) || null;
                return { name, url, slug, rating, review_count: reviewCount, eta, delivery_fee: feeLine, discount: discountLine };
            });
        }""")

        # Deduplicate by slug
        seen: set[str] = set()
        unique = []
        for r in restaurants:
            if r["slug"] and r["slug"] not in seen:
                seen.add(r["slug"])
                unique.append(r)

        log_fn(f"Found {len(unique)} unique restaurants")

        if config.target:
            unique = [r for r in unique if config.target.lower() in r["name"].lower() or config.target.lower() in r["slug"].lower()]

        # Phase 1: save listings, collect (restaurant, listing_id) pairs for phase 2
        phase1: list[tuple[dict, str]] = []
        for r in (unique[:config.max_items] if config.max_items else unique):
            rid = db.upsert_restaurant({"name": r["name"], "slug": r["slug"]})
            lid = db.upsert_listing({
                "restaurant_id": rid,
                "platform": "takeaway",
                "url": r.get("url"),
                "rating": _parse_float(r.get("rating")),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
                "delivery_fee": _parse_fee(r.get("delivery_fee")),
                "discount_label": r.get("discount"),
            })
            records_saved += 1
            phase1.append((r, lid))

        log_fn(f"Phase 1 done — {records_saved} listings saved")

        # Phase 2: SPA click to each restaurant menu — client-side routing avoids CF retrigger.
        listing_url = page.url
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)
        menu_items_saved = 0
        n = len(phase1)
        for i, (r, lid) in enumerate(phase1):
            slug = r.get("slug", "")
            if not slug:
                log_fn(f"Menu: {i+1}/{n} — {r['name']} (no slug, skipping)")
                continue

            log_fn(f"Menu: {i+1}/{n} — {r['name']}")
            try:
                # Return to listing via go_back (SPA, no CF) if we navigated away.
                if listing_url not in page.url:
                    try:
                        await page.go_back(wait_until="domcontentloaded", timeout=15000)
                        await asyncio.sleep(0.5)
                    except Exception:
                        await page.goto(listing_url, wait_until="domcontentloaded", timeout=30000)
                        cleared = await wait_for_cf_clear(page, timeout_s=45)
                        if not cleared:
                            raise CloudflareBlockedError("CF on listing reload")
                        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)

                # SPA click — find the restaurant anchor, scroll into view, click.
                clicked = False
                for _attempt in range(4):
                    clicked = await page.evaluate(f"""
                        (() => {{
                            const a = document.querySelector('a[href*="/menu/{slug}"]');
                            if (a) {{ a.scrollIntoView({{block:'center'}}); a.click(); return true; }}
                            return false;
                        }})()
                    """)
                    if clicked:
                        break
                    await page.evaluate("window.scrollBy(0, 3000)")
                    await asyncio.sleep(0.8)

                if not clicked:
                    log_fn(f"  Link not found for {r['name']}, skipping")
                    continue

                try:
                    await page.wait_for_url("**/menu/**", timeout=10000)
                except Exception:
                    pass
                await asyncio.sleep(1)

                # SPA nav rarely triggers CF, but check as safety net.
                title = await page.title()
                if "instant" in title.lower() or "moment" in title.lower():
                    cleared = await wait_for_cf_clear(page, timeout_s=45)
                    if not cleared:
                        raise CloudflareBlockedError("CF on menu page")

                _, menu_items = await _extract_menu_items(page, lid)

                if menu_items:
                    db.insert_menu_items(lid, menu_items)
                    menu_items_saved += len(menu_items)
                    log_fn(f"  {len(menu_items)} items")
                else:
                    log_fn(f"  No items found")

                # Extract delivery fee from restaurant page (not shown on listing cards).
                fee_text: str | None = await page.evaluate("""() => {
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let node;
                    while ((node = walker.nextNode())) {
                        const t = node.textContent.trim();
                        if (t.length > 0 && t.length < 80 &&
                            /livraison|bezorg|delivery/i.test(t) &&
                            /€\s*\d|\d[,.]\d\s*€|gratuit|gratis|free/i.test(t)) {
                            return t;
                        }
                    }
                    // Fallback: any standalone "€ X,XX" line in the page header area
                    const all = Array.from(document.querySelectorAll('[data-qa]'));
                    for (const el of all) {
                        const t = (el.innerText || '').trim();
                        if (/^€\s*\d+[,.]\d+$/.test(t) || /gratuit|gratis|free delivery/i.test(t)) return t;
                    }
                    return null;
                }""")
                fee = _parse_fee(fee_text)
                if fee is not None and r.get("delivery_fee") is None:
                    db.patch_listing(lid, {"delivery_fee": fee})
                    log_fn(f"  Delivery fee: {fee}")

            except CloudflareBlockedError:
                log_fn(f"Menu: {i+1}/{n} — {r['name']} (Cloudflare blocked, skipping)")
            except Exception as exc:
                log_fn(f"Menu: {i+1}/{n} — {r['name']} (error: {exc}, skipping)")

        log_fn(f"Done — {records_saved} listings, {menu_items_saved} menu items saved")
        return ScraperResult(records_saved=records_saved, restaurants=unique, menu_items_saved=menu_items_saved)

    finally:
        await browser.close()


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
    m = re.search(r"[\d.]+", str(val).replace(",", "."))
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
