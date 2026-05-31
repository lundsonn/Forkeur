"""Probe: click-nav to menu page, dump data-qa structure to find title+price selectors."""
import asyncio
import json
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        print("Loading listing...")
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)

        print("Waiting for CF...")
        cleared = await wait_for_cf_clear(page, timeout_s=90)
        print(f"CF cleared: {cleared}, title: {await page.title()}")

        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        print("Cards visible — waiting 15s for SPA to fully bootstrap...")
        await asyncio.sleep(15)

        # Check SPA readiness signals
        spa_info = await page.evaluate("""() => ({
            reactRoot: !!document.querySelector('#__next, #root, [data-reactroot]'),
            hasRouter: typeof window.__NEXT_DATA__ !== 'undefined' || typeof window.next !== 'undefined',
            cardCount: document.querySelectorAll('[data-qa="restaurant-card"]').length,
            firstCardHTML: document.querySelector('[data-qa="restaurant-card"]')?.innerHTML?.substring(0, 300) || '',
            firstMenuHref: document.querySelector('[data-qa="restaurant-card"] a[href*="/menu/"]')?.getAttribute('href') || null,
        })""")
        print(f"SPA info: react={spa_info['reactRoot']} router={spa_info['hasRouter']} cards={spa_info['cardCount']}")
        print(f"First menu href: {spa_info['firstMenuHref']}")
        print(f"First card HTML snippet:\n{spa_info['firstCardHTML']}")

        first_href = spa_info['firstMenuHref']
        if not first_href:
            print("No menu link found")
            return

        # Scroll target into view
        await page.evaluate(f"""() => {{
            const el = document.querySelector('a[href="{first_href}"]');
            el?.scrollIntoView({{behavior: 'smooth', block: 'center'}});
        }}""")
        await asyncio.sleep(2)

        # Try JS click (goes through SPA router more reliably)
        print(f"JS-clicking {first_href}...")
        await page.evaluate(f"""() => {{
            document.querySelector('a[href="{first_href}"]')?.click();
        }}""")
        await asyncio.sleep(0.5)
        print(f"URL after click: {page.url}")

        # Try wait_for_cf_clear again on menu page
        print("Running wait_for_cf_clear on menu page (up to 120s)...")
        menu_cleared = await wait_for_cf_clear(page, timeout_s=120)
        print(f"Menu CF cleared: {menu_cleared}, title: {await page.title()}")
        await asyncio.sleep(3)
        title = await page.title()
        print(f"Menu page title: {title}")

        # Dump all data-qa values and counts
        qa_counts = await page.evaluate("""() => {
            const counts = {};
            document.querySelectorAll('[data-qa]').forEach(el => {
                const qa = el.getAttribute('data-qa');
                counts[qa] = (counts[qa] || 0) + 1;
            });
            return counts;
        }""")
        print("\n--- data-qa counts ---")
        for k, v in sorted(qa_counts.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")

        # Try card-element structure
        card_elements = await page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('[data-qa="card-element"]'));
            return els.slice(0, 5).map(el => ({
                outerHTML: el.outerHTML.substring(0, 500),
                text: el.innerText.substring(0, 200),
                childQas: Array.from(el.querySelectorAll('[data-qa]')).map(c => c.getAttribute('data-qa'))
            }));
        }""")
        print("\n--- card-element samples (first 5) ---")
        for i, c in enumerate(card_elements):
            print(f"\n[{i}] text: {c['text']!r}")
            print(f"     child data-qa: {c['childQas']}")

        # Try to find price patterns
        price_els = await page.evaluate("""() => {
            const results = [];
            // Look for elements containing € and a number
            const all = Array.from(document.querySelectorAll('[data-qa]'));
            for (const el of all) {
                const t = el.innerText || '';
                if (/€\\s*\\d|\\d[,.]\\d+\\s*€/.test(t) && el.children.length === 0) {
                    results.push({
                        qa: el.getAttribute('data-qa'),
                        text: t.trim(),
                        parentQas: [el.parentElement, el.parentElement?.parentElement, el.parentElement?.parentElement?.parentElement]
                            .filter(Boolean)
                            .map(p => p.getAttribute('data-qa'))
                    });
                    if (results.length >= 10) break;
                }
            }
            return results;
        }""")
        print("\n--- price-bearing leaf elements ---")
        for p in price_els:
            print(f"  qa={p['qa']!r} text={p['text']!r} parents={p['parentQas']}")

        # Dump full structure of first card-element
        if card_elements:
            print("\n--- first card-element HTML ---")
            print(card_elements[0]['outerHTML'])

    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
