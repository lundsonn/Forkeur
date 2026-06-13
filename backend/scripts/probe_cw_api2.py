"""
Focused probe: grab __NEXT_DATA__ from restaurant page + find cw-api version/paths.
"""
import asyncio
import json
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            locale="fr-BE",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()

        # Intercept responses to cw-api
        api_calls: list[dict] = []
        async def on_response(resp):
            if "cw-api.takeaway.com" in resp.url or "bff-service" in resp.url:
                try:
                    body = await resp.body()
                    api_calls.append({
                        "url": resp.url,
                        "status": resp.status,
                        "body_preview": body[:500].decode("utf-8", errors="replace"),
                    })
                except Exception as e:
                    api_calls.append({"url": resp.url, "status": resp.status, "error": str(e)})
        page.on("response", on_response)

        # Navigate directly to a known restaurant menu page
        slug = "sensei-sushi-bruxelles"
        url = f"https://www.takeaway.com/be-fr/menu/{slug}"
        print(f"Loading {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"goto error (ignoring): {e}")

        # Wait for CF if needed
        for _ in range(20):
            title = await page.title()
            if "instant" not in title.lower() and "moment" not in title.lower():
                break
            print(f"  CF: {title}")
            await asyncio.sleep(2)

        await asyncio.sleep(4)

        # Extract __NEXT_DATA__
        nd = await page.evaluate("""
        () => {
            const s = document.getElementById('__NEXT_DATA__');
            return s ? s.textContent : null;
        }
        """)

        if nd:
            data = json.loads(nd)
            props = data.get("props", {}).get("pageProps", {})
            print(f"\n__NEXT_DATA__ pageProps keys: {list(props.keys())}")

            # Dump full structure (truncated)
            nd_str = json.dumps(props)
            print(f"Total size: {len(nd_str)} chars")

            # Search for fee/price/delivery data
            for key in ["deliveryFee", "delivery_fee", "minOrder", "min_order", "deliveryTime",
                        "priceRange", "menu", "categories", "products", "items", "restaurant"]:
                idx = nd_str.find(key)
                if idx >= 0:
                    print(f"\n  Found '{key}': ...{nd_str[max(0,idx-5):idx+200]}...")

            # Dump restaurant top-level if exists
            r = props.get("restaurant") or props.get("restaurantData")
            if r:
                print(f"\nrestaurant keys: {list(r.keys()) if isinstance(r, dict) else type(r)}")
                if isinstance(r, dict):
                    print(json.dumps(r, indent=2, default=str)[:3000])
        else:
            print("No __NEXT_DATA__")
            # Print page source snippet
            html = await page.content()
            print(f"Page length: {len(html)}")
            print(html[:2000])

        print(f"\n=== API calls intercepted: {len(api_calls)} ===")
        for c in api_calls:
            print(f"\n  {c['status']} {c['url']}")
            print(f"  body: {c.get('body_preview', c.get('error', ''))[:300]}")

        # Also search for cw-api URL patterns in JS
        print("\n=== Searching JS for API paths ===")
        all_scripts = await page.evaluate("""
        () => Array.from(document.querySelectorAll('script:not([src])'))
                  .map(s => s.textContent)
                  .join('\\n')
        """)
        for pattern in ["/api/v", "restaurants?", "/restaurant?", "postalCode", "countryCode", "cw-api"]:
            idx = all_scripts.find(pattern)
            if idx >= 0:
                print(f"  Found '{pattern}': ...{all_scripts[max(0,idx-30):idx+100]}...")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
