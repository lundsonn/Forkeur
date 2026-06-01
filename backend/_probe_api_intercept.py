"""
Intercept XHR/fetch on listing + menu page to find JET internal API endpoints.
Once found, we can call them directly with session cookies — no CF on menu pages.
"""
import asyncio
import json
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"

captured_listing = []
captured_menu = []
responses = {}


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")

        def on_req(req):
            u = req.url
            if req.resource_type in ("xhr", "fetch") and "cloudflare" not in u and "cdn-cgi" not in u:
                captured_listing.append((req.method, u))

        page.on("request", on_req)

        print("Loading listing + clearing CF...", flush=True)
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        await asyncio.sleep(3)

        print(f"\n=== LISTING XHR ({len(captured_listing)}) ===", flush=True)
        for method, u in captured_listing:
            print(f"  {method} {u}", flush=True)

        # Extract cookies + headers for direct API calls
        cookies = await page.context.cookies()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        print(f"\nSession cookies ({len(cookies)} total): {cookie_str[:200]}...", flush=True)

        # Now SPA click to first restaurant and capture menu XHR
        first_href = await page.evaluate("""() => {
            const a = document.querySelector('[data-qa="restaurant-card"] a[href*="/menu/"]');
            return a ? a.getAttribute('href') : null;
        }""")
        print(f"\nClicking menu: {first_href}", flush=True)

        menu_captured = []

        async def on_menu_req(req):
            u = req.url
            if req.resource_type in ("xhr", "fetch") and "cloudflare" not in u and "cdn-cgi" not in u:
                menu_captured.append((req.method, u, req.post_data or ""))

        async def on_menu_resp(resp):
            u = resp.url
            if any(k in u for k in ("jet-external", "takeaway.com/api", "api.", "restaurants", "menu")):
                try:
                    body = await resp.text()
                    responses[u] = body[:500]
                except Exception:
                    pass

        page.on("request", on_menu_req)
        page.on("response", on_menu_resp)

        await page.evaluate(f"""() => {{
            const a = document.querySelector('a[href="{first_href}"]');
            if (a) a.click();
        }}""")

        # Wait up to 30s for menu XHR to fire (CF may delay)
        for _ in range(30):
            await asyncio.sleep(1)
            if menu_captured:
                break

        print(f"\n=== MENU XHR ({len(menu_captured)}) ===", flush=True)
        for method, u, body in menu_captured:
            print(f"  {method} {u}", flush=True)
            if body:
                print(f"    body: {body[:100]}", flush=True)

        print(f"\n=== RESPONSE BODIES (API endpoints) ===", flush=True)
        for u, body in responses.items():
            print(f"\n  URL: {u}", flush=True)
            print(f"  BODY: {body[:300]}", flush=True)

        # Try direct API call with session cookies
        print("\n=== TRYING DIRECT JET API ===", flush=True)
        slug = first_href.split("/menu/")[-1].rstrip("/") if first_href else ""
        api_urls = [
            f"https://cw-api.takeaway.com/api/v33/restaurant?slug={slug}&language=fr",
            f"https://rest.api.eu-central-1.production.jet-external.com/restaurants/{slug}/menu",
            f"https://www.takeaway.com/be-fr/api/v5/restaurants/{slug}/menu",
        ]
        import urllib.request
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Cookie": cookie_str,
            "Accept": "application/json",
            "x-requested-with": "XMLHttpRequest",
        }
        for url in api_urls:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as r:
                    body = r.read().decode()[:300]
                    print(f"  ✓ {url}\n    {body}\n", flush=True)
            except Exception as e:
                print(f"  ✗ {url} → {e}", flush=True)

    finally:
        await browser.close()


asyncio.run(main())
