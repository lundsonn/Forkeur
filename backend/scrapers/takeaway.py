from __future__ import annotations
import asyncio
import re
from typing import Callable
from models import ScraperConfig, ScraperResult
from scrapers.base import (
    new_browser, new_page, wait_for_cf_clear,
    noop_log, parse_menu_price, CloudflareBlockedError,
)
import db
from scrapers.promos import parse_promo_texts

_LISTING_BASE = "https://www.takeaway.com/be-fr/livraison/repas/"

# Brussels zones by postal code — each loaded in a fresh browser context to avoid CF re-challenge
LISTING_ZONES = [
    "bruxelles-1000",   # City center / Pentagone
    "bruxelles-1020",   # Laeken
    "bruxelles-1030",   # Schaerbeek
    "bruxelles-1040",   # Etterbeek
    "bruxelles-1050",   # Ixelles / Elsene
    "bruxelles-1060",   # Saint-Gilles / Sint-Gillis
    "bruxelles-1070",   # Anderlecht
    "bruxelles-1080",   # Molenbeek
    "bruxelles-1090",   # Jette
    "bruxelles-1140",   # Evere
    "bruxelles-1150",   # Woluwe-Saint-Pierre
    "bruxelles-1160",   # Auderghem
    "bruxelles-1180",   # Uccle
    "bruxelles-1190",   # Forest / Vorst
    "bruxelles-1200",   # Woluwe-Saint-Lambert
    "bruxelles-1210",   # Saint-Josse-ten-Noode
]

_CARD_JS = "document.querySelectorAll('[data-qa=\"card-element\"]').length"

_MENU_EVAL = """
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
        const imgEl = node.querySelector('img[src]');
        const descEl = node.querySelector('[data-qa="item-description"]');
        const description = descEl ? (descEl.innerText || '').trim() || null : null;
        cur.items.push({ title, price, image_url: imgEl ? imgEl.src : null, description });
    }
    return { sections };
}
"""

_LISTING_EVAL = """
() => {
    const cards = Array.from(document.querySelectorAll('[data-qa="restaurant-card"]'));
    const seen = new Set();
    return cards.flatMap(card => {
        const a = card.querySelector('a[href*="/menu/"]');
        if (!a) return [];
        const href = a.getAttribute('href') || '';
        const slug = (href.match(/\\/menu\\/([^?#]+)/) || [])[1] || '';
        if (!slug || seen.has(slug)) return [];
        seen.add(slug);

        const text = (card.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
        // Capture promo lines before filtering them from name candidates
        const promoLines = text.filter(l =>
            /%/.test(l) ||
            /gratuit|free delivery|gratis|livraison.{0,20}offerte?|€0/i.test(l) ||
            /achet[eé].{0,20}offert|offert.{0,20}achet[eé]|buy.{0,8}get.{0,8}free/i.test(l) ||
            /remise|réduction|korting|rabatt|discount|spend\s+€|dépense|besteed/i.test(l)
        );
        const nameCandidates = text.filter(l =>
            l.length > 2 &&
            !/^Sponsorisé|^Gesponsord|^Sponsored|^Ad$/i.test(l) &&
            !/^\\d+(\\.\\d+)?$/.test(l) &&
            !/%/.test(l) &&
            !/^[€£$]/.test(l) &&
            !/à partir de|starting from|vanaf/i.test(l) &&
            !/gratuit|free delivery|gratis/i.test(l) &&
            !/carte de fidélité|loyalty|spaarpunten/i.test(l)
        );
        const name = nameCandidates[0] || slug;

        const ratingM = text.find(l => /^[1-5][,.]\\d/.test(l));
        const rating = ratingM ? ratingM.replace(',', '.') : null;

        const eta = text.find(l => /\\d+\\s*-\\s*\\d+\\s*min|\\d+\\s*min/i.test(l)) || null;

        const feeEl = card.querySelector('[data-qa="delivery-fee"], [data-qa="restaurant-delivery-fee"]');
        const feeText = feeEl ? (feeEl.innerText || '').trim() : null;

        const heroImg = card.querySelector('img[src]');
        const image_url = heroImg ? heroImg.src : null;

        return [{ name, slug, href, rating, eta, feeText, promoLines, image_url }];
    });
}
"""


