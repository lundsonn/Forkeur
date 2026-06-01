"""Try /_next/data/{buildId}/be-fr/menu/{slug}.json — Next.js SSR props endpoint.
CF may not protect this path the same way as the full page render.
"""
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
        await asyncio.sleep(2)

        # Extract buildId + first 3 slugs
        info = await page.evaluate("""() => {
            const nd = window.__NEXT_DATA__ || {};
            const buildId = nd.buildId || '';
            const anchors = Array.from(document.querySelectorAll('a[href*="/menu/"]'));
            const slugs = [...new Set(anchors.map(a => {
                const m = a.href.match(/\/menu\/([^?#\/]+)/);
                return m ? m[1] : null;
            }).filter(Boolean))].slice(0, 5);
            return { buildId, slugs, ndKeys: Object.keys(nd) };
        }""")

        build_id = info["buildId"]
        slugs = info["slugs"]
        print(f"buildId: {build_id}", flush=True)
        print(f"slugs: {slugs}", flush=True)
        print(f"__NEXT_DATA__ keys: {info['ndKeys']}", flush=True)

        if not build_id:
            print("No buildId found — checking HTML for build ID pattern", flush=True)
            html = await page.content()
            import re
            m = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)
            if m:
                build_id = m.group(1)
                print(f"Found in HTML: {build_id}", flush=True)

        if not build_id or not slugs:
            print("Missing buildId or slugs — cannot continue", flush=True)
            return

        hdrs = {
            "Accept": "application/json",
            "Referer": LISTING_URL,
            "x-nextjs-data": "1",
        }

        print(f"\n=== _next/data tests ===", flush=True)
        for slug in slugs:
            url = f"https://www.takeaway.com/_next/data/{build_id}/be-fr/menu/{slug}.json"
            await asyncio.sleep(1)
            try:
                r = await page.request.get(url, headers=hdrs, timeout=15000)
                t = await r.text()
                is_json = t.strip()[:1] in ("{", "[")
                mark = "  <<< JSON HIT" if r.status == 200 and is_json else ""
                print(f"[{r.status}] /.../{slug}.json{mark}", flush=True)
                if r.status == 200 and is_json:
                    # Find menu items in response
                    import json
                    data = json.loads(t)
                    # Dump structure
                    print(f"  top keys: {list(data.keys())[:10]}", flush=True)
                    props = data.get("pageProps", {})
                    print(f"  pageProps keys: {list(props.keys())[:15]}", flush=True)
                    # Look for items/products
                    raw = str(data)
                    import re
                    items = re.findall(r'"(?:name|title)"\s*:\s*"([^"]{3,50})"', raw)[:8]
                    prices = re.findall(r'"(?:price|priceDoubleCents|amount)"\s*:\s*(\d+)', raw)[:8]
                    print(f"  sample names: {items}", flush=True)
                    print(f"  sample prices: {prices}", flush=True)
                    break
                elif r.status != 404:
                    print(f"    {t[:200]}", flush=True)
            except Exception as e:
                print(f"[ERR] {slug} → {e}", flush=True)

    finally:
        await browser.close()


asyncio.run(main())
