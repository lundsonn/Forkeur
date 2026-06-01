import asyncio
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"
SLUG = "carrefour-city-anspach-bruxelles"
H = "https://cw-api.takeaway.com"

# v30/v31 returned 429 (rate limited = endpoint exists). Try with delay + correct headers.
CAND = [
    f"{H}/api/v31/restaurants/{SLUG}",
    f"{H}/api/v31/restaurants/{SLUG}/menu",
    f"{H}/api/v31/restaurant?slug={SLUG}&language=fr&country_code=BE",
    f"{H}/api/v31/restaurant?slug={SLUG}&language=fr",
    f"{H}/api/v30/restaurants/{SLUG}",
    f"{H}/api/v30/restaurant?slug={SLUG}&language=fr&country_code=BE",
    f"{H}/api/v30/restaurants/{SLUG}/menu",
]


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        print("cleared\n", flush=True)
        await asyncio.sleep(5)  # let rate limit window reset

        # page.request bypasses CORS — use it with session context + delay
        hdrs = {
            "Accept": "application/json",
            "X-Country-Code": "BE",
            "X-Language-Code": "fr",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.takeaway.com",
            "Referer": LISTING_URL,
        }
        for url in CAND:
            await asyncio.sleep(2)
            try:
                r = await page.request.get(url, headers=hdrs, timeout=15000)
                t = await r.text()
                is_json = t.strip()[:1] in ("{", "[")
                mark = "  <<< JSON HIT" if r.status == 200 and is_json else ""
                print(f"[{r.status}] {url[len(H):]}{mark}", flush=True)
                if is_json or r.status not in (404, 429):
                    print(f"    {t[:400]}", flush=True)
                if r.status == 200 and is_json:
                    break
            except Exception as e:
                print(f"[ERR] {url[len(H):]} → {e}", flush=True)
    finally:
        await browser.close()


asyncio.run(main())
