"""
Probe cw-api.takeaway.com for Belgium support.
1. Use Playwright to load takeaway.com/be → harvest cookies
2. Fire cw-api listing endpoint for Brussels (1000)
3. Fire cw-api menu endpoint for first slug returned
"""
import asyncio
import json
import httpx
from playwright.async_api import async_playwright


CW_LISTING = "https://cw-api.takeaway.com/api/v33/restaurants"
CW_MENU    = "https://cw-api.takeaway.com/api/v33/restaurant"

LISTING_PARAMS = {
    "postalCode": "1000",
    "lat": "50.8503",
    "lng": "4.3517",
    "limit": "0",
    "isAccurate": "true",
}


async def inspect_next_data() -> None:
    """Inspect __NEXT_DATA__ to find API config and restaurant slug format."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(locale="fr-BE", user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        page = await ctx.new_page()

        # 1. Listing page
        print("=== LISTING PAGE __NEXT_DATA__ ===")
        await page.goto("https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        nd = await page.evaluate("() => { const s = document.getElementById('__NEXT_DATA__'); return s ? JSON.parse(s.textContent) : null; }")
        if nd:
            props = nd.get("props", {}).get("pageProps", {})
            print(f"pageProps keys: {list(props.keys())}")
            # Look for restaurants list
            for k, v in props.items():
                if isinstance(v, list) and len(v) > 0:
                    print(f"  List key '{k}': {len(v)} items, first: {json.dumps(v[0], default=str)[:300]}")
                elif isinstance(v, dict):
                    print(f"  Dict key '{k}': {list(v.keys())[:10]}")
            # Search for API config
            nd_str = json.dumps(nd)
            for pattern in ["cw-api", "api.takeaway", "apiUrl", "baseUrl", "API_URL"]:
                idx = nd_str.find(pattern)
                if idx >= 0:
                    print(f"\nFound '{pattern}' at {idx}: ...{nd_str[max(0,idx-20):idx+100]}...")
        else:
            print("No __NEXT_DATA__ found")

        # 2. Check env vars in window
        env = await page.evaluate("() => { return window.__ENV__ || window.ENV || window._env || null; }")
        if env:
            print(f"\nwindow ENV: {json.dumps(env, default=str)[:500]}")

        # 3. Check a restaurant detail page
        print("\n\n=== RESTAURANT PAGE __NEXT_DATA__ ===")
        # Find a slug from the listing page first
        slugs = await page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a[href*="/menu/"]'));
            return links.slice(0, 3).map(a => a.href);
        }
        """)
        print(f"Found slugs/links: {slugs}")

        if slugs:
            await page.goto(slugs[0], wait_until="domcontentloaded")
            await asyncio.sleep(3)
            nd2 = await page.evaluate("() => { const s = document.getElementById('__NEXT_DATA__'); return s ? JSON.parse(s.textContent) : null; }")
            if nd2:
                props2 = nd2.get("props", {}).get("pageProps", {})
                print(f"Restaurant pageProps keys: {list(props2.keys())}")
                for k, v in props2.items():
                    if isinstance(v, dict):
                        print(f"  Dict '{k}': {list(v.keys())[:15]}")
                    elif isinstance(v, list):
                        print(f"  List '{k}': {len(v)} items")
                # Search for fee/delivery info
                nd2_str = json.dumps(nd2)
                for pattern in ["deliveryFee", "delivery_fee", "minOrder", "min_order", "cw-api", "apiUrl"]:
                    idx = nd2_str.find(pattern)
                    if idx >= 0:
                        print(f"\nFound '{pattern}': ...{nd2_str[max(0,idx-10):idx+150]}...")

        await browser.close()


