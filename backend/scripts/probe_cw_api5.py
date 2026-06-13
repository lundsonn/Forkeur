"""
Extract bffServiceVersionDefault from __NEXT_DATA__ on takeaway.com/be listing page,
then probe cw-api.takeaway.com/discovery/{version}/restaurants/enriched/bypostcode/1000.
"""
import asyncio
import json
import re
import httpx
from playwright.async_api import async_playwright

BASE = "https://cw-api.takeaway.com"
POSTCODE = "1000"

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8",
    "X-Country-Code": "BE",
    "X-Language-Code": "fr",
    "Referer": "https://www.takeaway.com/",
    "Origin": "https://www.takeaway.com",
}

async def get_page_config():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            locale="fr-BE",
            user_agent=HEADERS_BASE["User-Agent"],
        )
        page = await ctx.new_page()

        cookies_from_page = []
        version_found = None

        async def on_response(resp):
            nonlocal version_found
            url = resp.url
            if "cw-api.takeaway.com" in url:
                print(f"  [BROWSER XHR] {resp.status} {url[:120]}")
                # Extract version from URL
                m = re.search(r'/discovery/([^/]+)/restaurants', url)
                if m:
                    version_found = m.group(1)
                    print(f"  *** VERSION FROM XHR: {version_found}")

        page.on("response", on_response)

        print("Loading listing page...")
        await page.goto(
            "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000",
            wait_until="domcontentloaded",
            timeout=45000,
        )

        # CF bypass
        for i in range(20):
            title = await page.title()
            if "moment" not in title.lower() and "instant" not in title.lower():
                break
            print(f"  CF wait {i}...")
            await asyncio.sleep(2)

        await asyncio.sleep(8)
        title = await page.title()
        print(f"Page title: {title}")

        # Extract __NEXT_DATA__
        next_data_raw = await page.evaluate("""
            () => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? el.textContent : null;
            }
        """)

        # Extract inline script config
        html = await page.content()

        # Also check window.next / __NEXT_DATA__ via JS
        runtime_config = await page.evaluate("""
            () => {
                try {
                    return JSON.stringify(window.__NEXT_DATA__ || null);
                } catch(e) { return null; }
            }
        """)

        # Get cookies
        cookies_from_page = await ctx.cookies()

        await browser.close()
        return next_data_raw, runtime_config, cookies_from_page, html, version_found


def extract_version_from_next_data(raw):
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None

    # Walk the config for bffServiceVersionDefault / bffServiceVersion
    def walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if "bff" in k.lower() or "version" in k.lower() or "ServiceVersion" in k:
                    print(f"  KEY [{path}.{k}] = {str(v)[:120]}")
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    walk(data)

    # Also search raw string for version patterns
    matches = re.findall(r'"bff[^"]*version[^"]*"\s*:\s*"([^"]{1,20})"', raw, re.IGNORECASE)
    if matches:
        print(f"  bff version strings in __NEXT_DATA__: {matches}")
        return matches[0]

    return None


async def probe_cw_api(version, cookies):
    cookie_hdr = "; ".join(f"{c['name']}={c['value']}" for c in cookies if "takeaway" in c.get("domain", ""))

    headers = {**HEADERS_BASE, "Cookie": cookie_hdr}

    # Also try common alternatives
    versions_to_try = [version] if version else []
    versions_to_try += ["v1", "v2", "v3", "v4", "v5", "1", "2", "3"]
    # Remove dupes
    seen = set()
    versions_to_try = [v for v in versions_to_try if v and not (v in seen or seen.add(v))]

    async with httpx.AsyncClient(timeout=20) as client:
        for ver in versions_to_try[:8]:
            url = f"{BASE}/discovery/{ver}/restaurants/enriched/bypostcode/{POSTCODE}"
            params = {"serviceType": "delivery"}
            print(f"\nPROBE: GET {url}")
            try:
                r = await client.get(url, headers=headers, params=params)
                print(f"  → {r.status_code} {r.headers.get('content-type','')}")
                body = r.text[:500]
                print(f"  body: {body}")
                if r.status_code == 200:
                    print(f"\n*** SUCCESS with version={ver}! ***")
                    # Try to parse
                    try:
                        data = r.json()
                        if isinstance(data, dict):
                            print(f"  keys: {list(data.keys())}")
                        elif isinstance(data, list):
                            print(f"  list len: {len(data)}, first: {str(data[0])[:200] if data else 'empty'}")
                    except Exception:
                        pass
                    return ver, r.text
            except Exception as e:
                print(f"  error: {e}")

    return None, None


async def main():
    print("=== Step 1: load page, get config ===")
    next_data_raw, runtime_config, cookies, html, version_from_xhr = await get_page_config()

    print(f"\n__NEXT_DATA__ length: {len(next_data_raw) if next_data_raw else 0}")
    print(f"runtime_config length: {len(runtime_config) if runtime_config else 0}")
    print(f"cookies count: {len(cookies)}")
    print(f"version from browser XHR: {version_from_xhr}")

    # Search HTML for bffServiceVersion
    print("\n=== Inline HTML config search ===")
    for m in re.finditer(r'bffServiceVersion[^"\']{0,5}["\']?\s*[:=]\s*["\']?([^"\',\s\}]{1,30})', html):
        print(f"  HTML match: {m.group(0)[:80]}")

    # Check __NEXT_DATA__ for version
    print("\n=== __NEXT_DATA__ walk ===")
    version_from_data = extract_version_from_next_data(next_data_raw)
    print(f"Extracted version: {version_from_data}")

    # Also check first 20KB of __NEXT_DATA__ for any version-like values
    if next_data_raw:
        # Look for environment variable injection
        for pattern in [r'"NEXT_PUBLIC_BFF_VERSION"\s*:\s*"([^"]+)"',
                        r'"bffVersion"\s*:\s*"([^"]+)"',
                        r'"apiVersion"\s*:\s*"([^"]+)"']:
            m = re.search(pattern, next_data_raw, re.IGNORECASE)
            if m:
                print(f"  ENV match: {m.group(0)[:60]} → {m.group(1)}")

    print("\n=== Step 2: probe cw-api ===")
    ver, body = await probe_cw_api(version_from_xhr or version_from_data, cookies)

    if ver:
        print(f"\n=== FOUND WORKING VERSION: {ver} ===")
        with open("/tmp/cw_api_response.json", "w") as f:
            f.write(body)
        print("Saved to /tmp/cw_api_response.json")
    else:
        print("\nNo working version found.")
        # Dump what we know for manual analysis
        if next_data_raw:
            with open("/tmp/next_data.json", "w") as f:
                f.write(next_data_raw)
            print("Saved __NEXT_DATA__ to /tmp/next_data.json for inspection")


if __name__ == "__main__":
    asyncio.run(main())
