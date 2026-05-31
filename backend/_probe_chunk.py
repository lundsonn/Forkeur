import asyncio, re
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"
BUILD = "qRkqedz0xfTs2EZdHCtxW"
BASE = "https://www.takeaway.com/_next/static"


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)

        # build manifest lists page -> chunk files
        man = await (await page.request.get(f"{BASE}/{BUILD}/_buildManifest.js", timeout=20000)).text()
        print("manifest len", len(man), flush=True)
        # find menu route entries + their js files
        menu_files = set(re.findall(r'static/(chunks/[^"\']*?menu[^"\']*?\.js)', man))
        # also routes mapping
        routes = re.findall(r'"(/[^"]*menu[^"]*)":\[([^\]]*)\]', man)
        print("menu routes:", [r[0] for r in routes], flush=True)
        for _, files in routes:
            for f in re.findall(r'"([^"]+\.js)"', files):
                menu_files.add(f)
        print("menu chunk files:", menu_files, flush=True)

        path_hits = set()
        for f in menu_files:
            url = f"{BASE}/{f}" if f.startswith("chunks") else f"https://www.takeaway.com/_next/{f}"
            try:
                js = await (await page.request.get(url, timeout=20000)).text()
            except Exception as e:
                print("fetch err", f, e, flush=True)
                continue
            print(f"\n--- {f} ({len(js)} bytes) cw-api:{ 'cw-api' in js }", flush=True)
            # any concat'd path building for restaurant/menu/items
            for m in re.findall(r'(?:api/v\d+|/restaurant|/menu|/items|/catalog|/products)[a-zA-Z0-9/_${}.?=&\-]{0,60}', js):
                path_hits.add(m)
        print("\n=== PATHS ===", flush=True)
        for p in sorted(path_hits):
            print(" ", p, flush=True)
    finally:
        await browser.close()


asyncio.run(main())
