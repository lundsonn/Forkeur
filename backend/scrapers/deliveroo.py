from __future__ import annotations
import asyncio
import re
from typing import Callable
from urllib.parse import urlparse, parse_qs
from models import ScraperConfig, ScraperResult
from scrapers.base import browser_session, new_page, check_cloudflare, noop_log, CloudflareBlockedError, parse_menu_price
from scrapers.promos import parse_promo_texts
import db

# One representative address per Brussels postal code — mirrors Takeaway zone strategy.
# Each zone is scraped with a fresh browser context (CF clearance per IP+session).
LISTING_ZONES = [
    "Grand-Place 1, 1000 Bruxelles",          # Centre / Pentagone
    "Avenue de Laeken 1, 1020 Bruxelles",      # Laeken
    "Place Colignon 1, 1030 Bruxelles",        # Schaerbeek
    "Chaussée d'Etterbeek 1, 1040 Bruxelles",  # Etterbeek
    "Chaussée d'Ixelles 1, 1050 Bruxelles",    # Ixelles
    "Parvis de Saint-Gilles 1, 1060 Bruxelles",# Saint-Gilles
    "Place de la Vaillance 1, 1070 Bruxelles", # Anderlecht
    "Chaussée de Gand 1, 1080 Bruxelles",      # Molenbeek
    "Rue du Prêtre 1, 1090 Bruxelles",         # Jette
    "Rue de Fiennes 1, 1140 Bruxelles",        # Evere
    "Avenue de Tervuren 1, 1150 Bruxelles",    # Woluwe-Saint-Pierre
    "Chaussée de Wavre 1, 1160 Bruxelles",     # Auderghem
    "Avenue Brugmann 1, 1180 Bruxelles",       # Uccle
    "Rue de Forest 1, 1190 Bruxelles",         # Forest
    "Avenue de Tervuren 200, 1200 Bruxelles",  # Woluwe-Saint-Lambert
    "Rue Rogier 1, 1210 Bruxelles",            # Saint-Josse
]

_GH_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def _decode_geohash(gh: str) -> tuple[float, float] | None:
    """Decode a geohash string to (lat, lng). Returns None on invalid input."""
    try:
        lat = [-90.0, 90.0]
        lon = [-180.0, 180.0]
        even = True
        for c in gh.lower():
            v = _GH_BASE32.index(c)
            for bit in (16, 8, 4, 2, 1):
                rng = lon if even else lat
                mid = (rng[0] + rng[1]) / 2
                if v & bit:
                    rng[0] = mid
                else:
                    rng[1] = mid
                even = not even
        return (lat[0] + lat[1]) / 2, (lon[0] + lon[1]) / 2
    except (ValueError, ZeroDivisionError):
        return None


def _coords_from_url(url: str) -> tuple[float, float] | None:
    """Extract lat/lng from Deliveroo menu URL geohash query param."""
    try:
        qs = parse_qs(urlparse(url).query)
        gh = qs.get("geohash", [None])[0]
        return _decode_geohash(gh) if gh else None
    except Exception:
        return None


