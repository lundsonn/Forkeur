import asyncio
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"

captured = []


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")

        def on_req(req):
            u = req.url
            if req.resource_type in ("xhr", "fetch"):
                captured.append((req.method, u, dict(req.headers)))

        page.on("request", on_req)

        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 3000)")
            await asyncio.sleep(0.6)
        await asyncio.sleep(2)

        print(f"\n=== ALL {len(captured)} XHR/fetch reqs ===", flush=True)
        for method, u, h in captured:
            print(f"{method} {u[:200]}", flush=True)
    finally:
        await browser.close()


asyncio.run(main())
