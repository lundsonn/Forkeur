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

        # Dump pageProps structure
        nd = await page.evaluate("() => JSON.stringify(window.__NEXT_DATA__?.props?.pageProps || {})")
        pp = json.loads(nd)
        print("=== pageProps keys ===")
        print(list(pp.keys())[:20])
        # Dump first 2000 chars
        print(json.dumps(pp, ensure_ascii=False)[:2000])

        # Fetch restaurant-list JS bundle
        html = await page.content()
        m = re.search(r'(/_next/static/chunks/[^"]*restaurant[^"]*\.js)', html)
        if m:
            url = "https://www.takeaway.com" + m.group(1)
            print(f"\n=== Fetching {url} ===")
            r = await page.request.get(url, timeout=20000)
            js = await r.text()
            # Find cw-api paths
            hits = re.findall(r'["\`][^"\`]*cw-api[^"\`]*["\`]', js)
            print("cw-api refs:", hits[:10])
            # Find all path-like templates
            paths = re.findall(r'`/api/[^`\s]{3,80}`', js)
            print("api path templates:", paths[:20])
            # Find restaurant/menu refs
            rests = re.findall(r'["\`][^"\`]*(?:restaurant|menu|product)[^"\`\s]{3,60}["\`]', js)
            print("restaurant refs:", rests[:20])
        else:
            print("restaurant-list bundle not found in HTML")

    finally:
        await browser.close()

asyncio.run(main())
