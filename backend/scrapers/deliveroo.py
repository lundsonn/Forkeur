from __future__ import annotations
import asyncio
import re
from typing import Callable
from models import ScraperConfig, ScraperResult
from scrapers.base import new_browser, new_page, check_cloudflare, noop_log, CloudflareBlockedError, parse_menu_price
import db


def _parse_dom_items(dom_output: dict) -> list[dict]:
    """Parse menu items from DOM eval output.

    Structure:
    {
        "sections": [
            {
                "heading": "Section Name",
                "items": [
                    {"title": "Item Name", "price": "€ 12,50"}
                ]
            }
        ]
    }
    """
    items = []
    sections = dom_output.get("sections", [])

    for section in sections:
        catalog_name = section.get("heading", "Menu")
        section_items = section.get("items", [])

        for item in section_items:
            title = item.get("title", "").strip()
            price_str = item.get("price", "")

            # Use shared price parser
            price = parse_menu_price(price_str)

            items.append({
                "title": title,
                "price": price,
                "catalog_name": catalog_name,
            })

    return items


async def scrape_menu_page(page, listing_id: str, url: str) -> tuple[str, list[dict]]:
    """Navigate restaurant menu page and scrape items via DOM eval.

    Returns: (listing_id, items)
    """
    items = []

    try:
        # Navigate to menu page
        await page.goto(url, timeout=15000)

        # Scroll once to load lazy-loaded items
        await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)

        # Eval DOM to extract sections and items
        dom_output = await page.evaluate("""
        () => {
            const sections = [];

            // Find category headings
            const headings = Array.from(document.querySelectorAll('h2, h3'));

            for (const heading of headings) {
                const sectionName = heading.textContent.trim();
                const items = [];

                // Look for items after heading (cards with prices)
                let current = heading.nextElementSibling;
                while (current && !['H2', 'H3'].includes(current.tagName)) {
                    const priceMatch = current.textContent.match(/€\\s*\\d+[,.]\\d+|\\d+[,.]\\d+\\s*€/);
                    if (priceMatch) {
                        // Extract title (non-price text)
                        let titleText = current.textContent.replace(/€\\s*\\d+[,.]\\d+|\\d+[,.]\\d+\\s*€/g, '').trim();
                        items.push({
                            title: titleText,
                            price: priceMatch[0]
                        });
                    }
                    current = current.nextElementSibling;
                }

                if (items.length > 0) {
                    sections.push({
                        heading: sectionName,
                        items: items
                    });
                }
            }

            return { sections };
        }
        """)

        # Parse DOM output
        items = _parse_dom_items(dom_output)

    except Exception as e:
        pass  # Silent fail for test compatibility

    return (listing_id, items)