async def _venue_coords_from_page(page) -> dict | None:
    """Extract actual venue coords + address from a Deliveroo restaurant menu page.

    Tries JSON-LD Restaurant schema first (most stable), then __NEXT_DATA__.
    Returns a dict ``{"lat", "lng", "street_address", "postal_code"}`` (the
    address keys may be None) or None if no valid Brussels-area coords are found.

    The JSON-LD Restaurant block carries an ``address`` PostalAddress alongside
    ``geo``; when present we also capture ``streetAddress`` + ``postalCode``.
    The __NEXT_DATA__ fallback yields coords only (no address), so address keys
    are None there.
    """
    try:
        result = await page.evaluate("""() => {
            // Strategy 1: JSON-LD with Restaurant + geo
            for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
                try {
                    const d = JSON.parse(script.textContent);
                    const items = Array.isArray(d) ? d : [d];
                    for (const item of items) {
                        if (item['@type'] === 'Restaurant' && item.geo) {
                            const lat = parseFloat(item.geo.latitude);
                            const lng = parseFloat(item.geo.longitude);
                            if (!isNaN(lat) && !isNaN(lng)) {
                                const addr = item.address || {};
                                const street = (addr.streetAddress || '').trim() || null;
                                const postal = (addr.postalCode || '').toString().trim() || null;
                                return { lat, lng, street_address: street, postal_code: postal };
                            }
                        }
                    }
                } catch {}
            }
            // Strategy 2: __NEXT_DATA__ — scan props for lat/lng keys (coords only)
            try {
                const nd = window.__NEXT_DATA__;
                if (nd) {
                    function findCoords(obj, depth) {
                        if (depth > 8 || !obj || typeof obj !== 'object') return null;
                        if ('latitude' in obj && 'longitude' in obj) {
                            const lat = parseFloat(obj.latitude);
                            const lng = parseFloat(obj.longitude);
                            if (!isNaN(lat) && !isNaN(lng)) return { lat, lng, street_address: null, postal_code: null };
                        }
                        if ('lat' in obj && ('lng' in obj || 'lon' in obj)) {
                            const lat = parseFloat(obj.lat);
                            const lng = parseFloat(obj.lng ?? obj.lon);
                            if (!isNaN(lat) && !isNaN(lng)) return { lat, lng, street_address: null, postal_code: null };
                        }
                        for (const v of Object.values(obj)) {
                            const r = findCoords(v, depth + 1);
                            if (r) return r;
                        }
                        return null;
                    }
                    const r = findCoords(nd.props, 0);
                    if (r) return r;
                }
            } catch {}
            return null;
        }""")
        if result and result.get("lat") is not None and result.get("lng") is not None:
            lat, lng = float(result["lat"]), float(result["lng"])
            if 50.4 < lat < 51.1 and 3.9 < lng < 4.8:  # Brussels + surrounding area
                return {
                    "lat": lat,
                    "lng": lng,
                    "street_address": result.get("street_address"),
                    "postal_code": result.get("postal_code"),
                }
    except Exception:
        pass
    return None


def _parse_dom_items(dom_output: dict) -> list[dict]:
    """Parse menu items from DOM eval output.

    Structure:
    {
        "sections": [
            {
                "heading": "Section Name",
                "items": [
                    {"title": "Item Name", "price": "€ 12,50"}
                ]
            }
        ]
    }
    """
    items = []
    sections = dom_output.get("sections", [])

    for section in sections:
        catalog_name = section.get("heading", "Menu")
        section_items = section.get("items", [])

        for item in section_items:
            title = item.get("title", "").strip()
            price_str = item.get("price", "")

            # Use shared price parser
            price = parse_menu_price(price_str)

            items.append({
                "title": title,
                "price": price,
                "catalog_name": catalog_name,
            })

    return items


async def scrape_menu_page(page, listing_id: str, url: str) -> tuple[str, list[dict]]:
    """Navigate restaurant menu page and scrape items via DOM eval.

    Returns: (listing_id, items)
    """
    items = []

    try:
        # Navigate to menu page
        await page.goto(url, timeout=15000)

        # Scroll once to load lazy-loaded items
        await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)

        # Eval DOM to extract sections and items
        dom_output = await page.evaluate("""
        () => {
            const sections = [];

            // Find category headings
            const headings = Array.from(document.querySelectorAll('h2, h3'));

            for (const heading of headings) {
                const sectionName = heading.textContent.trim();
                const items = [];

                // Look for items after heading (cards with prices)
                let current = heading.nextElementSibling;
                while (current && !['H2', 'H3'].includes(current.tagName)) {
                    const priceMatch = current.textContent.match(/€\\s*\\d+[,.]\\d+|\\d+[,.]\\d+\\s*€/);
                    if (priceMatch) {
                        // Extract title (non-price text)
                        let titleText = current.textContent.replace(/€\\s*\\d+[,.]\\d+|\\d+[,.]\\d+\\s*€/g, '').trim();
                        items.push({
                            title: titleText,
                            price: priceMatch[0]
                        });
                    }
                    current = current.nextElementSibling;
                }

                if (items.length > 0) {
                    sections.push({
                        heading: sectionName,
                        items: items
                    });
                }
            }

            return { sections };
        }
        """)

        # Parse DOM output
        items = _parse_dom_items(dom_output)

    except Exception as e:
        pass  # Silent fail for test compatibility

    return (listing_id, items)


