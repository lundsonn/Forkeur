"""
Monkey-patch window.fetch + XHR in browser to log all API calls.
Also try cart/checkout flow which might trigger client-side API calls.
"""
import asyncio
import json
from playwright.async_api import async_playwright

FETCH_INTERCEPT = """
window.__apiCalls = [];
const origFetch = window.fetch;
window.fetch = function(url, opts) {
    window.__apiCalls.push({type: 'fetch', url: String(url), method: (opts||{}).method||'GET'});
    return origFetch.apply(this, arguments);
};
const origXHR = window.XMLHttpRequest.prototype.open;
window.XMLHttpRequest.prototype.open = function(method, url) {
    window.__apiCalls.push({type: 'xhr', url: String(url), method: method});
    return origXHR.apply(this, arguments);
};
"""

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            locale="fr-BE",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()

        # Inject intercept before every navigation
        await ctx.add_init_script(FETCH_INTERCEPT)

        # Also capture network-level responses
        api_responses: list[dict] = []
        async def on_response(resp):
            if any(x in resp.url for x in ["cw-api", "bff-service", "tkwy", "takeaway.com/api", "api/v"]):
                try:
                    body = await resp.body()
                    api_responses.append({
                        "url": resp.url,
                        "status": resp.status,
                        "ct": resp.headers.get("content-type", ""),
                        "body": body[:600].decode("utf-8", errors="replace"),
                    })
                except Exception as e:
                    api_responses.append({"url": resp.url, "status": resp.status, "err": str(e)})
        page.on("response", on_response)

        # 1. Load listing page
        print("Loading listing page...")
        await page.goto("https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000", wait_until="domcontentloaded", timeout=30000)

        # CF check
        for _ in range(20):
            title = await page.title()
            if "instant" not in title.lower() and "moment" not in title.lower():
                break
            await asyncio.sleep(2)

        await asyncio.sleep(5)

        calls = await page.evaluate("() => window.__apiCalls || []")
        print(f"fetch/XHR calls on listing page: {len(calls)}")
        for c in calls[:10]:
            print(f"  {c['method']} {c['url']}")

        # 2. Load restaurant page
        print("\nLoading restaurant page...")
        await page.goto("https://www.takeaway.com/be-fr/menu/sensei-sushi-bruxelles", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        calls2 = await page.evaluate("() => window.__apiCalls || []")
        print(f"fetch/XHR calls on restaurant page: {len(calls2)}")
        for c in calls2:
            print(f"  {c['method']} {c['url'][:120]}")

        # 3. Try clicking "add to cart" to trigger API calls
        try:
            btn = await page.wait_for_selector("[data-qa='product-add-button'], button[data-testid*='add']", timeout=5000)
            if btn:
                print("\nClicking add-to-cart...")
                await btn.click()
                await asyncio.sleep(3)
                calls3 = await page.evaluate("() => window.__apiCalls || []")
                print(f"fetch/XHR calls after add-to-cart: {len(calls3)}")
                for c in calls3:
                    if c not in calls2:
                        print(f"  NEW: {c['method']} {c['url'][:120]}")
        except Exception as e:
            print(f"No add-to-cart button: {e}")

        print(f"\n=== Network API responses: {len(api_responses)} ===")
        for r in api_responses:
            print(f"\n  {r['status']} {r['url'][:120]}")
            print(f"  {r.get('body', r.get('err', ''))[:200]}")

        # 4. Extract the full config from __NEXT_DATA__ or window
        config_js = """
        () => {
            // Try to find the config object in React/Next internals
            const configs = [];

            // Search inline scripts for bffServiceUrl
            for (const s of document.querySelectorAll('script:not([src])')) {
                const t = s.textContent;
                if (t.includes('bffServiceUrl')) {
                    const m = t.match(/"bffServiceUrl[^"]*":"([^"]+)"/g);
                    if (m) configs.push(...m);
                }
                if (t.includes('/api/v')) {
                    const m = t.match(/\/api\/v\d+\/[a-z]+/g);
                    if (m) configs.push(...m);
                }
            }
            return configs;
        }
        """
        config = await page.evaluate(config_js)
        print(f"\n=== Config strings found: ===")
        for c in set(config):
            print(f"  {c}")

        # 5. Try the Next.js API routes (server actions)
        cookies = {c["name"]: c["value"] for c in await ctx.cookies()}
        print(f"\nCookies: {list(cookies.keys())}")

        await browser.close()

        # 6. Now try cw-api with harvested cookies
        import httpx
        headers = {
            "Accept": "application/json",
            "Accept-Language": "fr-BE,fr;q=0.9",
            "Origin": "https://www.takeaway.com",
            "Referer": "https://www.takeaway.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "X-Country-Code": "BE",
            "X-Language-Code": "fr",
        }
        # Try paths that are actually in the BFF spec
        paths_to_try = [
            ("/api/v33/restaurants", {"postalCode": "1000", "lat": "50.8503", "lng": "4.3517", "limit": "0"}),
            ("/api/v33/restaurant", {"slug": "sensei-sushi-bruxelles"}),
            ("/api/v32/restaurants", {"postalCode": "1000"}),
            ("/api/v1/restaurants", {"postalCode": "1000"}),
            ("/v33/restaurants", {"postalCode": "1000"}),
            ("/restaurants", {"postalCode": "1000", "countryCode": "BE"}),
        ]
        print("\n=== Testing cw-api paths with browser cookies ===")
        async with httpx.AsyncClient(cookies=cookies, headers=headers, follow_redirects=True) as client:
            for path, params in paths_to_try:
                r = await client.get(f"https://cw-api.takeaway.com{path}", params=params, timeout=10)
                print(f"  {r.status_code} {path}: {r.text[:100]}")


if __name__ == "__main__":
    asyncio.run(main())
