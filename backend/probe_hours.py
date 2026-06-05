"""Probe: dump data.hours and data.meta.sectionHoursInfo from getStoreV1."""
import asyncio, json, sys
sys.path.insert(0, '/opt/forkeur/backend')
from scrapers.base import browser_session, new_page, check_cloudflare

ADDRESS = "Place Jourdan, Etterbeek, Belgium"

async def main():
    async with browser_session(lang="fr-BE") as browser:
        page = await new_page(browser, lang="fr-BE")
        feed_pages = []
        store_raw = []

        async def on_resp(r):
            if "getFeedV1" in r.url and not feed_pages:
                try: feed_pages.append(await r.text())
                except: pass
            if "getStoreV1" in r.url and not store_raw:
                try: store_raw.append(await r.text())
                except Exception as e: store_raw.append(f"ERR:{e}")

        page.on("response", on_resp)
        await page.goto("https://www.ubereats.com/", wait_until="domcontentloaded", timeout=60000)
        check_cloudflare(await page.title())
        inp = "#location-typeahead-home-input"
        await page.wait_for_selector(inp, timeout=20000)
        await page.click(inp)
        await page.type(inp, ADDRESS, delay=60)
        await asyncio.sleep(3)
        await page.keyboard.press("ArrowDown")
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        deadline = asyncio.get_event_loop().time() + 20
        while not feed_pages and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)
        if not feed_pages:
            print("ERROR: no feed", flush=True); return

        feed = json.loads(feed_pages[0])
        for item in feed.get("data", {}).get("feedItems", []):
            if item.get("type") == "REGULAR_STORE":
                s = item.get("store", {})
                if s.get("actionUrl"):
                    store_slug = s["actionUrl"].split("?")[0].split("/store/")[-1].strip("/")
                    name = (s.get("title") or {}).get("text", "?")
                    break

        print(f"Clicking: {name}", flush=True)
        await page.evaluate(f"""
            (() => {{ let a = document.querySelector('a[href*="/store/{store_slug}"]'); if (a) a.click(); }})()
        """)
        deadline = asyncio.get_event_loop().time() + 15
        while not store_raw and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)
        if not store_raw:
            print("ERROR: not captured", flush=True); return

        d = json.loads(store_raw[0]).get("data", {})

        print(f"\n[hours] = {json.dumps(d.get('hours'))[:1000]}", flush=True)
        print(f"\n[isOpen] = {d.get('isOpen')}", flush=True)
        print(f"\n[meta.sectionHoursInfo] = {json.dumps(d.get('meta', {}).get('sectionHoursInfo'))[:1000]}", flush=True)
        print(f"\n[workingHoursTagline] = {d.get('workingHoursTagline')}", flush=True)

asyncio.run(main())
