"""Probe Deliveroo menu page: count notranslate divs, price leaves, item extraction."""
import asyncio
from scrapers.base import new_browser, new_page

URL = "https://deliveroo.be/fr/menu/Brussels/midi-marolles/otacos-lemonnier?day=today&geohash=u1515p8sqrwc&time=ASAP"

JS = r"""
() => {
    function parsePrice(raw) {
        const m = raw.match(/(\d+)[,.]?(\d{0,2})/);
        if (!m) return null;
        const p = parseFloat(m[1] + '.' + (m[2] || '00').padEnd(2, '0'));
        return (p > 0 && p <= 200) ? p : null;
    }

    const ntDivs = Array.from(document.querySelectorAll('div.notranslate'));
    const ntItems = [];
    ntDivs.forEach(nt => {
        if (nt.parentElement?.closest('div.notranslate')) return;
        const titleEl = nt.querySelector('p, span, h2, h3, h4') || nt;
        const title = (titleEl.innerText || '').trim();
        if (!title || title.length < 2) return;
        let el = nt;
        let priceM = null;
        for (let i = 0; i < 6; i++) {
            if (!el.parentElement) break;
            el = el.parentElement;
            const text = (el.innerText || '').trim();
            priceM = text.match(/(\d+)[,.]?(\d{0,2})\s*€/);
            if (priceM) break;
        }
        if (priceM) ntItems.push(title);
    });

    // Price leaf count
    const priceLeaves = Array.from(document.querySelectorAll('span, div, p')).filter(el => {
        const t = (el.innerText || '').trim();
        return /^\d+[,.]\d{2}\s*€$/.test(t) && el.children.length === 0;
    });

    // Class patterns containing "MenuItemCard"
    const cardClasses = new Set();
    document.querySelectorAll('[class]').forEach(el => {
        const c = el.className;
        if (typeof c === 'string' && c.includes('MenuItemCard')) cardClasses.add(c.slice(0, 60));
    });

    // h2 headings
    const h2s = Array.from(document.querySelectorAll('h2')).map(h => h.innerText.trim()).filter(Boolean);

    return {
        ntDivCount: ntDivs.length,
        ntItemsWithPrice: ntItems.length,
        ntSample: ntItems.slice(0, 5),
        priceLeafCount: priceLeaves.length,
        priceSample: priceLeaves.slice(0, 5).map(e => e.innerText.trim()),
        menuItemCardClasses: [...cardClasses].slice(0, 5),
        h2Headings: h2s.slice(0, 10),
        bodyScrollHeight: document.body.scrollHeight,
    };
}
"""


async def main():
    browser = await new_browser(lang="fr-BE", headed=False)
    page = await new_page(browser, lang="fr-BE")
    try:
        print("Loading...", flush=True)
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"goto: {e}", flush=True)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(2)

        # Scroll fully
        prev_h = 0
        for _ in range(30):
            h = await page.evaluate("document.body.scrollHeight")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(800)
            if h == prev_h:
                await page.wait_for_timeout(600)
                h2 = await page.evaluate("document.body.scrollHeight")
                if h2 == h:
                    break
            prev_h = h

        # Count-stable loop
        prev_count = 0
        for _ in range(20):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(900)
            cur = await page.evaluate("document.querySelectorAll('div.notranslate').length")
            if cur == prev_count:
                break
            prev_count = cur

        result = await page.evaluate(JS)
        print(f"\n=== DELIVEROO MENU PROBE ===", flush=True)
        print(f"notranslate divs total:      {result['ntDivCount']}", flush=True)
        print(f"notranslate with price:      {result['ntItemsWithPrice']}", flush=True)
        print(f"price leaf elements:         {result['priceLeafCount']}", flush=True)
        print(f"body scroll height:          {result['bodyScrollHeight']}", flush=True)
        print(f"\nSample items (notranslate):  {result['ntSample']}", flush=True)
        print(f"Sample prices (leaf):        {result['priceSample']}", flush=True)
        print(f"MenuItemCard classes:        {result['menuItemCardClasses']}", flush=True)
        print(f"h2 headings:                 {result['h2Headings']}", flush=True)
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