async def harvest_cookies() -> tuple[dict, dict]:
    """Load takeaway.com/be-fr, wait for CF clear, return cookies + headers."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            locale="fr-BE",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
        print("Loading takeaway.com/be-fr ...")
        await page.goto("https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000", wait_until="domcontentloaded")

        # Wait for CF or page load
        for _ in range(60):
            title = await page.title()
            print(f"  title: {title!r}")
            if "instant" not in title.lower() and "moment" not in title.lower():
                break
            await asyncio.sleep(2)

        await asyncio.sleep(3)

        cookies = {c["name"]: c["value"] for c in await ctx.cookies()}
        print(f"Harvested {len(cookies)} cookies: {list(cookies.keys())}")

        # Also grab the request headers the browser sends to cw-api
        intercepted: list[dict] = []
        async def on_request(req):
            if "cw-api.takeaway.com" in req.url:
                intercepted.append({"url": req.url, "headers": dict(req.headers)})

        # Intercept ALL requests
        all_requests: list[dict] = []
        all_responses: list[dict] = []
        async def on_any_request(req):
            all_requests.append({"url": req.url, "method": req.method, "headers": dict(req.headers)})

        async def on_any_response(resp):
            url = resp.url
            if any(x in url for x in ["cw-api", "api.takeaway", "graphql", "restaurant"]):
                all_responses.append({"url": url, "status": resp.status})

        page.on("request", on_any_request)
        page.on("response", on_any_response)

        # Navigate to a restaurant page (client-side rendered → triggers API calls)
        print("Navigating to restaurant page...")
        await page.goto("https://www.takeaway.com/be-fr/menu/mcdonald-s-bruxelles", wait_until="domcontentloaded")
        await asyncio.sleep(6)

        print(f"\n=== API responses intercepted: {len(all_responses)} ===")
        for r in all_responses[:10]:
            print(f"  {r['status']} {r['url'][:120]}")

        # Also dump all unique domains from all requests
        domains = sorted(set(r["url"].split("/")[2] for r in all_requests if "://" in r["url"]))
        print(f"\nAll request domains: {domains}")

        # Look for cw-api in JS bundles
        js_urls = [r["url"] for r in all_requests if ".js" in r["url"] and "takeaway" in r["url"]]
        print(f"\nJS bundle URLs (first 5): {js_urls[:5]}")

        if intercepted:
            print(f"\n=== INTERCEPTED cw-api requests ({len(intercepted)}) ===")
            for r in intercepted[:3]:
                print(json.dumps(r, indent=2))

        await browser.close()
        return cookies, intercepted[0]["headers"] if intercepted else {}


async def probe_listing(cookies: dict, headers: dict) -> list:
    default_headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr-BE,fr;q=0.9",
        "Origin": "https://www.takeaway.com",
        "Referer": "https://www.takeaway.com/",
        "User-Agent": headers.get("user-agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"),
        "X-Country-Code": "BE",
        "X-Language-Code": "fr",
    }
    # Merge intercepted headers if we got any
    merged = {**default_headers, **{k: v for k, v in headers.items() if k.lower() not in ("host", "content-length")}}

    async with httpx.AsyncClient(cookies=cookies, headers=merged, follow_redirects=True) as client:
        print(f"\n=== GET {CW_LISTING} ===")
        r = await client.get(CW_LISTING, params=LISTING_PARAMS)
        print(f"Status: {r.status_code}")
        print(f"Content-Type: {r.headers.get('content-type')}")

        if r.status_code == 200:
            data = r.json()
            print(f"Top-level keys: {list(data.keys())}")
            restaurants = data.get("restaurants", data.get("data", []))
            print(f"Restaurant count: {len(restaurants)}")
            if restaurants:
                first = restaurants[0]
                print(f"\nFirst restaurant keys: {list(first.keys())}")
                print(json.dumps(first, indent=2, default=str)[:2000])
            return restaurants
        else:
            print(f"Body: {r.text[:500]}")
            return []


async def probe_menu(slug: str, cookies: dict, headers: dict):
    default_headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr-BE,fr;q=0.9",
        "Origin": "https://www.takeaway.com",
        "Referer": "https://www.takeaway.com/",
        "User-Agent": headers.get("user-agent", "Mozilla/5.0"),
        "X-Country-Code": "BE",
        "X-Language-Code": "fr",
    }
    merged = {**default_headers, **{k: v for k, v in headers.items() if k.lower() not in ("host", "content-length")}}

    async with httpx.AsyncClient(cookies=cookies, headers=merged, follow_redirects=True) as client:
        print(f"\n=== GET {CW_MENU}?slug={slug} ===")
        r = await client.get(CW_MENU, params={"slug": slug})
        print(f"Status: {r.status_code}")

        if r.status_code == 200:
            data = r.json()
            print(f"Top-level keys: {list(data.keys())}")
            # Show categories/menu structure
            categories = data.get("categories", data.get("menus", []))
            print(f"Category count: {len(categories)}")
            if categories:
                cat = categories[0]
                print(f"\nFirst category: {json.dumps(cat, indent=2, default=str)[:1500]}")
        else:
            print(f"Body: {r.text[:500]}")


async def main():
    await inspect_next_data()
    return

    cookies, headers = await harvest_cookies()

    restaurants = await probe_listing(cookies, headers)

    if restaurants:
        # Try first slug
        first = restaurants[0]
        slug = first.get("slug") or first.get("primarySlug") or first.get("id")
        if slug:
            print(f"\nProbing menu for slug: {slug!r}")
            await probe_menu(slug, cookies, headers)
        else:
            print(f"\nNo slug found in: {list(first.keys())}")
    else:
        print("\nNo restaurants returned — API may not support BE or needs different params")


if __name__ == "__main__":
    asyncio.run(main())
