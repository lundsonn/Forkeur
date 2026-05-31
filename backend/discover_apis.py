"""
Run this from the server to discover API calls made by Takeaway and Deliveroo SPAs.
Output: JSON dump of all XHR/fetch responses so we can wire up API interception.

Usage:
    uv run python discover_apis.py takeaway
    uv run python discover_apis.py deliveroo
"""
from __future__ import annotations
import asyncio
import json
import sys
from scrapers.base import new_browser, new_page, wait_for_cf_clear

TAKEAWAY_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"
DELIVEROO_URL = "https://deliveroo.be/en"

_NOISE = {
    "google-analytics", "googletagmanager", "doubleclick", "facebook",
    "hotjar", "sentry", "segment", "fontawesome", "fonts.g",
    ".css", ".png", ".jpg", ".svg", ".woff", ".ico",
}

# Always capture these domains (platform data APIs)
_ALWAYS = ("jet-external.com", "takeaway.com", "deliveroo", "consumer-ow", "deliveroo-static",
           "cms-api", "just-eat")


def _is_interesting(url: str) -> bool:
    low = url.lower()
    if any(n in low for n in _NOISE):
        return False
    if any(d in low for d in _ALWAYS):
        return True
    # Capture .js only if it looks like an API (not static bundle)
    if ".js" in low and "chunk" in low:
        return False
    return any(x in low for x in ("api", "graphql", "feed", "menu", "restaurant", "query", "product"))