_PROMO_EVAL = """
() => {
    const texts = new Set();
    // data-qa promo elements
    document.querySelectorAll(
        '[data-qa*="promo"], [data-qa*="offer"], [data-qa*="deal"], [data-qa*="discount"], [data-qa*="voucher"], [data-qa*="banner"]'
    ).forEach(el => {
        const t = (el.innerText || '').trim();
        if (t && t.length < 200) texts.add(t);
    });
    // class-based promo elements
    document.querySelectorAll(
        '[class*="promo"], [class*="Promo"], [class*="discount"], [class*="Discount"], [class*="offer"], [class*="Offer"]'
    ).forEach(el => {
        const t = (el.innerText || '').trim();
        if (t && t.length < 200) texts.add(t);
    });
    // text nodes matching promo patterns
    Array.from(document.querySelectorAll('span, p, div, li, h2, h3')).forEach(el => {
        if (el.children.length > 3) return;
        const t = (el.innerText || '').trim();
        if (t.length > 3 && t.length < 200 && (
            /gratuit|free delivery|gratis|livraison.{0,20}offerte?|€0/i.test(t) ||
            /%\s*(?:de\s+r[ée]duction|off|korting|rabatt|remise)/i.test(t) ||
            /achet[eé].{0,20}offert|buy.{0,8}get.{0,8}free/i.test(t) ||
            /spend\s+€\d|dépense.{0,20}€|besteed.{0,20}€/i.test(t)
        )) { texts.add(t); }
    });
    return { promoLines: Array.from(texts) };
}
"""


async def scrape_menu_page(page, listing_id: str, url: str) -> tuple[str, list[dict], list[str]]:
    """Navigate to menu page, scroll fully, extract items. Returns (listing_id, items)."""
    try:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass

        title = await page.title()
        if "just a moment" in title.lower():
            cleared = await wait_for_cf_clear(page, timeout_s=60)
            if not cleared:
                raise CloudflareBlockedError("CF not cleared on menu page")

        try:
            await page.wait_for_selector('[data-qa="card-element"]', timeout=20000)
        except Exception:
            return (listing_id, [], [])

        # Height-stable scroll
        prev_h = 0
        for _ in range(20):
            h = await page.evaluate("document.body.scrollHeight")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(600)
            if h == prev_h:
                break
            prev_h = h

        # Item-count-stable scroll
        prev_cnt = 0
        for _ in range(15):
            cur_cnt = await page.evaluate(_CARD_JS)
            if cur_cnt == prev_cnt:
                break
            prev_cnt = cur_cnt
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(700)
        await page.wait_for_timeout(500)

        dom = await page.evaluate(_MENU_EVAL)
        items = []
        for section in dom.get("sections", []):
            catalog = section.get("heading", "Menu")
            for item in section.get("items", []):
                title = item.get("title", "").strip()
                price = parse_menu_price(item.get("price", ""))
                if title:
                    items.append({"title": title, "price": price, "catalog_name": catalog, "image_url": item.get("image_url"), "description": item.get("description")})

        promo_dom = await page.evaluate(_PROMO_EVAL)
        promo_lines = promo_dom.get("promoLines") or []

        return (listing_id, items, promo_lines)

    except CloudflareBlockedError:
        raise
    except Exception:
        return (listing_id, [], [])


