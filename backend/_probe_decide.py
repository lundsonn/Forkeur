import asyncio
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"
MENU_PATH = "/be-fr/menu/carrefour-city-anspach-bruxelles"


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        print("listing cleared", flush=True)

        cookies = await page.context.cookies()
        names = [c["name"] for c in cookies]
        print("cookies:", names, flush=True)
        print("cf_clearance present:", any("cf_clearance" in n for n in names), flush=True)

        # SPA in-app nav via click (keeps session, real gesture, referer set)
        print("\nclicking first card...", flush=True)
        await page.click(f'a[href="{MENU_PATH}"]', timeout=10000)

        for i in range(24):  # up to 120s
            await asyncio.sleep(5)
            t = await page.title()
            blocked = "instant" in t.lower() or "moment" in t.lower()
            nprod = await page.evaluate("""() => document.querySelectorAll(
                '[data-qa*="menu"],[data-qa*="product"],[data-qa*="item"],article,[class*="menu-item"],[class*="MenuItem"]').length""")
            print(f"  t+{(i+1)*5}s title={t[:40]!r} blocked={blocked} prodish={nprod}", flush=True)
            if not blocked and nprod > 3:
                break

        # discover real selectors
        probe = await page.evaluate("""() => {
            const qa={}, cls={};
            document.querySelectorAll('[data-qa]').forEach(e=>{const v=e.getAttribute('data-qa');qa[v]=(qa[v]||0)+1;});
            document.querySelectorAll('[class]').forEach(e=>{e.classList.forEach(c=>{if(/item|product|dish|menu/i.test(c))cls[c]=(cls[c]||0)+1;});});
            return {qa, cls, h1:(document.querySelector('h1')||{}).textContent};
        }""")
        print("\nH1:", probe["h1"], flush=True)
        print("data-qa >3:", flush=True)
        for k,v in sorted(probe["qa"].items(), key=lambda x:-x[1]):
            if v>3: print(f"  {v:4d} {k}", flush=True)
        print("item-ish classes >3:", flush=True)
        for k,v in sorted(probe["cls"].items(), key=lambda x:-x[1]):
            if v>3: print(f"  {v:4d} {k}", flush=True)
    finally:
        await browser.close()


asyncio.run(main())