async def discover(site: str) -> None:
    headed = site == "takeaway"  # Takeaway needs headed for CF
    print(f"Launching {'headed' if headed else 'headless'} browser for {site}...")
    browser = await new_browser(lang="fr-BE", headed=headed)
    captured: list[dict] = []

    try:
        page = await new_page(browser, lang="fr-BE")

        async def on_response(response):
            url = response.url
            if not _is_interesting(url):
                return
            try:
                status = response.status
                ct = response.headers.get("content-type", "")
                body = ""
                if "json" in ct:
                    text = await response.text()
                    body = text[:2000]  # first 2KB only
                captured.append({"url": url, "status": status, "ct": ct, "body_preview": body})
                print(f"  [{status}] {url[:120]}")
            except Exception as e:
                print(f"  [err] {url[:80]} — {e}")

        page.on("response", on_response)

        if site == "takeaway":
            print(f"Navigating to {TAKEAWAY_URL}")
            await page.goto(TAKEAWAY_URL, wait_until="domcontentloaded", timeout=60000)
            print("Waiting for CF...")
            cleared = await wait_for_cf_clear(page, timeout_s=90)
            print(f"CF cleared: {cleared}")
            if cleared:
                print("Waiting for restaurant cards...")
                try:
                    await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
                except Exception:
                    pass

                # Dump listing-page __NEXT_DATA__
                listing_next = await page.evaluate("""() => {
                    const el = document.getElementById('__NEXT_DATA__');
                    return el ? el.textContent.slice(0, 8000) : 'NOT FOUND';
                }""")
                print(f"\n=== LISTING __NEXT_DATA__ (first 8KB) ===\n{listing_next[:3000]}\n")

                print("Scrolling...")
                for _ in range(5):
                    await page.evaluate("window.scrollBy(0, 3000)")
                    await asyncio.sleep(1)

                # Dump full __NEXT_DATA__ keys to see restaurant data structure
                listing_keys = await page.evaluate("""() => {
                    const el = document.getElementById('__NEXT_DATA__');
                    if (!el) return 'NOT FOUND';
                    try {
                        const d = JSON.parse(el.textContent);
                        // Walk top-level pageProps keys
                        const pp = d.props?.pageProps || {};
                        return JSON.stringify({
                            pagePropsKeys: Object.keys(pp),
                            restaurantSample: JSON.stringify(pp.restaurants || pp.initialRestaurants || pp.restaurantList || pp.data || {}).slice(0, 3000)
                        });
                    } catch(e) { return 'PARSE_ERROR: ' + e; }
                }""")
                print(f"\n=== LISTING pageProps keys ===\n{listing_keys}\n")

                # Try BFF API calls from within the cleared browser context
                first_slug = await page.evaluate("""() => {
                    const a = document.querySelector('a[href*="/menu/"]');
                    return a ? (a.href.match(/\\/menu\\/([^?#]+)/) || [])[1] : null;
                }""")
                if first_slug:
                    print(f"\nTrying BFF API calls from browser context for slug: {first_slug}")

                    # Intercept network to capture BFF responses
                    bff_responses: list[str] = []
                    async def capture_bff(response):
                        url = response.url
                        if "cw-api" in url or "globalmenucdn" in url or "jet-external" in url:
                            try:
                                ct = response.headers.get("content-type", "")
                                if "json" in ct:
                                    text = await response.text()
                                    bff_responses.append(f"[{response.status}] {url}\n{text[:3000]}")
                            except Exception:
                                pass
                    page.on("response", capture_bff)

                    # Probe common BFF/menu endpoints via in-browser fetch (uses CF-cleared cookies)
                    probe_result = await page.evaluate("""async (slug) => {
                        const results = {};
                        const base = 'https://cw-api.takeaway.com';

                        const urls = [
                            `/be-fr/menu/${slug}?format=json`,
                            `/api/restaurant/${slug}`,
                            `/api/v1/restaurant/${slug}/menu`,
                            `/be-fr/api/restaurants/${slug}`,
                        ];

                        for (const path of urls) {
                            try {
                                const r = await fetch(base + path, {
                                    headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
                                });
                                const text = await r.text();
                                results[path] = { status: r.status, preview: text.slice(0, 500) };
                            } catch(e) {
                                results[path] = { error: e.toString() };
                            }
                        }

                        try {
                            const r2 = await fetch(`https://globalmenucdn.eu-central-1.production.jet-external.com/${slug}`, {
                                headers: { 'Accept': 'application/json' }
                            });
                            results['menucdn'] = { status: r2.status, preview: (await r2.text()).slice(0, 500) };
                        } catch(e) {
                            results['menucdn'] = { error: e.toString() };
                        }

                        return results;
                    }""", first_slug)
                    print(f"\n=== BFF probe results ===")
                    print(json.dumps(probe_result, indent=2))
                    if bff_responses:
                        print("\n=== BFF intercepted responses ===")
                        for r in bff_responses:
                            print(r[:1000])

        elif site == "deliveroo":
            print(f"Navigating to {DELIVEROO_URL}")
            await page.goto(DELIVEROO_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(3)
            try:
                await page.click('input[id="location-search"], input[placeholder*="address" i]', timeout=5000)
                await page.type('input[id="location-search"], input[placeholder*="address" i]', "1000 Brussels", delay=60)
                await asyncio.sleep(3)
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.5)
                await page.keyboard.press("Enter")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"Address input failed: {e}")

            print("Waiting for restaurants...")
            try:
                await page.wait_for_selector('a[href*="/menu/"]', timeout=20000)
            except Exception:
                pass
            for _ in range(4):
                await page.evaluate("window.scrollBy(0, 3000)")
                await asyncio.sleep(1)

            print("\n=== Deliveroo GraphQL responses captured so far ===")
            gql_items = [r for r in captured if "graphql" in r["url"]]
            for g in gql_items:
                print(f"  {g['url']}")
                print(f"  body: {g['body_preview'][:800]}\n")

            # Navigate to first restaurant menu
            first_href = await page.evaluate("""() => {
                const a = document.querySelector('a[href*="/menu/"]');
                return a ? a.href : null;
            }""")
            if first_href:
                print(f"\nGoto menu: {first_href[:100]}")
                await page.goto(first_href, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(3)
                for _ in range(4):
                    await page.evaluate("window.scrollBy(0, 3000)")
                    await asyncio.sleep(1)

                print("\n=== Deliveroo GraphQL responses after menu nav ===")
                gql_items2 = [r for r in captured if "graphql" in r["url"]]
                for g in gql_items2:
                    print(f"  {g['url']}")
                    print(f"  body: {g['body_preview'][:2000]}\n")

                # Dump data-testid values
                tids = await page.evaluate("""() => {
                    return [...new Set(
                        Array.from(document.querySelectorAll('[data-testid]'))
                            .map(el => el.getAttribute('data-testid'))
                    )].slice(0, 60);
                }""")
                print(f"\ndata-testid values on menu page: {tids}")

                # Dump __NEXT_DATA__ from menu page
                next_data = await page.evaluate("""() => {
                    const el = document.getElementById('__NEXT_DATA__');
                    if (!el) return 'NOT FOUND';
                    try {
                        const d = JSON.parse(el.textContent);
                        const pp = d.props?.pageProps || {};
                        return JSON.stringify({
                            pagePropsKeys: Object.keys(pp),
                            sample: JSON.stringify(pp).slice(0, 8000)
                        });
                    } catch(e) { return 'PARSE_ERROR: ' + e; }
                }""")
                print(f"\n=== Deliveroo menu __NEXT_DATA__ ===\n{next_data}\n")

                # Dump structure around first menu-item-image
                item_structure = await page.evaluate("""() => {
                    const img = document.querySelector('[data-testid="menu-item-image"]');
                    if (!img) return 'NOT FOUND';
                    let el = img;
                    // Walk up to find price-bearing container
                    for (let i = 0; i < 6; i++) {
                        if (!el.parentElement) break;
                        el = el.parentElement;
                        const text = el.innerText || '';
                        if (text.match(/€/)) break;
                    }
                    return {
                        outerHTML: el.outerHTML.slice(0, 2000),
                        testids: [...el.querySelectorAll('[data-testid]')].map(e => e.getAttribute('data-testid')),
                        text: el.innerText.slice(0, 500)
                    };
                }""")
                print(f"\n=== Menu item DOM structure ===\n{json.dumps(item_structure, indent=2, ensure_ascii=False)}\n")

        print(f"\n=== Captured {len(captured)} interesting responses ===")
        out_path = f"discover_{site}.json"
        with open(out_path, "w") as f:
            json.dump(captured, f, indent=2)
        print(f"Saved to {out_path}")

        # Print URL summary
        print("\nURL patterns found:")
        for r in captured:
            print(f"  {r['url'][:120]}")

    finally:
        await browser.close()


if __name__ == "__main__":
    site = sys.argv[1] if len(sys.argv) > 1 else "takeaway"
    if site not in ("takeaway", "deliveroo"):
        print("Usage: python discover_apis.py [takeaway|deliveroo]")
        sys.exit(1)
    asyncio.run(discover(site))
