"""
Intercept JS bundles via Playwright response listener, save to /tmp, grep for API paths.
Avoids re-downloading (CDN 403); only the initial page-load bundles are accessible.
"""
import asyncio
import re
import json
import os
from playwright.async_api import async_playwright

SAVE_DIR = "/tmp/tkwy_bundles"
os.makedirs(SAVE_DIR, exist_ok=True)

# Bundles known to be relevant from previous session
PRIORITY_NAMES = ["restaurant-list", "_app", "52540", "discovery-saga"]

captured: dict[str, str] = {}  # filename -> content


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            locale="fr-BE",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )

        async def on_response(resp):
            url = resp.url
            if "_next/static" not in url or not url.endswith(".js"):
                return
            fname = url.split("/")[-1]
            try:
                body = await resp.body()
                text = body.decode("utf-8", errors="replace")
                captured[fname] = text
                # Save to disk
                with open(f"{SAVE_DIR}/{fname}", "w", encoding="utf-8") as f:
                    f.write(text)
            except Exception as e:
                print(f"  capture err {fname}: {e}")

        page = await ctx.new_page()
        page.on("response", on_response)

        print("Loading listing page...")
        await page.goto(
            "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000",
            wait_until="domcontentloaded",
            timeout=35000,
        )

        # CF bypass wait
        for _ in range(20):
            title = await page.title()
            if "instant" not in title.lower() and "moment" not in title.lower():
                break
            await asyncio.sleep(2)

        await asyncio.sleep(6)
        await browser.close()

    print(f"\nCaptured {len(captured)} bundles total")
    sizes = sorted(captured.items(), key=lambda x: -len(x[1]))
    for fname, txt in sizes[:10]:
        print(f"  {fname}: {len(txt)} bytes")

    # --- Search each bundle ---
    patterns = [
        (r'/api/v\d+/[a-z\-]+', "versioned API paths"),
        (r'"(/[a-z\-]+/restaurants[^"]{0,60})"', "restaurants in string"),
        (r'"(/[a-z\-]+/restaurant[^"]{0,60})"', "restaurant in string"),
        (r'fetch\([`"\']([^`"\']{5,120})[`"\']', "fetch() calls"),
        (r'axios\.(get|post)\([`"\']([^`"\']{5,120})', "axios calls"),
        (r'"(https?://[a-z\-\.]+\.takeaway\.com/[^"]{5,120})"', "full takeaway URLs"),
        (r'"/api/[^"]{5,80}"', "any /api/ path"),
        (r'"countryCode"\s*:\s*"BE"', "countryCode BE literal"),
        (r'bffServiceUrl[^,\}]{0,100}', "bffServiceUrl assignment"),
        (r'postalCode[^,\}]{0,80}', "postalCode param usage"),
    ]

    all_findings: dict[str, list[str]] = {}

    for fname, txt in sizes:
        found_any = False
        for rx, label in patterns:
            hits = list(set(re.findall(rx, txt)))
            if hits:
                if not found_any:
                    print(f"\n=== {fname} ({len(txt)} bytes) ===")
                    found_any = True
                print(f"  [{label}]: {hits[:5]}")
                key = f"{fname}|{label}"
                all_findings[key] = hits

                # Context dump for API path hits
                if "API path" in label or "fetch" in label or "axios" in label or "takeaway URL" in label:
                    for hit in hits[:3]:
                        h = hit if isinstance(hit, str) else hit[0]
                        idx = txt.find(h)
                        if idx >= 0:
                            ctx_str = txt[max(0, idx - 100):idx + 300]
                            print(f"    ctx: ...{ctx_str[:350]}...")

    # --- Dedicated deep search of restaurant-list bundle ---
    rl_bundle = next((c for f, c in captured.items() if "restaurant-list" in f), None)
    if rl_bundle:
        print(f"\n\n=== DEEP SEARCH: restaurant-list ({len(rl_bundle)} bytes) ===")

        # All string literals containing "restaurant"
        matches = re.findall(r'["\`]([^"\`]{0,50}restaurant[^"\`]{0,80})["\`]', rl_bundle, re.IGNORECASE)
        print(f"  String literals with 'restaurant': {len(matches)} hits")
        for m in sorted(set(matches))[:30]:
            if any(c in m for c in ['/', '?', '&', 'http', 'url', 'URL', 'path', 'PATH']):
                print(f"    URL-like: {m}")

        # All string literals containing "/"
        url_strings = re.findall(r'["\`](/[a-zA-Z][a-zA-Z0-9\-_/]{3,80})["\`]', rl_bundle)
        print(f"\n  Path strings: {len(url_strings)}")
        deduped = sorted(set(url_strings))
        for s in deduped[:50]:
            print(f"    {s}")

        # All fetch/axios/http calls
        http_calls = re.findall(r'(?:fetch|axios|http)\s*[\.(]\s*["\`]([^"\`]{5,120})["\`]', rl_bundle)
        if http_calls:
            print(f"\n  HTTP call arguments: {http_calls[:20]}")

        # Look for GraphQL
        gql = re.findall(r'query\s+[A-Z][a-zA-Z]+\s*\{', rl_bundle)
        if gql:
            print(f"\n  GraphQL queries: {gql[:10]}")

        # Template literals with URL patterns
        tmpl = re.findall(r'`([^`]{0,30}\$\{[^`]{0,200})`', rl_bundle)
        url_tmpl = [t for t in tmpl if 'restaurant' in t.lower() or '/api' in t or 'cw-api' in t]
        if url_tmpl:
            print(f"\n  Template literals (URL-like): {url_tmpl[:5]}")

    # Summary of cw-api / bff / tkwy domain strings
    print("\n\n=== SUMMARY: all takeaway/bff domain references ===")
    for fname, txt in captured.items():
        hits = re.findall(r'(?:cw-api|bff-service|tkwy-prod|\.takeaway\.com/api)[^\s"\'`]{0,120}', txt)
        if hits:
            print(f"  {fname}: {list(set(hits))[:5]}")


if __name__ == "__main__":
    asyncio.run(main())
