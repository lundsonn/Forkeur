"""Website finder scraper.

For each restaurant row that has no website yet, searches Google Maps,
extracts the external website link, then visits the site to detect online
ordering capability.

Usage (standalone):
    uv run python find_websites.py [--limit N]

Usage (from FastAPI):
    from scrapers.website_finder import run
    await run(log_fn, limit=10)
"""
from __future__ import annotations

import asyncio
import re
from typing import Callable
from urllib.parse import quote_plus, urlparse

import db
from scrapers.base import new_browser, new_page, is_safe_url

_SKIP_DOMAINS = {
    "facebook", "instagram", "twitter", "youtube", "wikipedia",
    "tripadvisor", "ubereats", "deliveroo", "takeaway", "linkedin",
    "yelp", "thefork", "lafourchette", "zomato", "just-eat",
}

_ORDER_URL_PATTERNS = [
    r"/order", r"/commande", r"/bestellen", r"/menu",
    r"wixrestaurants", r"lightspeedrestaurant", r"livepepper",
    r"obypay", r"eatsup", r"orderbird", r"flipdish", r"deliveryheroes",
    r"ordering\.website", r"bopple\.com", r"square\.site",
    r"restolution", r"tabletop\.at",
]

_ORDER_HOSTNAMES = {
    "wixrestaurants", "lightspeedrestaurant", "livepepper", "obypay",
    "eatsup", "orderbird", "flipdish", "deliveryheroes", "bopple",
    "square", "restolution", "tabletop",
}

_ORDER_KEYWORDS = [
    "livraison", "livré", "commander", "commande", "à domicile",
    "chez vous", "commandez", "nous livrons",
    "delivery", "deliver", "order online", "order now", "we deliver",
    "home delivery", "free delivery",
    "bezorging", "bezorgen", "bestellen", "thuisbezorging", "wij bezorgen",
    "commandez par téléphone", "order by phone", "appelez",
    "bestellen per telefoon", "téléphone",
]

import re as _re
_PHONE_RE = _re.compile(r"(?:\+32|0032|0)[\s.\-]?[1-9][\s.\-]?(?:[0-9][\s.\-]?){7,8}")

_ORDER_LINK_RE = re.compile(
    r"\b(order|commande[rz]?|bestel|bestelling)\b", re.IGNORECASE
)


def _is_order_url(url: str) -> bool:
    lower = url.lower()
    parsed = urlparse(lower)
    hostname = parsed.netloc

    if any(pat in hostname for pat in _ORDER_HOSTNAMES):
        return True
    if any(re.search(pat, lower) for pat in _ORDER_URL_PATTERNS):
        return True
    return False


def _looks_like_order_link(href: str, text: str) -> bool:
    if _is_order_url(href):
        return True
    if _ORDER_LINK_RE.search(text):
        return True
    return False


async def _accept_google_cookies(page) -> None:
    selectors = [
        'button[aria-label*="Accept"]',
        'button[aria-label*="Akzeptieren"]',
        'button[aria-label*="Accepter"]',
        'button:has-text("Accept all")',
        'button:has-text("Tout accepter")',
        'button:has-text("Alle akzeptieren")',
        'button:has-text("Accepter tout")',
    ]
    for selector in selectors:
        try:
            btn = page.locator(selector)
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_timeout(2000)
                return
        except Exception:
            pass


_COORDS_RE = re.compile(r"/@(-?\d+\.\d+),(-?\d+\.\d+)")


async def _find_website_on_maps(
    page, restaurant_name: str, log: Callable
) -> tuple[str | None, bool, float | None, float | None]:
    """Navigate to Google Maps and return (website_url, has_delivery, lat, lng)."""
    url = f"https://www.google.com/maps/search/{quote_plus(restaurant_name + ' Brussels')}"
    try:
        await page.goto(url, timeout=30_000)
        await page.wait_for_timeout(3_000)
    except Exception as e:
        log(f"    Maps navigation failed: {e}")
        return None, False, None, None

    lat: float | None = None
    lng: float | None = None
    m = _COORDS_RE.search(page.url)
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))

    try:
        result = await page.evaluate("""() => {
            const links = Array.from(document.querySelectorAll('a[href]'))
                .filter(a => a.href.startsWith('http') && !a.href.includes('google'))
                .map(a => a.href.split('?')[0]);
            const text = document.body.innerText.toLowerCase();
            const hasDelivery = /delivery|livraison|bezorg|lieferung/.test(text);
            return {links, hasDelivery};
        }""")
    except Exception as e:
        log(f"    Failed to evaluate Maps page: {e}")
        return None, False, lat, lng

    links = result.get("links", [])
    has_delivery = result.get("hasDelivery", False)

    website = next(
        (
            link for link in links
            if not any(skip in link.lower() for skip in _SKIP_DOMAINS)
        ),
        None,
    )
    return website, has_delivery, lat, lng


async def _detect_ordering(page, website_url: str, log: Callable) -> str | None:
    if not is_safe_url(website_url):
        log(f"    skipped unsafe URL: {website_url[:60]}")
        return None

    if _is_order_url(website_url):
        return website_url

    text = await _fetch_text_httpx(website_url, log)

    if text is None:
        try:
            await page.goto(website_url, timeout=20_000)
            await page.wait_for_timeout(2_000)
            final_url = page.url
            if _is_order_url(final_url):
                return final_url
            text = await page.evaluate("() => document.body?.innerText || ''")
        except Exception as e:
            log(f"    Could not load website ({e})")
            return None

    body_lower = (text or "").lower()

    if any(kw in body_lower for kw in _ORDER_KEYWORDS):
        order_link = await _find_order_link(page, website_url)
        return order_link or website_url

    has_phone = bool(_PHONE_RE.search(body_lower))
    has_delivery_hint = any(w in body_lower for w in ("livr", "deliver", "bezorg", "bestell"))
    if has_phone and has_delivery_hint:
        return website_url

    return None


