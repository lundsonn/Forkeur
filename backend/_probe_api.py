"""Validate rewritten scrape_menu_page against 2 real restaurants (no DB)."""
import asyncio
from scrapers.base import new_browser, new_page, wait_for_cf_clear
from scrapers.takeaway import scrape_menu_page, LISTING_URL

MENUS = [
    "https://www.takeaway.com/be-fr/menu/curry-n-grill-house-bruxelles",
    "https://www.takeaway.com/be-fr/menu/sensei-sushi-meiser",
]


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        # warm listing
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        print("listing cleared\n", flush=True)

        for url in MENUS:
            print(f"=== {url} ===", flush=True)
            try:
                _, items = await scrape_menu_page(page, "test-lid", url)
                print(f"  {len(items)} items", flush=True)
                cats = {}
                for it in items:
                    cats.setdefault(it["catalog_name"], 0)
                    cats[it["catalog_name"]] += 1
                for c, n in cats.items():
                    print(f"    [{c}] {n}", flush=True)
                for it in items[:6]:
                    print(f"    - {it['title']!r} = {it['price']} ({it['catalog_name']})", flush=True)
            except Exception as e:
                print(f"  ERROR: {e!r}", flush=True)
            print(flush=True)

    finally:
        await browser.close()


asyncio.run(main())
