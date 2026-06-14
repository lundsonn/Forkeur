"""Targeted Deliveroo Phase 2: scrape menus for specific listings.

Queries listings that need Phase 2 (based on --mode) and runs the same
extraction logic as the main deliveroo.py Phase 2. No Phase 0/1 needed.

Modes:
  --mode null       listings where last_scraped_at IS NULL (Group D)
  --mode closed     listings where item_count <= 3 AND last_scraped_at IS NOT NULL (Group C)
  --mode ids        comma-separated listing IDs via --ids (manual override)

Run (on server):
    cd /opt/forkeur/backend
    DISPLAY=:99 uv run python -m scripts.deliveroo_phase2_targeted --mode null
    DISPLAY=:99 uv run python -m scripts.deliveroo_phase2_targeted --mode closed
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
import time

os.environ.setdefault("DISPLAY", ":99")

# Add backend/ to path when run as __main__
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import pgpool
from scrapers.base import new_browser, new_page, check_cloudflare, noop_log, CloudflareBlockedError
from scrapers.deliveroo import _venue_coords_from_page, _phone_from_page, _parse_fee
from scrapers.promos import parse_promo_texts, extract_min_order

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("deliveroo_phase2")


def _get_listings(mode: str, ids: list[str]) -> list[dict]:
    """Return rows: id, name, url, restaurant_id."""
    if mode == "ids":
        rows = pgpool.fetchall(
            """
            SELECT pl.id, r.name, pl.url, pl.restaurant_id
            FROM platform_listings pl
            JOIN restaurants r ON r.id = pl.restaurant_id
            WHERE pl.platform = 'deliveroo'
              AND pl.id = ANY(%s)
            ORDER BY r.name
            """,
            (ids,),
        )
    elif mode == "null":
        rows = pgpool.fetchall(
            """
            SELECT pl.id, r.name, pl.url, pl.restaurant_id
            FROM platform_listings pl
            JOIN restaurants r ON r.id = pl.restaurant_id
            WHERE pl.platform = 'deliveroo'
              AND pl.last_scraped_at IS NULL
              AND pl.url IS NOT NULL
              AND pl.url != ''
            ORDER BY r.name
            """,
        )
    elif mode == "closed":
        # Listings with ≤3 items that were scraped (not null) — likely closed at scrape time
        rows = pgpool.fetchall(
            """
            SELECT pl.id, r.name, pl.url, pl.restaurant_id
            FROM platform_listings pl
            JOIN restaurants r ON r.id = pl.restaurant_id
            LEFT JOIN (
                SELECT listing_id, COUNT(*) AS cnt
                FROM menu_items
                GROUP BY listing_id
            ) mi ON mi.listing_id = pl.id
            WHERE pl.platform = 'deliveroo'
              AND pl.last_scraped_at IS NOT NULL
              AND pl.url IS NOT NULL
              AND pl.url != ''
              AND COALESCE(mi.cnt, 0) <= 3
            ORDER BY r.name
            """,
        )
    else:
        raise ValueError(f"Unknown mode: {mode}")
    return [{"id": str(r["id"]), "name": r["name"], "url": r["url"], "restaurant_id": str(r["restaurant_id"])} for r in rows]


async def _scrape_one(page, listing: dict, log_fn) -> int:
    """Run Phase 2 extraction for one listing. Returns items saved count."""
    lid = listing["id"]
    rid = listing["restaurant_id"]
    name = listing["name"]
    url = listing["url"]

    log_fn(f"→ {name}")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass  # progressive load — timeout OK
    check_cloudflare(await page.title())

    venue = await _venue_coords_from_page(page)
    if venue:
        if venue.get("lat") is not None and venue.get("lng") is not None:
            db.patch_restaurant_geo(rid, venue["lat"], venue["lng"], "deliveroo_venue")
            log_fn(f"  coords: {venue['lat']:.5f}, {venue['lng']:.5f}")
        addr_patch = {
            "street_address": venue.get("street_address"),
            "postal_code": venue.get("postal_code"),
        }
        if any(addr_patch.values()):
            db.patch_listing(lid, addr_patch)
            log_fn(f"  addr: {addr_patch}")
        tel = venue.get("telephone") or await _phone_from_page(page)
        if tel:
            db.patch_restaurant_phone(rid, tel)
            log_fn(f"  phone: {tel}")

    try:
        await page.wait_for_selector(
            'div.notranslate, [class*="MenuItemCardV2"], [class*="MenuItemCard"], [data-testid="menu-item-image"]',
            timeout=25000,
        )
    except Exception:
        pass

    _EXPAND_JS = """() => {
        const seen = new Set();
        const selectors = [
            'button[aria-expanded="false"]',
            '[role="button"][aria-expanded="false"]',
            'button[data-testid*="expand"]',
            'button[data-testid*="accordion"]',
            'button[data-testid*="section"]',
        ];
        for (const sel of selectors) {
            for (const btn of document.querySelectorAll(sel)) {
                if (!seen.has(btn)) {
                    seen.add(btn);
                    try { btn.click(); } catch {}
                }
            }
        }
        return seen.size;
    }"""

    # Initial expand pass before scroll.
    try:
        expanded = await page.evaluate(_EXPAND_JS)
        if expanded:
            await page.wait_for_timeout(600)
            log_fn(f"  pre-scroll: expanded {expanded} section(s)")
    except Exception:
        pass

    # Scroll until stable; expand newly-mounted virtualised sections on each tick.
    prev_h, prev_count, stale, total_expanded = 0, 0, 0, 0
    for _ in range(40):
        result = await page.evaluate(
            "()=>({h:document.body.scrollHeight,"
            "c:document.querySelectorAll('div.notranslate').length})"
        )
        h, count = result["h"], result["c"]
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(600)
        try:
            n_exp = await page.evaluate(_EXPAND_JS)
            if n_exp:
                total_expanded += n_exp
                await page.wait_for_timeout(400)
        except Exception:
            pass
        if h == prev_h and count == prev_count:
            stale += 1
            if stale >= 3:
                break
        else:
            stale = 0
        prev_h, prev_count = h, count
    await page.evaluate("window.scrollTo(0, 0)")
    log_fn(f"  scroll done: {prev_count} notranslate divs, {total_expanded} expansions, url={page.url[:80]}")

    items: list[dict] = await page.evaluate("""() => {
        const seen = new Set();
        const out = [];
        const h2s = Array.from(document.querySelectorAll('h2'));

        function nearestHeading(el) {
            for (const h2 of [...h2s].reverse()) {
                if (h2.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)
                    return h2.innerText.trim();
            }
            return '';
        }

        function parsePrice(raw) {
            const m = raw.match(/(\\d+)[,.]?(\\d{0,2})/);
            if (!m) return null;
            const p = parseFloat(m[1] + '.' + (m[2] || '00').padEnd(2, '0'));
            return (p > 0 && p <= 200) ? p : null;
        }

        function addItem(title, price, catalogName, imageUrl, description) {
            title = title.trim().replace(/ /g, ' ');
            if (!title || title.length < 2 || price === null) return;
            if (/frais de livraison|leveringskosten|delivery fee|livraison offert|\d+\s*%\s*(sur|off|de réduction|korting|discount)/i.test(title)) return;
            const key = title + '|' + price;
            if (seen.has(key)) return;
            seen.add(key);
            out.push({ title, price, catalog_name: catalogName, image_url: imageUrl || null, description: description || null });
        }

        // Strategy 1: div.notranslate
        document.querySelectorAll('div.notranslate').forEach(nt => {
            if (nt.parentElement?.closest('div.notranslate')) return;
            const titleEl = nt.querySelector('p, span, h2, h3, h4') || nt;
            const title = (titleEl.innerText || '').trim();
            if (!title || title.length < 2) return;
            let el = nt;
            let priceM = null;
            let imageUrl = null;
            for (let i = 0; i < 6; i++) {
                if (!el.parentElement) break;
                el = el.parentElement;
                const text = (el.innerText || '').trim();
                if (!priceM) priceM = text.match(/(\\d+)[,.]?(\\d{0,2})\\s*€/);
                if (!imageUrl) {
                    const img = el.querySelector('img[src]');
                    if (img) imageUrl = img.src;
                }
                if (priceM && imageUrl) break;
            }
            if (!priceM) return;
            let description = null;
            for (const p of el.querySelectorAll('p, span')) {
                if (p.closest('div.notranslate')) continue;
                const t = (p.innerText || '').trim();
                if (t && t !== title && t.length > 5 && t.length < 300 && !/^\\d+[,.]?\\d*\\s*€/.test(t)) {
                    description = t;
                    break;
                }
            }
            addItem(title, parsePrice(priceM[1] + '.' + (priceM[2] || '00').padEnd(2, '0')), nearestHeading(nt), imageUrl, description);
        });
        if (out.length > 0) return out;

        // Strategy 2: data-testid
        for (const sel of ['[data-testid*="menu-item"]', '[data-testid*="product"]', '[data-test*="item"]']) {
            document.querySelectorAll(sel).forEach(el => {
                const text = (el.innerText || '').trim();
                const priceM = text.match(/€\\s*(\\d+[,.]\\d{1,2})/);
                if (!priceM) return;
                const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 1);
                const title = lines.find(l => !l.startsWith('€') && !/^\\d+[,.]?\\d*\\s*€/.test(l) && l.length > 2);
                const img = el.querySelector('img[src]');
                if (title) addItem(title, parsePrice(priceM[1]), nearestHeading(el), img ? img.src : null, null);
            });
            if (out.length > 0) return out;
        }

        // Strategy 3: li/article — skip when no notranslate divs (closed/non-food pages only yield promo banners)
        if (document.querySelectorAll('div.notranslate').length === 0) return out;
        document.querySelectorAll('li, article').forEach(el => {
            const text = (el.innerText || '').trim();
            if (text.length > 500 || text.length < 4) return;
            const priceM = text.match(/(\\d+)[,.]?(\\d{0,2})\\s*€/);
            if (!priceM) return;
            const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 1);
            const title = lines.find(l => !l.includes('€') && !/^\\d+[,.]?\\d*$/.test(l) && l.length > 2);
            const img = el.querySelector('img[src]');
            if (title) addItem(title, parsePrice(priceM[1] + '.' + (priceM[2] || '00').padEnd(2, '0')), nearestHeading(el), img ? img.src : null, null);
        });
        return out;
    }""")

    log_fn(f"  extracted {len(items)} items")

    if items:
        allergen_map: dict = await page.evaluate("""() => {
            try {
                const metas = window.__NEXT_DATA__?.props?.initialState?.menuPage?.menu?.metas;
                if (!metas) return {};
                const found = [];
                function walk(obj, depth) {
                    if (!obj || typeof obj !== 'object' || depth > 8) return;
                    if (Array.isArray(obj)) {
                        for (const el of obj) walk(el, depth + 1);
                    } else {
                        if (typeof obj.name === 'string' && Array.isArray(obj.dietaryTags) && obj.dietaryTags.length) {
                            found.push(obj);
                        }
                        for (const v of Object.values(obj)) walk(v, depth + 1);
                    }
                }
                walk(metas, 0);
                const out = {};
                for (const item of found) {
                    const tags = item.dietaryTags.map(t => t.text).filter(Boolean);
                    if (tags.length) out[item.name.toLowerCase()] = tags;
                }
                return out;
            } catch { return {}; }
        }""")
        if allergen_map:
            for item in items:
                tags = allergen_map.get(item["title"].lower())
                if tags:
                    item["allergens"] = [t.lower() for t in tags]
            log_fn(f"  allergens: {sum(1 for i in items if 'allergens' in i)}/{len(items)}")

        db.insert_menu_items(lid, items)
        log_fn(f"  saved {len(items)} items ✓")
    else:
        # Clear any stale items from previous scrapes; update last_scraped_at
        db.insert_menu_items(lid, [])
        log_fn(f"  warning: 0 items found — cleared old items, marked scraped")

    # Delivery fee
    fee_text: str | None = await page.evaluate(r"""() => {
        for (const sel of ['[data-test*="delivery"]','[data-testid*="delivery"]','[data-test*="fee"]']) {
            for (const el of document.querySelectorAll(sel)) {
                const t = (el.innerText || '').trim();
                if (/€|free|gratuit|gratis/i.test(t) && t.length < 80) return t;
            }
        }
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
            const t = node.textContent.trim();
            if (t.length > 0 && t.length < 80 &&
                /delivery|livraison|bezorgkosten/i.test(t) &&
                /€\s*\d|\d+[,.]\d+\s*€|free|gratuit|gratis/i.test(t)) return t;
        }
        return null;
    }""")
    fee = _parse_fee(fee_text)
    if fee is not None:
        db.patch_listing(lid, {"delivery_fee": fee})
        log_fn(f"  delivery fee: {fee}")

    # Min order
    min_order_text: str | None = await page.evaluate(r"""() => {
        for (const sel of ['[data-test*="minimum"]','[data-testid*="minimum"]','[data-test*="min-order"]','[data-testid*="min-order"]']) {
            for (const el of document.querySelectorAll(sel)) {
                const t = (el.innerText || '').trim();
                if (/€\s*\d|\d+[,.]\d+\s*€/i.test(t) && t.length < 80) return t;
            }
        }
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
            const t = node.textContent.trim();
            if (t.length > 0 && t.length < 80 &&
                /minimum|commande min|min\. bestelling/i.test(t) &&
                /€\s*\d|\d+[,.]\d+\s*€/.test(t)) return t;
        }
        return null;
    }""")
    if min_order_text:
        mo = extract_min_order(min_order_text)
        if mo is not None:
            db.patch_listing(lid, {"min_order": mo})
            log_fn(f"  min order: {mo}")

    # Promotions
    promo_texts: list[str] = await page.evaluate(r"""() => {
        const results = [];
        const seen = new Set();
        function add(text) {
            text = (text || '').trim();
            if (!text || text.length > 200 || seen.has(text.toLowerCase())) return;
            seen.add(text.toLowerCase());
            results.push(text);
        }
        for (const sel of ['[data-testid*="offer"]','[data-testid*="promotion"]','[data-testid*="deal"]','[data-test*="offer"]','[data-testid*="voucher"]']) {
            document.querySelectorAll(sel).forEach(el => {
                const t = (el.innerText || '').trim();
                if (t && t.length < 200) add(t);
            });
        }
        for (const el of document.querySelectorAll('[class]')) {
            const cls = (el.getAttribute('class') || '').toLowerCase();
            if (/offer|promo|deal|discount|voucher/.test(cls)) {
                const t = (el.innerText || '').trim();
                if (t && t.length < 200 && t.length > 5) add(t);
            }
        }
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
            const t = node.textContent.trim();
            if (t.length < 8 || t.length > 150) continue;
            if (/spend.{0,40}(free|get|off|gratuit)|buy \d|get \d free|free delivery|livraison (gratuite|offerte)|\d+%.{0,20}off|offert.{0,20}dès|\d+ (achet|offert)/i.test(t)) add(t);
        }
        return results;
    }""")
    if promo_texts:
        rich_promos = parse_promo_texts(promo_texts)
        if rich_promos:
            db.upsert_promotions(lid, rich_promos)
            log_fn(f"  {len(rich_promos)} promotions saved")

    return len(items)


async def main(mode: str, ids: list[str], workers: int) -> None:
    listings = _get_listings(mode, ids)
    if not listings:
        log.info("No listings found for mode=%s", mode)
        return

    log.info("Mode=%s: %d listings to scrape", mode, len(listings))
    for i, l in enumerate(listings):
        log.info("  %d. %s [%s]", i + 1, l["name"], l["id"][:8])

    total_items = 0
    errors = 0
    t0 = time.time()

    browser = await new_browser(lang="fr-BE", headed=False)
    try:
        # Slice listings across workers
        slices: list[list[dict]] = [[] for _ in range(workers)]
        for i, listing in enumerate(listings):
            slices[i % workers].append(listing)

        async def _worker(wid: int, slice_listings: list[dict]) -> tuple[int, int]:
            nonlocal total_items, errors
            page = await new_page(browser, lang="fr-BE")
            saved = 0
            errs = 0
            try:
                for j, listing in enumerate(slice_listings):
                    def _log(msg: str, _name=listing["name"]) -> None:
                        log.info("[w%d] %s", wid, msg)
                    try:
                        n = await _scrape_one(page, listing, _log)
                        saved += n
                        # Recycle page every 10 to avoid RSS leak
                        if (j + 1) % 10 == 0:
                            await page.close()
                            page = await new_page(browser, lang="fr-BE")
                    except CloudflareBlockedError as e:
                        log.warning("[w%d] Cloudflare blocked %s: %s", wid, listing["name"], e)
                        errs += 1
                    except Exception as e:
                        log.error("[w%d] Error on %s: %s", wid, listing["name"], e)
                        errs += 1
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
            return saved, errs

        results = await asyncio.gather(*[
            _worker(wid, slices[wid])
            for wid in range(workers)
            if slices[wid]
        ])

        for saved, errs in results:
            total_items += saved
            errors += errs

    finally:
        await browser.close()

    elapsed = time.time() - t0
    log.info(
        "Done in %.0fs — %d listings, %d items saved, %d errors",
        elapsed, len(listings), total_items, errors,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deliveroo targeted Phase 2 scraper")
    parser.add_argument("--mode", choices=["null", "closed", "ids"], default="null")
    parser.add_argument("--ids", help="Comma-separated listing IDs (for --mode ids)")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    ids = [i.strip() for i in args.ids.split(",")] if args.ids else []
    if args.mode == "ids" and not ids:
        print("--mode ids requires --ids")
        sys.exit(1)

    asyncio.run(main(args.mode, ids, args.workers))
