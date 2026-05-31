import asyncio
from scrapers.base import new_browser, new_page, wait_for_cf_clear

# A known restaurant menu URL from last run (Domino's — likely has clean menu)
MENU_URL = "https://www.takeaway.com/be-fr/menu/domino-s-pizza-bruxelles"


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        print("goto", MENU_URL, flush=True)
        await page.goto(MENU_URL, wait_until="domcontentloaded", timeout=60000)
        cleared = await wait_for_cf_clear(page, timeout_s=90)
        print("cf cleared:", cleared, "| title:", await page.title(), flush=True)
        await asyncio.sleep(3)
        await page.evaluate("window.scrollBy(0, 2000)")
        await asyncio.sleep(2)

        # Dump candidate selectors + counts
        probe = await page.evaluate("""() => {
            const sel = (s) => document.querySelectorAll(s).length;
            // collect data-qa values that look item-ish
            const qa = {};
            document.querySelectorAll('[data-qa]').forEach(e => {
                const v = e.getAttribute('data-qa');
                qa[v] = (qa[v]||0)+1;
            });
            const testid = {};
            document.querySelectorAll('[data-testid]').forEach(e => {
                const v = e.getAttribute('data-testid');
                testid[v] = (testid[v]||0)+1;
            });
            return {
                counts: {
                    'data-qa*=product': sel('[data-qa*="product"]'),
                    'data-testid*=product': sel('[data-testid*="product"]'),
                    'product-card': sel('.product-card'),
                    'article': sel('article'),
                    'li': sel('li'),
                },
                dataQa: qa,
                dataTestid: testid,
            };
        }""")
        import json
        print("COUNTS:", json.dumps(probe["counts"], indent=2), flush=True)
        # show data-qa keys with count >5 (repeated = likely list items)
        print("\nREPEATED data-qa (>3):", flush=True)
        for k, v in sorted(probe["dataQa"].items(), key=lambda x: -x[1]):
            if v > 3:
                print(f"  {v:4d}  {k}", flush=True)
        print("\nREPEATED data-testid (>3):", flush=True)
        for k, v in sorted(probe["dataTestid"].items(), key=lambda x: -x[1]):
            if v > 3:
                print(f"  {v:4d}  {k}", flush=True)
    finally:
        await browser.close()


asyncio.run(main())
