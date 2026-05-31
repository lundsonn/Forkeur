import asyncio, re
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        await asyncio.sleep(1)

        html = await page.content()
        srcs = re.findall(r'<script[^>]+src="([^"]+\.js)"', html)
        srcs = [s if s.startswith("http") else "https://www.takeaway.com" + s for s in srcs]
        print(f"{len(srcs)} scripts", flush=True)

        path_hits = set()
        for s in srcs:
            try:
                resp = await page.request.get(s, timeout=20000)
                js = await resp.text()
            except Exception:
                continue
            if "cw-api" in js or "/restaurant" in js:
                # find path templates referencing restaurant/menu/items
                for m in re.findall(r'["\`/][a-zA-Z0-9/_${}.\-]*(?:restaurant|menu|items)[a-zA-Z0-9/_${}.\-]*', js):
                    if 4 < len(m) < 80 and m.count("/") >= 1:
                        path_hits.add(m.strip('"`'))
        print("\n=== path templates ===", flush=True)
        for p in sorted(path_hits):
            if any(k in p for k in ("api", "restaurant", "menu", "items", "v3", "v2", "v1")):
                print(" ", p, flush=True)
    finally:
        await browser.close()


asyncio.run(main())