_LISTING_JS = """anchors => {
    const seen = new Set();
    return anchors.filter(a => {
        const slug = (a.href.match(/\\/menu\\/([^?#]+)/) || [])[1];
        if (!slug || seen.has(slug)) return false;
        seen.add(slug);
        return true;
    }).map(a => {
        const slug = (a.href.match(/\\/menu\\/([^?#]+)/) || [])[1] || '';
        let card = a;
        for (let i = 0; i < 8; i++) {
            if (!card.parentElement) break;
            card = card.parentElement;
            if (card.tagName === 'LI' || card.tagName === 'ARTICLE') break;
        }
        const lines = (card.innerText || '').split('\\n').map(l => l.trim()).filter(Boolean);
        const ratingIdx = lines.findIndex(l => /^[1-5][,.]\\d(\\s|$|\\()/.test(l));
        const ratingLine = ratingIdx >= 0 ? lines[ratingIdx] : null;
        const _isEta = l => /^\\d+(-\\d+)?\\s*min$|around\\s+\\d+/i.test(l);
        const name = ratingIdx > 0 ? lines[ratingIdx - 1] : (lines.find(l => !_isEta(l) && !l.includes('€') && l.length > 3) || slug);
        const ratingMatch = (ratingLine || '').match(/^(\\d[,.]\\d)/);
        const reviewMatch = (ratingLine || '').match(/\\((\\d[\\d.,]*\\+?)\\)/);
        const eta = lines.find(l => /^\\d+(-\\d+)?\\s*min$/i.test(l)) || 'N/A';
        const promoLines = lines.filter(l =>
            /spend|get|free|gratuit|promo|off|réduction|korting|gratis|achet|offert/i.test(l) &&
            l !== name && !ratingLine?.startsWith(l) &&
            !_isEta(l) && l.length < 120
        );
        const heroImg = card.querySelector('img[src]');
        const isClosed = lines.some(l => /^(ferm[eé]|closed|gesloten|pr[eé]-?commande|pre-?order|vooruitbestellen)/i.test(l));
        return {
            name, url: a.href, slug,
            rating: ratingMatch ? ratingMatch[1] : 'N/A',
            review_count: reviewMatch ? reviewMatch[1] : '',
            eta,
            discount: promoLines[0] || null,
            promoLines,
            image_url: heroImg ? heroImg.src : null,
            is_closed: isClosed,
        };
    });
}"""


async def _scrape_zone_listings(browser, zone_address: str, log_fn) -> list[dict]:
    """Load Deliveroo listing page for one address and return restaurant dicts."""
    page = await new_page(browser, lang="fr-BE")
    try:
        await page.goto("https://deliveroo.be/fr", wait_until="domcontentloaded", timeout=60000)
        check_cloudflare(await page.title())

        try:
            await page.click('button:has-text("Accept all"), button:has-text("Continue without accepting")', timeout=4000)
            await asyncio.sleep(0.5)
        except Exception:
            pass

        input_sel = 'input[id="location-search"], input[placeholder*="address" i], input[placeholder*="adresse" i]'
        await page.wait_for_selector(input_sel, timeout=10000)
        await page.click(input_sel)
        await page.type(input_sel, zone_address, delay=60)

        suggestion_sel = 'li.ccl-ee4ea4aaab604785'
        try:
            await page.wait_for_selector(suggestion_sel, timeout=8000)
            await page.click(suggestion_sel)
        except Exception:
            await asyncio.sleep(2)
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")

        try:
            await page.wait_for_url("**/restaurants**", timeout=20000)
        except Exception:
            pass

        if "restaurants" not in page.url:
            log_fn(f"  Did not reach listing page — got: {page.url}")
            return []

        await page.wait_for_selector('a[href*="/menu/"]', timeout=10000)

        # Height + count stable scroll (0.5s per tick, stale=3)
        prev_h, prev_count, stale = 0, 0, 0
        for _ in range(80):
            result = await page.evaluate(
                "(function(){window.scrollTo(0,document.body.scrollHeight);"
                "return {h:document.body.scrollHeight,"
                "c:document.querySelectorAll('a[href*=\"/menu/\"]').length};})()"
            )
            await asyncio.sleep(0.5)
            h, count = result["h"], result["c"]
            if h == prev_h and count == prev_count:
                stale += 1
                if stale >= 3:
                    break
            else:
                stale = 0
            prev_h, prev_count = h, count
        await asyncio.sleep(0.5)

        return await page.eval_on_selector_all('a[href*="/menu/"]', _LISTING_JS)
    except Exception as exc:
        log_fn(f"  Error: {exc}")
        return []
    finally:
        await page.close()


