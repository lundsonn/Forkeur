"""
Download Next.js JS bundles from takeaway.com/be and grep for API paths.
The BFF endpoint is hardcoded in the compiled JS — find /api/v* patterns.
"""
import asyncio
import re
import httpx
from playwright.async_api import async_playwright


async def collect_bundle_urls() -> tuple[list[str], dict]:
    """Load page, collect all _next/static/*.js URLs + cookies."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            locale="fr-BE",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        js_urls: list[str] = []

        async def on_request(req):
            if "_next/static" in req.url and req.url.endswith(".js"):
                js_urls.append(req.url)

        page = await ctx.new_page()
        page.on("request", on_request)

        print("Loading page...")
        await page.goto(
            "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        for _ in range(20):
            title = await page.title()
            if "instant" not in title.lower() and "moment" not in title.lower():
                break
            await asyncio.sleep(2)
        await asyncio.sleep(4)

        cookies = {c["name"]: c["value"] for c in await ctx.cookies()}
        await browser.close()

        print(f"Collected {len(js_urls)} JS bundle URLs")
        return js_urls, cookies


async def search_bundles(js_urls: list[str], cookies: dict) -> None:
    """Download JS bundles and grep for API path patterns."""
    headers = {
        "Accept": "*/*",
        "Origin": "https://www.takeaway.com",
        "Referer": "https://www.takeaway.com/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    # Patterns to search for
    api_patterns = [
        r"/api/v\d+/[a-z]+",
        r'"restaurants"',
        r"bffServiceUrl",
        r"postalCode",
        r"deliveryAreaId",
        r"countryCode",
        r"/v\d+/restaurant",
    ]

    hits: dict[str, list[str]] = {}

    async with httpx.AsyncClient(cookies=cookies, headers=headers, follow_redirects=True) as client:
        # Prioritize larger bundles (more likely to contain app logic)
        # Sort by bundle name — "app" and "pages" bundles are most relevant
        priority = sorted(
            js_urls,
            key=lambda u: (
                0 if any(x in u for x in ["app-", "pages/", "main-", "framework"]) else 1,
                -len(u),
            ),
        )

        for url in priority[:30]:  # limit to 30 bundles
            try:
                r = await client.get(url, timeout=15)
                if r.status_code != 200:
                    print(f"  SKIP {r.status_code} {url[-60:]}")
                    continue

                js = r.text
                found_any = False
                for pat in api_patterns:
                    matches = re.findall(pat, js)
                    if matches:
                        unique = list(set(matches))
                        key = f"{url[-50:]} [{pat}]"
                        hits[key] = unique
                        if not found_any:
                            print(f"\n=== {url[-70:]} ({len(js)} bytes) ===")
                            found_any = True
                        print(f"  {pat}: {unique[:5]}")

                        # If we found API path pattern, dump context
                        if "/api/v" in pat:
                            for m in unique[:3]:
                                idx = js.find(m)
                                if idx >= 0:
                                    snippet = js[max(0, idx - 80) : idx + 200]
                                    print(f"    Context: ...{snippet}...")

            except Exception as e:
                print(f"  ERR {url[-60:]}: {e}")

    print(f"\n=== Summary: {len(hits)} pattern hits across bundles ===")
    all_api_paths = []
    for key, vals in hits.items():
        for v in vals:
            if re.match(r"^/api/v\d+/", v):
                all_api_paths.append(v)
    if all_api_paths:
        print(f"API paths found: {sorted(set(all_api_paths))}")
    else:
        print("No /api/vN/ paths found in bundles")


async def main():
    js_urls, cookies = await collect_bundle_urls()
    await search_bundles(js_urls, cookies)


if __name__ == "__main__":
    asyncio.run(main())