async def run(config: ScraperConfig, log_fn: Callable[[str], None] = noop_log) -> ScraperResult:
    log_fn("Starting Takeaway scraper (Playwright DOM)")
    # headed=True required — CF passes on datacenter IP only with headed Chromium
    browser = await new_browser(lang="fr-BE", headed=True)
    records_saved = 0
    menu_items_saved = 0

    try:
        # Phase 0: collect listings — one fresh browser context per zone to avoid CF re-challenge.
        # All restaurant cards are rendered server-side on the first page load (no infinite scroll /
        # lazy pagination), so a single load + extract is sufficient per zone.
        all_by_slug: dict[str, dict] = {}
        for zone in LISTING_ZONES:
            url = _LISTING_BASE + zone
            log_fn(f"Loading zone {zone}")
            zone_page = await new_page(browser, lang="fr-BE")
            try:
                async def _scrape_zone():
                    await zone_page.goto(url, wait_until="domcontentloaded", timeout=60000)

                    title = await zone_page.title()
                    if "just a moment" in title.lower():
                        log_fn(f"  CF challenge — waiting up to 60s")
                        cleared = await wait_for_cf_clear(zone_page, timeout_s=60)
                        if not cleared:
                            log_fn(f"  CF not cleared — skipping {zone}")
                            return []

                    try:
                        await zone_page.wait_for_selector('[data-qa="restaurant-card"]', timeout=20000)
                    except Exception:
                        log_fn(f"  No cards — skipping {zone}")
                        return []

                    await zone_page.wait_for_timeout(1000)
                    return await zone_page.evaluate(_LISTING_EVAL)

                try:
                    page_restaurants = await asyncio.wait_for(_scrape_zone(), timeout=120)
                except asyncio.TimeoutError:
                    log_fn(f"  ⚠ zone timed out after 120s, skipping")
                    page_restaurants = []

                new_count = 0
                for r in page_restaurants:
                    if r["slug"] not in all_by_slug:
                        all_by_slug[r["slug"]] = r
                        new_count += 1

                log_fn(f"  {len(page_restaurants)} cards, {new_count} new (total {len(all_by_slug)})")
                await asyncio.sleep(2)
            except Exception as exc:
                log_fn(f"  Error: {exc}")
            finally:
                await zone_page.close()

        restaurants = list(all_by_slug.values())
        log_fn(f"Found {len(restaurants)} unique restaurants across all zones")

        if config.target:
            restaurants = [r for r in restaurants
                           if config.target.lower() in r["name"].lower()
                           or config.target.lower() in r["slug"].lower()]

        if config.max_items:
            restaurants = restaurants[:config.max_items]

        # Phase 1: upsert listings
        saved: list[tuple[dict, str]] = []
        for r in restaurants:
            try:
                rid = db.upsert_restaurant({"name": r["name"], "slug": r["slug"], "image_url": r.get("image_url")})
            except ValueError:
                continue
            url = f"https://www.takeaway.com{r['href']}"
            lid = db.upsert_listing({
                "restaurant_id": rid,
                "platform": "takeaway",
                "url": url,
                "rating": _parse_float(r.get("rating")),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
                "delivery_fee": parse_menu_price(r.get("feeText")),
                "discount_label": None,
            })
            db.upsert_promotions(lid, parse_promo_texts(r.get("promoLines") or []))
            records_saved += 1
            saved.append((r, lid))

        log_fn(f"Phase 1 done — {records_saved} listings saved")

        if config.listing_only:
            return ScraperResult(records_saved=records_saved)

        # Phase 2: menu per restaurant — fresh page per restaurant to avoid CF re-challenge

        n = len(saved)
        for i, (r, lid) in enumerate(saved):
            url = f"https://www.takeaway.com{r['href']}"
            log_fn(f"Menu: {i + 1}/{n} — {r['name']}")
            menu_page = await new_page(browser, lang="fr-BE")
            try:
                _, items, promo_lines = await scrape_menu_page(menu_page, lid, url)
                if items:
                    count = db.insert_menu_items(lid, items)
                    menu_items_saved += count
                    log_fn(f"  {count} items saved")
                else:
                    log_fn(f"  No items found")
                if promo_lines:
                    db.upsert_promotions(lid, parse_promo_texts(promo_lines))
                    log_fn(f"  {len(promo_lines)} promo lines found")
            except CloudflareBlockedError:
                log_fn(f"  CF blocked — skipping {r['name']}")
            except Exception as exc:
                log_fn(f"  Error: {exc}")
            finally:
                await menu_page.close()
            await asyncio.sleep(1)

        log_fn(f"Done — {records_saved} listings, {menu_items_saved} menu items saved")
        return ScraperResult(
            records_saved=records_saved,
            restaurants=restaurants,
            menu_items_saved=menu_items_saved,
        )

    finally:
        await browser.close()


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
    m = re.search(r"-\s*(\d+)", eta.strip())
    return int(m.group(1)) if m else None
