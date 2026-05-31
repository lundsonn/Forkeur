import asyncio
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"
SLUG = "carrefour-city-anspach-bruxelles"

# Candidate menu API endpoints (Takeaway/JustEat "cw-api" historical patterns)
CANDIDATES = [
    f"https://cw-api.takeaway.com/api/v34/restaurant?slug={SLUG}",
    f"https://cw-api.takeaway.com/api/v33/restaurant?slug={SLUG}",
    f"https://cw-api.takeaway.com/api/v32/restaurant?slug={SLUG}",
]


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        print("listing cleared\n", flush=True)

        hdr_variants = [
            {"X-Country-Code": "be", "X-Language-Code": "fr", "Accept": "application/json"},
            {"X-Country-Code": "BE", "X-Language-Code": "fr-BE", "Accept": "application/json"},
            {},
        ]

        for url in CANDIDATES:
            for hv in hdr_variants:
                try:
                    resp = await page.request.get(url, headers=hv, timeout=20000)
                    body = await resp.text()
                    ok = resp.status == 200 and body.strip().startswith("{")
                    print(f"[{resp.status}] hdr={list(hv.keys())} {url[:70]}", flush=True)
                    if ok:
                        print("   >>> JSON len", len(body), "snippet:", body[:200], flush=True)
                        return
                    else:
                        print("   body:", body[:120].replace(chr(10), " "), flush=True)
                except Exception as e:
                    print(f"[ERR] {url[:70]} :: {e}", flush=True)
    finally:
        await browser.close()


asyncio.run(main())