async def _fetch_text_httpx(url: str, log: Callable) -> str | None:
    try:
        import httpx
        import html as _html
        import re as _re2
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
            "Accept": "text/html",
            "Accept-Language": "fr-BE,fr;q=0.9,nl;q=0.8,en;q=0.7",
        }
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            r = await client.get(url, headers=headers)
            if r.status_code < 400:
                raw = r.text
                text = _re2.sub(r"<[^>]+>", " ", raw)
                return _html.unescape(text)
    except Exception as e:
        log(f"    httpx fetch failed: {e}")
    return None


async def _find_order_link(page, base_url: str) -> str | None:
    try:
        anchors: list[dict] = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a[href]'))
                .map(a => ({href: a.href || '', text: a.innerText || ''}))
                .filter(a => a.href.startsWith('http'));
        }""")
    except Exception:
        return None

    for anchor in anchors:
        href = anchor.get("href", "")
        text = anchor.get("text", "")
        if _looks_like_order_link(href, text):
            return href.split("?")[0] or None
    return None


_JUNK_RE = re.compile(
    r"[𐀀-􏿿]|"
    r"[☀-➿]|"
    r"\d+\s*%|"
    r"à partir de|moitié prix|half price|"
    r"% off|% de réduction|korting|rabais",
    re.IGNORECASE,
)


def _is_junk_name(name: str) -> bool:
    clean = name.strip()
    if len(clean) < 4:
        return True
    if _JUNK_RE.search(clean):
        return True
    return False


_CONCURRENCY = 4


async def _worker(
    worker_id: int,
    queue: asyncio.Queue,
    total: int,
    browser,
    log: Callable,
    counters: dict,
    lock: asyncio.Lock,
) -> None:
    page = await new_page(browser)
    try:
        await page.goto("https://www.google.com/maps", timeout=30_000)
        await page.wait_for_timeout(1_500)
        await _accept_google_cookies(page)
        log(f"[worker-{worker_id}] ready")

        while True:
            try:
                idx, row = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            rid = row["id"]
            name = row["name"]
            log(f"[website_finder] [{idx}/{total}] {name}")

            try:
                if _is_junk_name(name):
                    log(f"    [{worker_id}] Skipping junk name")
                    db.mark_restaurant_searched(rid)
                    async with lock:
                        counters["processed"] += 1
                    queue.task_done()
                    continue

                website, maps_has_delivery, lat, lng = await _find_website_on_maps(page, name, log)

                if lat is not None and lng is not None:
                    db.get_client().table("restaurants").update({"lat": lat, "lng": lng}).eq("id", rid).execute()

                if not website:
                    db.mark_restaurant_searched(rid)
                    async with lock:
                        counters["processed"] += 1
                    await asyncio.sleep(1)
                    queue.task_done()
                    continue

                log(f"    [{worker_id}] Website: {website} (maps_delivery={maps_has_delivery})")
                async with lock:
                    counters["websites_found"] += 1

                if maps_has_delivery:
                    order_url = website
                    async with lock:
                        counters["orders_found"] += 1
                else:
                    order_url = await _detect_ordering(page, website, log)
                    if order_url:
                        async with lock:
                            counters["orders_found"] += 1

                db.patch_restaurant_website(rid, website, order_url)
                async with lock:
                    counters["processed"] += 1

                await asyncio.sleep(1)
            except Exception as e:
                log(f"    [{worker_id}] error on {name}: {e}")
                db.mark_restaurant_searched(rid)
                async with lock:
                    counters["processed"] += 1
            finally:
                queue.task_done()
    finally:
        await page.close()


async def run(
    log: Callable[[str], None] | None = None,
    limit: int | None = None,
    concurrency: int = _CONCURRENCY,
) -> dict:
    """Find websites and detect online ordering for restaurants that have none yet."""
    if log is None:
        log = print

    client = db.get_client()
    query = (
        client.table("restaurants")
        .select("id, name")
        .is_("website_searched_at", "null")
        .order("name")
    )
    if limit is not None:
        query = query.limit(limit)

    rows: list[dict] = query.execute().data
    total = len(rows)
    log(f"[website_finder] {total} restaurants to process (concurrency={concurrency})")

    counters = {"processed": 0, "websites_found": 0, "orders_found": 0}
    lock = asyncio.Lock()

    queue: asyncio.Queue = asyncio.Queue()
    for i, row in enumerate(rows, 1):
        queue.put_nowait((i, row))

    browser = await new_browser(headed=False)
    try:
        workers = [
            asyncio.create_task(
                _worker(i, queue, total, browser, log, counters, lock)
            )
            for i in range(min(concurrency, total or 1))
        ]
        await asyncio.gather(*workers)
    finally:
        await browser.close()

    summary = {
        "processed": counters["processed"],
        "websites_found": counters["websites_found"],
        "orders_found": counters["orders_found"],
    }
    log(f"[website_finder] Done: {summary}")
    return summary