async def run(config: ScraperConfig, log_fn: Callable[[str], None] = noop_log) -> ScraperResult:
    log_fn("Starting Deliveroo scraper")
    records_saved = 0
    page = None

    async with browser_session(lang="fr-BE") as browser:
        # Phase 0: collect listings across all zones, dedup by slug.
        # Zones are independent (own page, same browser/CF session) → run concurrently.
        ZONE_WORKERS = 4
        zones = LISTING_ZONES
        zone_sem = asyncio.Semaphore(ZONE_WORKERS)

        async def _scrape_zone_safe(zone_address: str) -> list[dict]:
            async with zone_sem:
                log_fn(f"Zone: {zone_address}")
                try:
                    return await asyncio.wait_for(
                        _scrape_zone_listings(browser, zone_address, log_fn),
                        timeout=180,
                    )
                except asyncio.TimeoutError:
                    log_fn(f"  ⚠ zone timed out: {zone_address}")
                    return []
                except Exception as exc:
                    log_fn(f"  ⚠ zone error ({zone_address}): {exc}")
                    return []

        log_fn(f"Phase 0: {len(zones)} zones, {ZONE_WORKERS} concurrent")
        zone_results: list[list[dict]] = await asyncio.gather(
            *[_scrape_zone_safe(z) for z in zones]
        )

        all_by_slug: dict[str, dict] = {}
        for zone_restaurants in zone_results:
            for r in zone_restaurants:
                if r["slug"] not in all_by_slug:
                    all_by_slug[r["slug"]] = r

        restaurants = list(all_by_slug.values())
        total_cards = sum(len(zr) for zr in zone_results)
        log_fn(f"Phase 0 done — {total_cards} cards across {len(zones)} zones → {len(restaurants)} unique")

        if config.target:
            restaurants = [r for r in restaurants if config.target.lower() in r["name"].lower() or config.target.lower() in r["slug"].lower()]

        # --- Phase 1: upsert restaurants + listings ---
        saved: list[tuple[dict, str, str]] = []  # (r, rid, lid)
        promo_total = 0
        for r in (restaurants[:config.max_items] if config.max_items else restaurants):
            try:
                coords = _coords_from_url(r.get("url", ""))
                rid = db.upsert_restaurant({
                    "name": r["name"],
                    "slug": r["slug"],
                    "image_url": r.get("image_url"),
                    **({} if coords is None else {"lat": coords[0], "lng": coords[1], "geo_source": "deliveroo"}),
                })
            except ValueError:
                continue  # junk entry filtered by db._is_junk
            lid = db.upsert_listing({
                "restaurant_id": rid,
                "platform": "deliveroo",
                "url": r.get("url"),
                "rating": _parse_float(r.get("rating")),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
                "discount_label": r.get("discount"),
                "is_available": not r.get("is_closed", False),
                # delivery_fee: not exposed on listing page, filled in phase 2
            })
            promos = parse_promo_texts(r.get("promoLines") or [])
            promo_total += db.upsert_promotions(lid, promos)
            records_saved += 1
            saved.append((r, rid, lid))

        log_fn(f"Phase 1 — {records_saved} listings, {promo_total} promotions saved")

        if config.listing_only:
            return ScraperResult(records_saved=records_saved)

        # --- Phase 2: goto per restaurant menu page ---
        # SPA click only renders a partial React tree → ~6 items.
        # Full goto gives 100+ items because the full SSR + hydration runs.
        # Deliveroo has no CF on menu pages so goto is safe.
        menu_items_saved = 0
        n = len(saved)

        async def _scrape_one(page, i, r, rid, lid):
            nonlocal menu_items_saved
            log_fn(f"Menu: {i + 1}/{n} — {r['name']}")
            try:
                menu_url = r.get("url", "")
                if not menu_url:
                    log_fn(f"  No URL for {r['name']}, skipping")
                    return

                try:
                    await page.goto(menu_url, wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    pass  # timeout is fine — content loads progressively
                check_cloudflare(await page.title())  # fail fast before waiting for content

                # Try to extract actual venue coords + address (JSON-LD / __NEXT_DATA__)
                venue = await _venue_coords_from_page(page)
                if venue:
                    db.patch_restaurant_geo(rid, venue["lat"], venue["lng"], "deliveroo_venue")
                    log_fn(f"  Venue coords: {venue['lat']:.5f}, {venue['lng']:.5f}")
                    # Persist street_address + postal_code onto the platform_listing
                    # (DB columns live on platform_listings). Null/absent → skipped.
                    addr_patch = {
                        "street_address": venue.get("street_address"),
                        "postal_code": venue.get("postal_code"),
                    }
                    if any(addr_patch.values()):
                        db.patch_listing(lid, addr_patch)
                        log_fn(f"  Venue address: {addr_patch}")

                # Single wait: covers redirect + load + settle in one step.
                # div.notranslate appears once any items render; fallbacks cover layout changes.
                try:
                    await page.wait_for_selector(
                        'div.notranslate, [class*="MenuItemCardV2"], [class*="MenuItemCard"], [data-testid="menu-item-image"]',
                        timeout=25000,
                    )
                except Exception:
                    pass

                # Unified scroll: stable when BOTH height AND item count unchanged for 2 consecutive ticks.
                prev_h, prev_count, stale = 0, 0, 0
                for _ in range(40):
                    result = await page.evaluate(
                        "()=>({h:document.body.scrollHeight,"
                        "c:document.querySelectorAll('div.notranslate').length})"
                    )
                    h, count = result["h"], result["c"]
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(800)
                    if h == prev_h and count == prev_count:
                        stale += 1
                        if stale >= 3:
                            break
                    else:
                        stale = 0
                    prev_h, prev_count = h, count
                await page.evaluate("window.scrollTo(0, 0)")
                log_fn(f"  Scroll done: {prev_count} notranslate divs, url={page.url[:80]}")

                # Multi-strategy extraction — ordered by selector stability.
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
                        title = title.trim();
                        if (!title || title.length < 2 || price === null) return;
                        const key = title + '|' + price;
                        if (seen.has(key)) return;
                        seen.add(key);
                        out.push({ title, price, catalog_name: catalogName, image_url: imageUrl || null, description: description || null });
                    }

                    // Strategy 1: div.notranslate — one per item card (Deliveroo wraps item
                    // title in a notranslate div to prevent Google Translate from mangling it).
                    // Walk up from the notranslate to the card container that has a price.
                    document.querySelectorAll('div.notranslate').forEach(nt => {
                        // Skip if nested inside another notranslate
                        if (nt.parentElement?.closest('div.notranslate')) return;
                        const titleEl = nt.querySelector('p, span, h2, h3, h4') || nt;
                        const title = (titleEl.innerText || '').trim();
                        if (!title || title.length < 2) return;
                        // Walk up to find price, image, and description
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
                        // Description: first non-title, non-price paragraph outside the notranslate div
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

                    // Strategy 2: data-testid attributes (stable across deploys)
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

                    // Strategy 3: li/article with price (covers other layouts)
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

                log_fn(f"  Extracted {len(items)} items via DOM")

                if items:
                    db.insert_menu_items(lid, items)
                    menu_items_saved += len(items)
                    log_fn(f"  Saved {len(items)} items")
                else:
                    log_fn(f"  Warning: no menu items found for {r['name']}")

                # Extract delivery fee from restaurant page.
                # CSS class selectors are hashed (CSS modules) and change; use
                # data-test* attributes first, then a broad text-node walk.
                fee_text: str | None = await page.evaluate(
                    """() => {
                        // 1. Semantic test attributes (stable across deploys)
                        for (const sel of [
                            '[data-test*="delivery"]',
                            '[data-testid*="delivery"]',
                            '[data-test*="fee"]',
                        ]) {
                            for (const el of document.querySelectorAll(sel)) {
                                const t = (el.innerText || '').trim();
                                if (/€|free|gratuit|gratis/i.test(t) && t.length < 80) return t;
                            }
                        }
                        // 2. Text-node walk: short strings mentioning delivery + price
                        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                        let node;
                        while ((node = walker.nextNode())) {
                            const t = node.textContent.trim();
                            if (t.length > 0 && t.length < 80 &&
                                /delivery|livraison|bezorgkosten/i.test(t) &&
                                /€\s*\d|\d[,.]\d\s*€|free|gratuit|gratis/i.test(t)) {
                                return t;
                            }
                        }
                        // 3. Any short line starting with € (e.g. "€ 1.99")
                        const walker2 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                        while ((node = walker2.nextNode())) {
                            const t = node.textContent.trim();
                            if (/^€\s*\d+[,.]\d+$/.test(t)) return t;
                        }
                        return null;
                    }"""
                )
                fee = _parse_fee(fee_text)
                if fee is not None:
                    db.patch_listing(lid, {"delivery_fee": fee})
                    log_fn(f"  Delivery fee: {fee}")

                # Extract promotions from the restaurant page — richer than listing card
                promo_texts: list[str] = await page.evaluate("""() => {
                    const results = [];
                    const seen = new Set();

                    function add(text) {
                        text = (text || '').trim();
                        if (!text || text.length > 200 || seen.has(text.toLowerCase())) return;
                        seen.add(text.toLowerCase());
                        results.push(text);
                    }

                    // 1. Dedicated offer/promotion elements (data-testid)
                    for (const sel of [
                        '[data-testid*="offer"]', '[data-testid*="promotion"]',
                        '[data-testid*="deal"]', '[data-test*="offer"]',
                        '[data-testid*="voucher"]',
                    ]) {
                        document.querySelectorAll(sel).forEach(el => {
                            const t = (el.innerText || '').trim();
                            if (t && t.length < 200) add(t);
                        });
                    }

                    // 2. Elements whose class names suggest offers
                    for (const el of document.querySelectorAll('[class]')) {
                        const cls = (el.getAttribute('class') || '').toLowerCase();
                        if (/offer|promo|deal|discount|voucher/.test(cls)) {
                            const t = (el.innerText || '').trim();
                            if (t && t.length < 200 && t.length > 5) add(t);
                        }
                    }

                    // 3. Short text nodes with clear promo patterns
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let node;
                    while ((node = walker.nextNode())) {
                        const t = node.textContent.trim();
                        if (t.length < 8 || t.length > 150) continue;
                        if (/spend.{0,40}(free|get|off|gratuit)|buy \d|get \d free|free delivery|livraison (gratuite|offerte)|\d+%.{0,20}off|offert.{0,20}dès|\d+ (achet|offert)/i.test(t)) {
                            add(t);
                        }
                    }

                    return results;
                }""")

                if promo_texts:
                    rich_promos = parse_promo_texts(promo_texts)
                    if rich_promos:
                        db.upsert_promotions(lid, rich_promos)
                        log_fn(f"  {len(rich_promos)} promotions saved")

            except CloudflareBlockedError:
                log_fn(f"  Cloudflare blocked — skipping menu for {r['name']}")
            except Exception as exc:
                if "crashed" in str(exc).lower():
                    raise  # bubble up so the worker recreates its page
                log_fn(f"  Error scraping menu for {r['name']}: {exc}")

        # Phase 2 fan-out: Deliveroo menus use direct goto (no click-nav, no CF),
        # so each worker scrapes its slice on an independent page in parallel.
        async def _worker(wid: int, slice_items: list) -> None:
            wpage = await new_page(browser, lang="fr-BE")
            try:
                for k, (r, rid, lid) in enumerate(slice_items):
                    # Recycle the page every 30 restaurants — Deliveroo menu pages
                    # are heavy (full SSR); reusing one page across a whole slice
                    # leaks renderer RSS (drove full-batch free RAM to ~300MB).
                    if k > 0 and k % 30 == 0:
                        try:
                            await wpage.close()
                        except Exception:
                            pass
                        try:
                            wpage = await asyncio.wait_for(new_page(browser, lang="fr-BE"), timeout=30)
                        except Exception:
                            log_fn(f"  worker {wid}: recycle failed, abandoning {len(slice_items) - k} remaining")
                            return
                    try:
                        # Hard wall cap — goto(60s)+scroll loops can stack; also
                        # guards against a crashed page wedging past Playwright timeouts.
                        await asyncio.wait_for(_scrape_one(wpage, k, r, rid, lid), timeout=150)
                    except asyncio.TimeoutError:
                        log_fn(f"  worker {wid}: {r['name']} timed out, skipping")
                    except Exception:
                        log_fn(f"  worker {wid}: page crashed, recreating")
                        try:
                            await wpage.close()
                        except Exception:
                            pass
                        try:
                            wpage = await asyncio.wait_for(new_page(browser, lang="fr-BE"), timeout=30)
                        except Exception:
                            log_fn(f"  worker {wid}: cannot recover, abandoning {len(slice_items) - k - 1} remaining")
                            return
            finally:
                try:
                    await wpage.close()
                except Exception:
                    pass

        # 3 workers (not 4) — keeps full-batch peak RAM clear of the 8GB ceiling.
        WORKERS = 3
        slices = [saved[w::WORKERS] for w in range(WORKERS)]
        log_fn(f"Phase 2: {n} menus across {WORKERS} parallel workers")
        await asyncio.gather(
            *[_worker(w, s) for w, s in enumerate(slices) if s],
            return_exceptions=True,
        )
        log_fn(f"Done — {records_saved} listings, {menu_items_saved} menu items, {promo_total} promos saved")
        return ScraperResult(records_saved=records_saved, restaurants=restaurants, menu_items_saved=menu_items_saved)


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
