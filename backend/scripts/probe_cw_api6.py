"""
Make cw-api request from INSIDE Playwright browser context to bypass CF fingerprinting.
Version: 34 (confirmed from __NEXT_DATA__)
"""
import asyncio
import json
import re
from playwright.async_api import async_playwright

VERSION = "34"
POSTCODE = "1000"
CW_URL = f"https://cw-api.takeaway.com/discovery/{VERSION}/restaurants/enriched/bypostcode/{POSTCODE}"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            locale="fr-BE",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )

        # --- Approach A: intercept XHR on the listing page ---
        # (Unlikely since SSR, but maybe some lazy-loaded content)
        api_responses = {}

        async def on_response(resp):
            if "cw-api" in resp.url:
                print(f"  [XHR INTERCEPTED] {resp.status} {resp.url[:120]}")
                try:
                    body = await resp.body()
                    api_responses[resp.url] = body.decode("utf-8")[:2000]
                except Exception as e:
                    print(f"  body err: {e}")

        page = await ctx.new_page()
        page.on("response", on_response)

        print("=== Step 1: load listing page ===")
        await page.goto(
            "https://www.takeaway.com/be-fr/livraison/repas/bruxelles-1000",
            wait_until="domcontentloaded",
            timeout=45000,
        )
        # CF bypass wait
        for _ in range(20):
            title = await page.title()
            if "moment" not in title.lower() and "instant" not in title.lower():
                break
            await asyncio.sleep(2)
        await asyncio.sleep(8)

        title = await page.title()
        print(f"Title: {title}")
        print(f"XHR intercepted: {len(api_responses)} cw-api calls")

        # --- Approach B: page.evaluate fetch from takeaway.com domain ---
        print("\n=== Step 2: page.evaluate fetch from takeaway.com context ===")
        fetch_result = await page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch("{CW_URL}", {{
                        method: "GET",
                        headers: {{
                            "Accept": "application/json",
                            "Accept-Language": "fr-BE,fr;q=0.9",
                            "X-Country-Code": "BE",
                            "X-Language-Code": "fr",
                        }},
                        credentials: "include"
                    }});
                    const status = r.status;
                    const ct = r.headers.get("content-type") || "";
                    let body;
                    try {{ body = await r.text(); }} catch(e) {{ body = "body read error: " + e; }}
                    return {{ status, ct, body: body.slice(0, 3000), ok: r.ok }};
                }} catch(e) {{
                    return {{ error: String(e) }};
                }}
            }}
        """)
        print(f"Result: {json.dumps(fetch_result, indent=2)[:1000]}")

        # --- Approach C: navigate directly to cw-api URL ---
        print("\n=== Step 3: navigate directly to cw-api URL ===")
        api_page = await ctx.new_page()

        api_data = {}

        async def on_api_response(resp):
            if "cw-api" in resp.url and "bypostcode" in resp.url:
                print(f"  [DIRECT NAV RESP] {resp.status} {resp.url[:120]}")
                try:
                    body = await resp.body()
                    api_data["body"] = body.decode("utf-8")[:3000]
                    api_data["status"] = resp.status
                    api_data["ct"] = resp.headers.get("content-type", "")
                except Exception as e:
                    print(f"  body err: {e}")

        api_page.on("response", on_api_response)

        try:
            await api_page.goto(CW_URL + "?serviceType=delivery", wait_until="domcontentloaded", timeout=30000)
            content = await api_page.content()
            print(f"Nav result: {content[:500]}")
            if api_data:
                print(f"Intercepted response: status={api_data.get('status')}, ct={api_data.get('ct')}")
                print(f"Body: {api_data.get('body', '')[:500]}")
        except Exception as e:
            print(f"Nav error: {e}")

        # --- Approach D: route/bypass CF by setting cookies manually ---
        # Get all cookies CF set during the main page load
        all_cookies = await ctx.cookies()
        print(f"\n=== All cookies after page load ({len(all_cookies)}) ===")
        for c in all_cookies:
            print(f"  {c['domain']} | {c['name']} = {c['value'][:40]}")

        # Check for __cf_bm or cf_clearance on .takeaway.com
        cf_cookies = [c for c in all_cookies if "cf" in c["name"].lower()]
        print(f"\nCF cookies: {cf_cookies}")

        await browser.close()

    if api_responses:
        print("\n=== cw-api XHR responses captured ===")
        for url, body in api_responses.items():
            print(f"  {url}: {body[:500]}")


if __name__ == "__main__":
    asyncio.run(main())
