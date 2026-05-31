import asyncio
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"
SLUG = "carrefour-city-anspach-bruxelles"
H = "https://cw-api.takeaway.com"

CAND = []
for v in ("v34", "v33", "v32", "v31", "v30"):
    CAND += [
        f"{H}/api/{v}/restaurant/{SLUG}",
        f"{H}/api/{v}/restaurants/{SLUG}",
        f"{H}/api/{v}/restaurant/{SLUG}/menu",
    ]
CAND += [
    f"{H}/api/restaurant/{SLUG}",
    f"{H}/api/restaurants/{SLUG}",
    f"{H}/restaurant/{SLUG}",
    f"{H}/api/v1/restaurants/{SLUG}/menu",
    f"{H}/api/v1/restaurant/{SLUG}",
]


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        print("cleared\n", flush=True)

        hdrs = {"X-Country-Code": "be", "X-Language-Code": "fr", "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest"}
        for url in CAND:
            try:
                r = await page.request.get(url, headers=hdrs, timeout=15000)
                b = await r.text()
                flag = "  <<<<< JSON" if (r.status == 200 and b.lstrip()[:1] in "{[") else ""
                print(f"[{r.status}] {url[len(H):]}{flag}", flush=True)
                if flag:
                    print("   ", b[:300], flush=True)
            except Exception as e:
                print(f"[ERR] {url[len(H):]} :: {str(e)[:60]}", flush=True)
    finally:
        await browser.close()


asyncio.run(main())
