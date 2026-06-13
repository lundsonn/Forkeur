"""
Use curl_cffi (Chrome TLS fingerprint) + CF cookies from Playwright to probe cw-api.
Version: 34 (confirmed from __NEXT_DATA__)
"""
import asyncio
import json
from playwright.async_api import async_playwright
from curl_cffi import requests as cf_requests

VERSION = "34"
POSTCODE = "1000"
BASE_URL = f"https://cw-api.takeaway.com/discovery/{VERSION}/restaurants/enriched/bypostcode/{POSTCODE}"


async def get_cf_cookies():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            locale="fr-BE",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()
        print("Loading takeaway.com to get CF cookies...")
        await page.goto(
            "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000",
            wait_until="domcontentloaded",
            timeout=45000,
        )
        for _ in range(20):
            title = await page.title()
            if "moment" not in title.lower() and "instant" not in title.lower():
                break
            await asyncio.sleep(2)
        await asyncio.sleep(6)

        cookies = await ctx.cookies()
        await browser.close()
        return cookies


def probe_with_curl_cffi(cookies):
    # Build cookie dict for curl_cffi
    cookie_dict = {c["name"]: c["value"] for c in cookies if "takeaway" in c.get("domain", "")}
    print(f"Using cookies: {list(cookie_dict.keys())}")

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
        "X-Country-Code": "BE",
        "X-Language-Code": "fr",
        "Referer": "https://www.takeaway.com/",
        "Origin": "https://www.takeaway.com",
    }

    params = {"serviceType": "delivery"}

    print(f"\nPROBE (curl_cffi chrome124): GET {BASE_URL}")
    r = cf_requests.get(
        BASE_URL,
        headers=headers,
        cookies=cookie_dict,
        params=params,
        impersonate="chrome124",
        timeout=20,
    )
    print(f"  → {r.status_code} {r.headers.get('content-type', '')}")
    print(f"  body[:800]: {r.text[:800]}")

    if r.status_code == 200:
        print("\n*** SUCCESS! ***")
        with open("/tmp/cw_api_success.json", "w") as f:
            f.write(r.text)
        print("Saved to /tmp/cw_api_success.json")
        try:
            data = r.json()
            if isinstance(data, list):
                print(f"Restaurant count: {len(data)}")
                if data:
                    first = data[0]
                    print(f"First restaurant keys: {list(first.keys()) if isinstance(first, dict) else type(first)}")
                    print(f"First restaurant: {json.dumps(first, indent=2)[:600]}")
            elif isinstance(data, dict):
                print(f"Keys: {list(data.keys())}")
                # Look for restaurants array
                for k, v in data.items():
                    if isinstance(v, list) and len(v) > 0:
                        print(f"  [{k}]: {len(v)} items, first keys: {list(v[0].keys()) if isinstance(v[0], dict) else type(v[0])}")
        except Exception as e:
            print(f"JSON parse error: {e}")

    return r.status_code, r.text


async def main():
    cookies = await get_cf_cookies()
    print(f"Got {len(cookies)} cookies")

    status, body = probe_with_curl_cffi(cookies)

    if status != 200:
        # Also try without cookies (maybe curl_cffi fingerprint alone is enough)
        print("\n=== Retry without cookies (fingerprint only) ===")
        r2 = cf_requests.get(
            BASE_URL,
            headers={
                "Accept": "application/json",
                "Accept-Language": "fr-BE",
                "X-Country-Code": "BE",
                "X-Language-Code": "fr",
            },
            params={"serviceType": "delivery"},
            impersonate="chrome124",
            timeout=20,
        )
        print(f"  → {r2.status_code}")
        print(f"  body[:400]: {r2.text[:400]}")

        # Also try chrome110
        print("\n=== Retry with chrome110 impersonation ===")
        r3 = cf_requests.get(
            BASE_URL,
            headers={
                "Accept": "application/json",
                "Accept-Language": "fr-BE",
                "X-Country-Code": "BE",
                "X-Language-Code": "fr",
            },
            params={"serviceType": "delivery"},
            impersonate="chrome110",
            timeout=20,
        )
        print(f"  → {r3.status_code}")
        print(f"  body[:400]: {r3.text[:400]}")


if __name__ == "__main__":
    asyncio.run(main())
