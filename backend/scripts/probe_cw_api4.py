"""
Find deliveryAreaId for Brussels + try cw-api with it.
Also try citymeal.com XML-RPC API with countryCode=BE.
"""
import asyncio
import json
import hashlib
import httpx
from playwright.async_api import async_playwright


async def find_delivery_area_ids():
    """Extract deliveryAreaId from page HTML/JSON-LD for Brussels zones."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            locale="fr-BE",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()
        print("Loading listing page...")
        await page.goto("https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000", wait_until="domcontentloaded", timeout=30000)

        # CF check
        for _ in range(20):
            title = await page.title()
            if "instant" not in title.lower() and "moment" not in title.lower():
                break
            await asyncio.sleep(2)
        await asyncio.sleep(3)

        # Extract all text content looking for area IDs
        data = await page.evaluate("""
        () => {
            const result = {};

            // Get full page HTML for analysis
            result.htmlLen = document.body.innerHTML.length;

            // Search for deliveryAreaId in scripts
            const scripts = Array.from(document.querySelectorAll('script'));
            const patterns = ['deliveryAreaId', 'areaId', 'area_id', 'postalCode', '"1000"', 'bruxelles'];
            for (const pat of patterns) {
                for (const s of scripts) {
                    const t = s.textContent || '';
                    const idx = t.indexOf(pat);
                    if (idx >= 0) {
                        result[pat] = t.slice(Math.max(0, idx-30), idx+150);
                        break;
                    }
                }
            }

            // Get all data attributes on restaurant cards
            const cards = Array.from(document.querySelectorAll('[data-qa="card-element"], [data-restaurant-id], [data-id]'));
            result.cardCount = cards.length;
            result.cardAttrs = cards.slice(0, 2).map(c => {
                const attrs = {};
                for (const a of c.attributes) attrs[a.name] = a.value;
                return attrs;
            });

            return result;
        }
        """)
        print(json.dumps(data, indent=2, default=str)[:3000])

        # Get full HTML snippet around "Area" or "area"
        html = await page.content()
        for pattern in ["deliveryAreaId", "areaId", "area_id", "\"c_id\"", "restaurantId"]:
            idx = html.find(pattern)
            if idx >= 0:
                print(f"\nFound '{pattern}' in HTML: ...{html[max(0,idx-20):idx+200]}...")

        cookies = {c["name"]: c["value"] for c in await ctx.cookies()}
        await browser.close()
        return cookies


def citymeal_sign(params: list[str]) -> str:
    """MD5 sign: concat all params + '4ndro1d'."""
    raw = "".join(params) + "4ndro1d"
    return hashlib.md5(raw.encode()).hexdigest()


async def probe_citymeal():
    """Try citymeal.com XML-RPC API with countryCode=BE."""
    print("\n=== Probing citymeal.com XML-RPC API ===")

    # getrestaurants(postalCode, countryCode, lat, lon, language, version)
    method = "getrestaurants"
    postal_code = "1000"
    country_code = "BE"
    lat = "50.8503"
    lon = "4.3517"
    language = "fr"

    params = [method, postal_code, country_code, lat, lon, language]
    sig = citymeal_sign(params)

    data = {
        "var0": sig,
        "var1": method,
        "var2": postal_code,
        "var3": country_code,
        "var4": lat,
        "var5": lon,
        "var6": language,
    }

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Takeaway.com/9.0.0 (Android 13)",
    }

    for base_url in [
        "https://citymeal.com/android/android.php",
        "https://be.citymeal.com/android/android.php",
        "https://nl.citymeal.com/android/android.php",  # try NL to verify signing works
    ]:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            try:
                r = await client.post(base_url, data=data, timeout=15)
                print(f"\n{r.status_code} {base_url}")
                print(f"  Content-Type: {r.headers.get('content-type', 'unknown')}")
                print(f"  Body: {r.text[:400]}")
            except Exception as e:
                print(f"\nERR {base_url}: {e}")


async def probe_cw_api_with_cookies(cookies: dict):
    """Try cw-api with different headers that might unlock BE."""
    print("\n=== Probing cw-api with BE cookies ===")

    # Try different Accept-Language and X-Country headers
    variants = [
        {"X-Country-Code": "BE", "Accept-Language": "fr-BE,fr;q=0.9"},
        {"X-Country-Code": "be", "Accept-Language": "fr-BE,fr;q=0.9"},
        {"X-Country-Code": "BE", "Accept-Language": "nl-BE,nl;q=0.9"},
        {"X-Country-Code": "NL", "Accept-Language": "nl-NL,nl;q=0.9"},  # try NL to verify
    ]

    params_variants = [
        {"postalCode": "1000", "lat": "50.8503", "lng": "4.3517", "limit": "0", "isAccurate": "true"},
        {"deliveryAreaId": "bruxelles-1000", "limit": "0"},
        {"deliveryAreaId": "1000", "limit": "0"},
    ]

    async with httpx.AsyncClient(cookies=cookies, follow_redirects=True) as client:
        for h in variants[:2]:  # don't spam
            for p in params_variants[:2]:
                headers = {
                    "Accept": "application/json",
                    "Origin": "https://www.takeaway.com",
                    "Referer": "https://www.takeaway.com/",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    **h,
                }
                r = await client.get(
                    "https://cw-api.takeaway.com/api/v33/restaurants",
                    params=p, headers=headers, timeout=10
                )
                print(f"  {r.status_code} {h.get('X-Country-Code')} {list(p.keys())}: {r.text[:100]}")


async def main():
    cookies = await find_delivery_area_ids()
    await probe_citymeal()
    await probe_cw_api_with_cookies(cookies)


if __name__ == "__main__":
    asyncio.run(main())
