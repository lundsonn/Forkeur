import asyncio
from scrapers.base import new_browser, new_page, wait_for_cf_clear

LISTING_URL = "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000"
SLUG = "carrefour-city-anspach-bruxelles"
H = "https://cw-api.takeaway.com"

CAND = [
    f"{H}/api/restaurant/{SLUG}",
    f"{H}/api/v34/restaurant?slug={SLUG}&language=fr&country=be",
    f"{H}/api/restaurants/{SLUG}",
]


async def main():
    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")
        await page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
        await wait_for_cf_clear(page, timeout_s=90)
        await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=30000)
        print("cleared\n", flush=True)
        await asyncio.sleep(2)

        # in-page fetch: tries a matrix of header sets, returns status+snippet
        result = await page.evaluate("""async (cands) => {
            const out = [];
            const headerSets = [
                {},
                {'X-Country-Code':'be','X-Language-Code':'fr'},
                {'X-Country-Code':'BE','X-Language-Code':'fr-BE','X-Requested-With':'XMLHttpRequest'},
                {'Accept':'application/json','X-Country-Code':'be'},
            ];
            for (const url of cands) {
                for (const h of headerSets) {
                    try {
                        const r = await fetch(url, {headers: h, credentials:'include'});
                        const t = await r.text();
                        out.push({url, h:Object.keys(h), status:r.status,
                                  json: t.trim()[0]==='{'||t.trim()[0]==='[',
                                  snip: t.slice(0,160)});
                        if (r.status===200 && (t.trim()[0]==='{'||t.trim()[0]==='[')) return out;
                    } catch(e) {
                        out.push({url, h:Object.keys(h), status:'ERR', snip:String(e).slice(0,100)});
                    }
                }
            }
            return out;
        }""", CAND)

        for o in result:
            mark = "  <<< JSON" if o.get("json") else ""
            print(f"[{o['status']}] hdr={o['h']} {o['url'][len(H):][:60]}{mark}", flush=True)
            if o.get("json"):
                print("   ", o["snip"], flush=True)
    finally:
        await browser.close()


asyncio.run(main())
