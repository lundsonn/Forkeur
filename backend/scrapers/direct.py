"""
Direct-delivery scraper.

Two phases:
1. Enrich: for each restaurant in DB with a website, detect direct ordering + phone.
2. Discover: search Google Maps for Brussels restaurants with delivery, upsert new ones.
"""
from __future__ import annotations
import asyncio
import re
from typing import Callable
import httpx
from models import ScraperResult
from scrapers.base import browser_session, new_page, noop_log
from scrapers.direct_classify import classify_url, is_junk_url
import db

# ── Belgian phone regex (mobile + landline) ───────────────────────────────────
_PHONE_RE = re.compile(
    r'(?<!\d)(\+32|0032|\b0)[1-9][\d\s\.\-]{6,11}(?!\d)'
)

# ── Ordering platform URLs we recognise as "direct" (not aggregators) ─────────
_ORDER_PLATFORM_RE = re.compile(
    r'order\.lightspeedrestaurant\.com'
    r'|yummyfood\.be'
    r'|orderyoyo\.'
    r'|clickeat\.be'
    r'|app\.orda\.io'
    r'|order\.me/'
    r'|orderingstack\.'
    r'|shopify\.com/.*order'
    r'|wixrestaurants\.com',
    re.IGNORECASE,
)

_AGGREGATOR_RE = re.compile(
    r'ubereats\.com|deliveroo\.|takeaway\.com|just-eat\.|thuisbezorgd\.',
    re.IGNORECASE,
)

_DELIVERY_KEYWORDS = [
    'livraison à domicile', 'commander en ligne', 'commandez en ligne',
    'order online', 'online ordering', 'bestel online', 'thuis bezorgen',
    'online bestellen', 'livraison gratuite', 'frais de livraison',
    'home delivery', 'deliver to your door',
]

# Neighborhoods to search on Google Maps
_BRUSSELS_AREAS = [
    'Bruxelles centre', 'Ixelles', 'Etterbeek', 'Schaerbeek',
    'Molenbeek', 'Uccle', 'Anderlecht', 'Forest',
]

_CUISINE_SEARCHES = [
    'restaurant livraison', 'pizza livraison', 'sushi livraison',
    'burger livraison', 'indien livraison', 'thaï livraison',
    'japonais livraison', 'chinois livraison', 'mexicain livraison',
]


def _validate_order_url(url: str) -> bool:
    """Return False for ordering-platform URLs that lack a restaurant-specific identifier.

    Prevents generic SPA base paths (e.g. sq-menu.com/ordering/restaurant/menu
    without a code) from being stored — they look like ordering links but
    contain no restaurant identity and can never be scraped.
    """
    from urllib.parse import urlparse
    lower = url.lower()
    parts = [p for p in urlparse(url).path.split('/') if p]

    if 'sq-menu.com' in lower or 'foodbooking.com' in lower:
        return len(parts) >= 3 and parts[0] == 'api'

    if 'odoo.com' in lower and 'pos-self' in lower:
        pos_i = next((i for i, p in enumerate(parts) if p == 'pos-self'), -1)
        return pos_i >= 0 and pos_i + 1 < len(parts) and parts[pos_i + 1].isdigit()

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_phone(raw: str) -> str | None:
    digits = re.sub(r'\D', '', raw)
    if digits.startswith('0032'):
        digits = '32' + digits[4:]
    elif digits.startswith('0') and len(digits) == 10:
        digits = '32' + digits[1:]
    if digits.startswith('32') and len(digits) in (10, 11):
        return f'+{digits}'
    return None


def _extract_phone(text: str) -> str | None:
    for m in _PHONE_RE.finditer(text):
        phone = _normalize_phone(m.group())
        if phone:
            return phone
    return None


def _make_slug(name: str) -> str:
    s = name.lower()
    s = re.sub(r'[àáâãä]', 'a', s)
    s = re.sub(r'[èéêë]', 'e', s)
    s = re.sub(r'[ìíîï]', 'i', s)
    s = re.sub(r'[òóôõö]', 'o', s)
    s = re.sub(r'[ùúûü]', 'u', s)
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')[:60]


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — enrich existing restaurants
# ─────────────────────────────────────────────────────────────────────────────