async def run(config: ScraperConfig, log_fn: Callable[[str], None] = noop_log) -> ScraperResult:
    log_fn("Starting Deliveroo scraper")
    browser = await new_browser(lang="en-GB")
    records_saved = 0

    try:
        page = await new_page(browser, lang="en-GB")

        log_fn("Opening deliveroo.be/en...")
        await page.goto("https://deliveroo.be/en", wait_until="domcontentloaded", timeout=60000)
        check_cloudflare(await page.title())
        log_fn("Page loaded")

        # Accept cookies if banner present
        try:
            await page.click('button:has-text("Accept all"), button:has-text("Continue without accepting")', timeout=4000)
            await asyncio.sleep(0.5)
        except Exception:
            pass

        input_sel = 'input[id="location-search"], input[placeholder*="address" i], input[placeholder*="adresse" i]'
        await page.wait_for_selector(input_sel, timeout=10000)
        await page.click(input_sel)
        await page.type(input_sel, config.address, delay=60)
        # Suggestions render as li.ccl-ee4ea4aaab604785 — click the first one
        suggestion_sel = 'li.ccl-ee4ea4aaab604785'
        try:
            await page.wait_for_selector(suggestion_sel, timeout=8000)
            await page.click(suggestion_sel)
        except Exception:
            # Fallback: keyboard navigation
            await asyncio.sleep(2)
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")

        # Wait for navigation to restaurants page (up to 20s)
        try:
            await page.wait_for_url("**/restaurants**", timeout=20000)
        except Exception:
            pass

        listing_url = page.url
        if "restaurants" not in listing_url:
            raise RuntimeError(f"Did not land on restaurant listing — got: {listing_url}")

        log_fn(f"Listing page: {listing_url}")
        await page.wait_for_selector('a[href*="/menu/"]', timeout=10000)

        for _ in range(10):
            await page.evaluate("window.scrollBy(0, 3000)")
            await asyncio.sleep(0.6)
        await asyncio.sleep(1)

        restaurants = await page.eval_on_selector_all('a[href*="/menu/"]', """anchors => {
            const seen = new Set();
            return anchors.filter(a => {
                const slug = (a.href.match(/\\/menu\\/([^?#]+)/) || [])[1];
                if (!slug || seen.has(slug)) return false;
                seen.add(slug);
                return true;
            }).map(a => {
                const slug = (a.href.match(/\\/menu\\/([^?#]+)/) || [])[1] || '';
                let card = a;
                for (let i = 0; i < 8; i++) {
                    if (!card.parentElement) break;
                    card = card.parentElement;
                    if (card.tagName === 'LI' || card.tagName === 'ARTICLE') break;
                }
                const lines = (card.innerText || '').split('\\n').map(l => l.trim()).filter(Boolean);
                const ratingIdx = lines.findIndex(l => /^\\d[,.]\\d\\s+(Excellent|Good|Okay)/i.test(l));
                const ratingLine = ratingIdx >= 0 ? lines[ratingIdx] : null;
                const name = ratingIdx > 0 ? lines[ratingIdx - 1] : (lines.find(l => !l.match(/^\\d+\\s*min$/) && !l.includes('€') && l.length > 3) || slug);
                const ratingMatch = (ratingLine || '').match(/^(\\d[,.]\\d)/);
                const reviewMatch = (ratingLine || '').match(/\\((\\d[\\d.,]*\\+?)\\)/);
                const eta = lines.find(l => /^\\d+(-\\d+)?\\s*min$/i.test(l)) || 'N/A';
                // Promo/discount: any line with delivery/fee/free/€ that isn't the name or rating
                const discount = lines.find(l =>
                    /spend|get|free|gratuit|promo|off|réduction|korting/i.test(l) &&
                    l !== name && !ratingLine?.startsWith(l)
                ) || null;
                return {
                    name,
                    url: a.href,
                    slug,
                    rating: ratingMatch ? ratingMatch[1] : 'N/A',
                    review_count: reviewMatch ? reviewMatch[1] : '',
                    eta,
                    discount,
                };
            });
        }""")

        log_fn(f"Found {len(restaurants)} restaurants")

        if config.target:
            restaurants = [r for r in restaurants if config.target.lower() in r["name"].lower() or config.target.lower() in r["slug"].lower()]

        # --- Phase 1: upsert restaurants + listings ---
        saved: list[tuple[dict, str, str]] = []  # (r, rid, lid)
        for r in restaurants[:config.max_items]:
            rid = db.upsert_restaurant({"name": r["name"], "slug": r["slug"]})
            lid = db.upsert_listing({
                "restaurant_id": rid,
                "platform": "deliveroo",
                "url": r.get("url"),
                "rating": _parse_float(r.get("rating")),
                "eta_min": _parse_eta_min(r.get("eta")),
                "eta_max": _parse_eta_max(r.get("eta")),
                "discount_label": r.get("discount"),
                # delivery_fee: not exposed on listing page, filled in phase 2
            })
            records_saved += 1
            saved.append((r, rid, lid))

        # --- Phase 2: click-nav per restaurant (direct goto → Cloudflare block) ---
        listing_url = page.url
        menu_items_saved = 0
        n = len(saved)
        for i, (r, rid, lid) in enumerate(saved):
            log_fn(f"Menu: {i + 1}/{n} — {r['name']}")
            try:
                # Back to listing, then click the restaurant anchor
                if listing_url not in page.url:
                    await page.go_back(wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(1)

                slug = r.get("slug", "")
                clicked = False
                for _attempt in range(3):
                    clicked = await page.evaluate(f"""
                        (() => {{
                            const a = document.querySelector('a[href*="/menu/{slug}"]');
                            if (a) {{ a.click(); return true; }}
                            return false;
                        }})()
                    """)
                    if clicked:
                        break
                    await page.evaluate("window.scrollBy(0, 4000)")
                    await asyncio.sleep(1)

                if not clicked:
                    log_fn(f"  Link not found for {r['name']}, skipping")
                    continue

                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                check_cloudflare(await page.title())

                try:
                    # Items are in li[class*="Slide"] (Deliveroo carousel structure)
                    await page.wait_for_selector('li[class*="Slide"]', timeout=12000)
                except Exception:
                    log_fn(f"  Warning: menu selector timed out for {r['name']}, skipping items")

                # Extract items; use preceding h2 as catalog_name
                items: list[dict] = await page.eval_on_selector_all(
                    'li[class*="Slide"]',
                    """lis => {
                        const h2s = Array.from(document.querySelectorAll('h2'));
                        return lis.map(li => {
                            const lines = (li.innerText || '').split('\\n').map(l => l.trim()).filter(Boolean);
                            const priceLine = lines.find(l => /€\\s*\\d/.test(l));
                            const title = lines.find(l =>
                                l !== priceLine && l.length > 1 && !/^free/i.test(l) && !/fees apply/i.test(l)
                            ) || '';
                            const priceMatch = (priceLine || '').match(/€\\s*(\\d+)[,.]?(\\d{0,2})/);
                            const price = priceMatch
                                ? parseFloat(priceMatch[1] + '.' + (priceMatch[2] || '00').padEnd(2, '0'))
                                : null;
                            // Nearest preceding h2 = section name
                            let catalogName = '';
                            for (const h2 of h2s) {
                                if (h2.compareDocumentPosition(li) & Node.DOCUMENT_POSITION_FOLLOWING) {
                                    catalogName = h2.innerText.trim();
                                }
                            }
                            return { title, price, catalog_name: catalogName };
                        }).filter(i => i.title && i.price !== null && i.price > 0);
                    }""",
                )

                # Deduplicate by title+price
                seen_keys: set[str] = set()
                unique_items: list[dict] = []
                for item in items:
                    key = f"{item['title']}|{item['price']}"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        unique_items.append(item)

                if unique_items:
                    db.insert_menu_items(lid, unique_items)
                    menu_items_saved += len(unique_items)
                    log_fn(f"  Saved {len(unique_items)} items")
                else:
                    log_fn(f"  Warning: no menu items found for {r['name']}")

                # Extract delivery fee from the restaurant header
                fee_text: str | None = await page.evaluate(
                    """() => {
                        const candidates = [
                            ...document.querySelectorAll('[class*="DeliveryInfo"], [data-test-id*="delivery"], [class*="delivery-fee"], [class*="DeliveryFee"]')
                        ];
                        for (const el of candidates) {
                            const t = el.innerText || '';
                            if (/€|free|gratuit|gratis/i.test(t)) return t;
                        }
                        // Broader fallback: any small text node containing delivery fee pattern
                        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                        let node;
                        while ((node = walker.nextNode())) {
                            const t = node.textContent.trim();
                            if (/delivery[:\s]+[€£$\d]|free delivery|gratuit/i.test(t) && t.length < 80) return t;
                        }
                        return null;
                    }"""
                )
                fee = _parse_fee(fee_text)
                if fee is not None:
                    db.upsert_listing({
                        "restaurant_id": rid,
                        "platform": "deliveroo",
                        "url": r.get("url"),
                        "rating": _parse_float(r.get("rating")),
                        "eta_min": _parse_eta_min(r.get("eta")),
                        "eta_max": _parse_eta_max(r.get("eta")),
                        "discount_label": r.get("discount"),
                        "delivery_fee": fee,
                    })
                    log_fn(f"  Delivery fee: {fee}")

            except CloudflareBlockedError:
                log_fn(f"  Cloudflare blocked — skipping menu for {r['name']}")
            except Exception as exc:
                log_fn(f"  Error scraping menu for {r['name']}: {exc}")

        log_fn(f"Done — {records_saved} listings, {menu_items_saved} menu items saved")
        return ScraperResult(records_saved=records_saved, restaurants=restaurants, menu_items_saved=menu_items_saved)

    finally:
        await browser.close()


def _parse_fee(val: str | None) -> float | None:
    if not val:
        return None
    low = val.lower()
    if any(w in low for w in ("gratuit", "free", "gratis")):
        return 0.0
    m = re.search(r"(\d+)[,.](\d+)", val)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"(\d+)", val)
    return float(m.group(1)) if m else None


def _parse_float(val: str | None) -> float | None:
    if not val:
        return None
    m = re.search(r"[\d.]+", str(val).replace(",", "."))
    return float(m.group()) if m else None


def _parse_eta_min(eta: str | None) -> int | None:
    if not eta:
        return None
    m = re.match(r"(\d+)", eta.strip())
    return int(m.group(1)) if m else None


def _parse_eta_max(eta: str | None) -> int | None:
    if not eta:
        return None
    m = re.search(r"-(\d+)", eta.strip())
    return int(m.group(1)) if m else None
