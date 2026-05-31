import asyncio
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 3000)")
            await asyncio.sleep(0.6)
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)

        # SPA click nav instead of goto — first restaurant card link
        link = await page.query_selector('[data-qa="restaurant-card"] a[href*="/menu/"]')
        target = await link.get_attribute("href")
        print("clicking ->", target, flush=True)
        await link.click()
        # wait for SPA route change
        try:
            await page.wait_for_url("**/menu/**", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(3)
        print("after click title:", await page.title(), "| url:", page.url, flush=True)

        # try wait for any product-ish selector
        await page.evaluate("window.scrollBy(0, 1500)")
        await asyncio.sleep(2)

        probe = await page.evaluate("""() => {
            const qa = {}; const testid = {};
            document.querySelectorAll('[data-qa]').forEach(e => {
                const v = e.getAttribute('data-qa'); qa[v]=(qa[v]||0)+1; });
            document.querySelectorAll('[data-testid]').forEach(e => {
                const v = e.getAttribute('data-testid'); testid[v]=(testid[v]||0)+1; });
            return { qa, testid, h1: (document.querySelector('h1')||{}).textContent };
        }""")
        print("H1:", probe["h1"], flush=True)
        print("\nREPEATED data-qa (>3):", flush=True)
        for k, v in sorted(probe["qa"].items(), key=lambda x: -x[1]):
            if v > 3:
                print(f"  {v:4d}  {k}", flush=True)
        print("\nREPEATED data-testid (>3):", flush=True)
        for k, v in sorted(probe["testid"].items(), key=lambda x: -x[1]):
            if v > 3:
                print(f"  {v:4d}  {k}", flush=True)
    finally:
        await browser.close()


asyncio.run(main())