async def _check_website(page, url: str, log: Callable) -> dict:
    """Load a restaurant website and detect direct ordering + phone number."""
    out: dict = {'phone': None, 'order_url': None, 'has_delivery': False}
    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=18000)
        await asyncio.sleep(0.8)
    except Exception as e:
        log(f"    ✗ load error {url[:60]}: {e}")
        return out

    try:
        text = await page.inner_text('body')
    except Exception:
        text = ''

    out['phone'] = _extract_phone(text)

    # Collect all hrefs — SVG <a> elements return SVGAnimatedString dicts, filter those out
    try:
        raw_links = await page.eval_on_selector_all(
            'a[href]', 'els => els.map(e => e.href).filter(Boolean)'
        )
        links: list[str] = [l for l in raw_links if isinstance(l, str)]
    except Exception:
        links = []

    # Priority: known ordering platform URL
    for link in links:
        if _AGGREGATOR_RE.search(link):
            continue
        if _ORDER_PLATFORM_RE.search(link) and _validate_order_url(link):
            out['order_url'] = link
            out['has_delivery'] = True
            return out

    # Fallback: delivery keywords in page text
    text_lower = text.lower()
    if any(kw in text_lower for kw in _DELIVERY_KEYWORDS):
        out['has_delivery'] = True
        for link in links:
            if _AGGREGATOR_RE.search(link):
                continue
            lw = link.lower()
            if any(kw in lw for kw in ['order', 'commande', 'bestel', 'livraison', 'delivery']):
                if _validate_order_url(link):
                    out['order_url'] = link
                    break

    return out


async def _enrich_existing(browser, log: Callable) -> int:
    """Check DB restaurants with websites that have no direct listing yet."""
    supabase = db.get_client()

    # Only fetch restaurants with no existing direct listing — skip already-done ones
    already_done = {
        row['restaurant_id']
        for row in (
            supabase.table('platform_listings')
            .select('restaurant_id')
            .eq('platform', 'direct')
            .execute()
        ).data
    }

    all_restaurants = (
        supabase.table('restaurants')
        .select('id, name, website, phone')
        .not_.is_('website', 'null')
        .neq('website', '')
        .execute()
    ).data

    restaurants = [r for r in all_restaurants if r['id'] not in already_done]
    log(f"Phase 1: {len(restaurants)} restaurants to check (skipped {len(already_done)} already enriched)")

    if not restaurants:
        return 0

    saved = 0
    sem = asyncio.Semaphore(5)

    async def _process(r: dict) -> int:
        async with sem:
            page = await new_page(browser)
            try:
                analysis = await _check_website(page, r['website'], log)
            finally:
                await page.close()

            if analysis['phone'] and not r.get('phone'):
                supabase.table('restaurants').update(
                    {'phone': analysis['phone']}
                ).eq('id', r['id']).execute()

            if not (analysis['has_delivery'] or analysis['order_url']):
                return 0

            order_url = analysis['order_url'] or r['website']
            if is_junk_url(order_url):
                return 0

            row = {
                'restaurant_id': r['id'],
                'platform': 'direct',
                'url': order_url,
                'url_type': classify_url(order_url, analysis['phone']),
                'is_available': True,
            }
            supabase.table('platform_listings').insert(row).execute()
            log(f"  ✓ {r['name']}: {order_url[:70]}")
            return 1

    results = await asyncio.gather(*[_process(r) for r in restaurants], return_exceptions=True)
    for res in results:
        if isinstance(res, int):
            saved += res
        elif isinstance(res, Exception):
            log(f"  ✗ worker error: {res}")

    return saved


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Google Maps discovery
# ─────────────────────────────────────────────────────────────────────────────

async def _maps_search(page, query: str, log: Callable) -> list[dict]:
    """Run one Google Maps search and return restaurant stubs."""
    url = (
        f"https://www.google.com/maps/search/{query.replace(' ', '+')}/"
        "@50.8503,4.3517,13z?hl=fr"
    )
    results: list[dict] = []
    seen: set[str] = set()

    try:
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)

        feed = await page.query_selector('[role="feed"]')
        if not feed:
            log(f"    No feed for: {query}")
            return results

        # Scroll to load ~60 results
        for _ in range(8):
            await feed.evaluate('el => el.scrollBy(0, 900)')
            await asyncio.sleep(1.2)

        # Each place card is an <a> linking to /maps/place/
        cards = await page.query_selector_all('a[href*="/maps/place/"]')
        for card in cards:
            try:
                aria = (await card.get_attribute('aria-label') or '').strip()
                href = (await card.get_attribute('href') or '').strip()
                if aria and aria not in seen:
                    seen.add(aria)
                    results.append({'name': aria, 'maps_url': href})
            except Exception:
                continue

    except Exception as e:
        log(f"    Maps error ({query}): {e}")

    return results


