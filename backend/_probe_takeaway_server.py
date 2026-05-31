"""
Verify the Takeaway scraper works on the server (Xvfb + proxy + geo).
Does NOT write to Supabase — stdout only.

Run:
    cd /opt/forkeur/backend
    uv run python _probe_takeaway_server.py

If DISPLAY is missing and pyvirtualdisplay install failed, use:
    xvfb-run -a uv run python _probe_takeaway_server.py
"""
from __future__ import annotations
import asyncio
import sys

# One known Brussels restaurant from the DB — used as the single test target.
TEST_URL = "https://www.takeaway.com/be-fr/menu/fritiko-rue-neuve"

# DOM eval reused from takeaway.py (same selectors — do not change here).
_MENU_EVAL = """
() => {
    const sections = [];
    const nodes = Array.from(document.querySelectorAll(
        '[data-qa="heading"], [data-qa="card-element"]'
    ));
    let heading = 'Menu';
    let cur = null;
    for (const node of nodes) {
        const qa = node.getAttribute('data-qa');
        if (qa === 'heading') {
            heading = (node.innerText || '').trim() || 'Menu';
            continue;
        }
        const nameEl = node.querySelector('[data-qa="item-name"]');
        const priceEl = node.querySelector('[data-qa="item-price"]');
        if (!nameEl || !priceEl) continue;
        const title = (nameEl.innerText || '').trim();
        const price = (priceEl.innerText || '').trim();
        if (!title) continue;
        if (!cur || cur.heading !== heading) {
            cur = { heading, items: [] };
            sections.push(cur);
        }
        cur.items.push({ title, price });
    }
    return { sections };
}
"""


async def main() -> None:
    from scrapers.base import new_browser, new_page, wait_for_cf_clear

    print(f"[probe] target: {TEST_URL}")
    print("[probe] launching headed Chromium (Xvfb auto-started if no DISPLAY)...")

    browser = await new_browser(lang="fr-BE", headed=True)
    try:
        page = await new_page(browser, lang="fr-BE")

        print("[probe] navigating...")
        await page.goto(TEST_URL, wait_until="domcontentloaded", timeout=60_000)

        title = await page.title()
        url = page.url
        cf_hit = "just a moment" in title.lower() or "cloudflare" in title.lower()
        print(f"[probe] CF challenge on load: {cf_hit}  (title={title!r}  url={url})")

        if cf_hit:
            print("[probe] clearing CF challenge (up to 90s)...")
            cleared = await wait_for_cf_clear(page, timeout_s=90)
            if not cleared:
                title = await page.title()
                print(f"[probe] FAILED — CF not cleared. title={title!r}  url={page.url}")
                sys.exit(1)
            print("[probe] CF cleared")
        else:
            print("[probe] no CF challenge — page loaded directly")

        # Wait for network to settle, then first card.
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass

        try:
            await page.wait_for_selector('[data-qa="card-element"]', timeout=20_000)
        except Exception:
            print("[probe] FAILED — no [data-qa=card-element] after 20s")
            print(f"[probe] page title: {await page.title()!r}  url: {page.url}")
            sys.exit(1)

        _count_js = "document.querySelectorAll('[data-qa=\"card-element\"]').length"
        count_before = await page.evaluate(_count_js)
        print(f"[probe] items before scroll: {count_before}")

        # Phase 1: height-based scroll.
        prev_h = 0
        for _ in range(20):
            h = await page.evaluate("document.body.scrollHeight")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(600)
            if h == prev_h:
                break
            prev_h = h

        # Phase 2: item-count-based scroll.
        prev_cnt = 0
        for _ in range(15):
            cur_cnt = await page.evaluate(_count_js)
            if cur_cnt == prev_cnt:
                break
            prev_cnt = cur_cnt
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(700)
        await page.wait_for_timeout(500)

        count_after = await page.evaluate(_count_js)
        print(f"[probe] items after scroll: {count_after}  (delta +{count_after - count_before})")

        dom = await page.evaluate(_MENU_EVAL)
        items = [
            {"title": i["title"], "price": i["price"], "section": s["heading"]}
            for s in dom.get("sections", [])
            for i in s.get("items", [])
        ]

        print(f"[probe] menu items parsed: {len(items)}")
        if not items:
            print("[probe] FAILED — 0 items")
            sys.exit(1)

        print("[probe] first 3 items:")
        for item in items[:3]:
            print(f"  [{item['section']}] {item['title']}  →  {item['price']}")

        print("[probe] SUCCESS")

    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
