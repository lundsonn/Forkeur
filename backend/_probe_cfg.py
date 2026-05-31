import asyncio, re, json
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        await asyncio.sleep(2)

        html = await page.content()
        print("HTML len:", len(html), flush=True)

        # find api hosts / versions
        hits = set(re.findall(r'https://[a-z0-9.\-]*api[a-z0-9.\-]*\.[a-z]+(?:/[a-zA-Z0-9/_\-.]*)?', html))
        print("\n=== api-ish URLs in HTML ===", flush=True)
        for h in sorted(hits)[:40]:
            print(" ", h[:120], flush=True)

        for kw in ("cw-api", "api/v", "deliveryArea", "restaurantSlug", "/menu", "apiUrl", "X-Country"):
            idx = html.find(kw)
            print(f"\nkw '{kw}': idx={idx}", flush=True)
            if idx > 0:
                print("   ctx:", html[max(0, idx-60):idx+90].replace("\n", " "), flush=True)

        # __NEXT_DATA__
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if m:
            try:
                nd = json.loads(m.group(1))
                rc = nd.get("runtimeConfig") or nd.get("props", {}).get("pageProps", {})
                print("\n__NEXT_DATA__ keys:", list(nd.keys()), flush=True)
                print("buildId:", nd.get("buildId"), flush=True)
                # dump runtimeConfig if present
                if "runtimeConfig" in nd:
                    print("runtimeConfig:", json.dumps(nd["runtimeConfig"])[:600], flush=True)
            except Exception as e:
                print("NEXT_DATA parse err", e, flush=True)
        else:
            print("\nno __NEXT_DATA__ (not pages-router Next)", flush=True)
    finally:
        await browser.close()


asyncio.run(main())