async def _get_place_details(page, maps_url: str) -> dict:
    """Open a Maps place URL and extract phone + website."""
    out: dict = {'phone': None, 'website': None}
    try:
        await page.goto(maps_url, wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(2)

        # Phone
        text = ''
        main = await page.query_selector('[role="main"]')
        if main:
            text = await main.inner_text()
        out['phone'] = _extract_phone(text)

        # Website link — Google Maps uses data-item-id="authority"
        website_el = await page.query_selector('a[data-item-id="authority"]')
        if website_el:
            out['website'] = await website_el.get_attribute('href')

    except Exception:
        pass
    return out


async def _discover_maps(page, log: Callable) -> int:
    """Search Google Maps for Brussels restaurants, upsert new ones."""
    supabase = db.get_client()

    all_stubs: list[dict] = []
    seen_names: set[str] = set()

    for area in _BRUSSELS_AREAS:
        for cuisine in _CUISINE_SEARCHES:
            query = f"{cuisine} {area}"
            log(f"  Maps: {query}")
            stubs = await _maps_search(page, query, log)
            for s in stubs:
                if s['name'] not in seen_names:
                    seen_names.add(s['name'])
                    s['neighborhood'] = area  # tag with the search area for upsert below
                    all_stubs.append(s)
            await asyncio.sleep(2)

    log(f"Phase 2: {len(all_stubs)} unique restaurants found on Maps")

    saved = 0
    # Only fetch details for the first 150 to keep run time reasonable
    for stub in all_stubs[:300]:
        if stub.get('maps_url'):
            details = await _get_place_details(page, stub['maps_url'])
            stub.update(details)
            await asyncio.sleep(1)

        name = stub['name']
        try:
            rest_id = db.upsert_restaurant({
                'name': name,
                'slug': _make_slug(name),
                'website': stub.get('website'),
                'neighborhood': stub.get('neighborhood', 'Bruxelles'),
            })

            if stub.get('phone'):
                supabase.table('restaurants').update(
                    {'phone': stub['phone']}
                ).eq('id', rest_id).execute()

            # Create a direct listing — even without confirmed ordering URL,
            # having a phone / website is already useful to the user.
            has_channel = stub.get('website') or stub.get('phone')
            if not has_channel:
                continue

            existing = (
                supabase.table('platform_listings')
                .select('id')
                .eq('restaurant_id', rest_id)
                .eq('platform', 'direct')
                .execute()
            ).data

            website_url = stub.get('website')
            if is_junk_url(website_url):
                continue
            row = {
                'restaurant_id': rest_id,
                'platform': 'direct',
                'url': website_url,
                'url_type': classify_url(website_url, stub.get('phone')),
                'is_available': True,
            }

            if not existing:
                supabase.table('platform_listings').insert(row).execute()
                saved += 1
                log(f"  + {name}")

        except Exception as e:
            log(f"  ✗ {name}: {e}")

    return saved


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — reverse-geocode missing neighborhoods via Nominatim
# ─────────────────────────────────────────────────────────────────────────────

def _clean_commune(name: str | None) -> str | None:
    """Strip Dutch half from bilingual Brussels commune names (e.g. 'Ixelles - Elsene' → 'Ixelles')."""
    if not name:
        return None
    return name.split(' - ')[0].strip()


async def _enrich_neighborhoods(log: Callable) -> None:
    """Reverse-geocode restaurants with null neighborhood using Nominatim (max 1 req/s)."""
    supabase = db.get_client()
    rows = (
        supabase.table('restaurants')
        .select('id, lat, lng')
        .is_('neighborhood', 'null')
        .not_.is_('lat', 'null')
        .execute()
    ).data

    log(f"Phase 3: {len(rows)} restaurants to geocode")
    updated = 0

    async with httpx.AsyncClient(
        headers={'User-Agent': 'Forkeur/1.0 (geraud.marion@gmail.com)'},
        timeout=10,
    ) as client:
        for row in rows:
            try:
                r = await client.get(
                    'https://nominatim.openstreetmap.org/reverse',
                    params={'lat': row['lat'], 'lon': row['lng'], 'format': 'json', 'accept-language': 'fr'},
                )
                addr = r.json().get('address', {})
                hood = _clean_commune(
                    addr.get('city_district') or addr.get('suburb') or addr.get('municipality')
                )
                if hood:
                    supabase.table('restaurants').update({'neighborhood': hood}).eq('id', row['id']).execute()
                    updated += 1
            except Exception:
                pass
            await asyncio.sleep(1.1)  # Nominatim rate limit: max 1 req/s

    log(f"  geocoded {updated} neighborhoods")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

async def run(config=None, log: Callable = noop_log) -> ScraperResult:
    """Run all three phases: enrich existing, discover new, geocode neighborhoods."""
    saved = 0
    async with browser_session(headed=False) as browser:
        saved += await _enrich_existing(browser, log)
        page = await new_page(browser)
        saved += await _discover_maps(page, log)
        await page.close()

    await _enrich_neighborhoods(log)

    log(f"\nDone — {saved} new direct listings saved")
    return ScraperResult(records_saved=saved)
