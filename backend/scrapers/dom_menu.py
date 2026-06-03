"""
Generic DOM menu scraper for restaurant websites with no structured API.
Strategy: JSON-LD first (reliable), then price-proximity heuristic (Playwright).
Targets platform_listings where platform='direct' and url_type IN ('website','menu').
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Callable
from urllib.parse import urlparse

from models import ScraperConfig, ScraperResult
from scrapers.base import new_browser, new_page, noop_log
import db

# ── Price pattern ─────────────────────────────────────────────────────────────

_PRICE_RE = re.compile(
    r'(?:€\s*|EUR\s*)(\d+[,.]?\d*)'
    r'|(\d+[,.]?\d*)\s*(?:€|EUR)',
    re.IGNORECASE,
)

# Noise keywords — skip price elements whose container includes these
_NOISE_RE = re.compile(
    r'livraison|delivery|minimum|commande min|bestelling|frais de port'
    r'|frais de livr|tip|pourboire|total|sous-total|subtotal'
    r'|service fee|order fee|coupon|promo|reduction|réduction|discount',
    re.IGNORECASE,
)

# ── JS extraction (runs inside Playwright page) ───────────────────────────────

_EXTRACT_JS = """
(function() {
    // ── 1. JSON-LD ──────────────────────────────────────────────────────────
    const jsonLdItems = [];
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
        try {
            const entries = [].concat(JSON.parse(s.textContent));
            for (const entry of entries) {
                if (entry['@type'] === 'Menu') {
                    for (const section of (entry.hasMenuSection || [])) {
                        const cat = section.name || 'Menu';
                        for (const item of (section.hasMenuItem || [])) {
                            const price = item.offers && item.offers.price;
                            if (item.name && price != null) {
                                jsonLdItems.push({
                                    title: item.name.trim(),
                                    price: parseFloat(String(price).replace(',','.')),
                                    catalog_name: cat,
                                    description: item.description || null,
                                    image_url: item.image || null,
                                });
                            }
                        }
                    }
                } else if (entry['@type'] === 'MenuItem') {
                    const price = entry.offers && entry.offers.price;
                    if (entry.name && price != null) {
                        jsonLdItems.push({
                            title: entry.name.trim(),
                            price: parseFloat(String(price).replace(',','.')),
                            catalog_name: 'Menu',
                            description: entry.description || null,
                            image_url: entry.image || null,
                        });
                    }
                }
            }
        } catch(e) {}
    }
    if (jsonLdItems.length >= 3) return {source: 'json_ld', items: jsonLdItems};

    // ── 2. DOM heuristic ────────────────────────────────────────────────────
    const PRICE_RE = /(?:€\\s*|EUR\\s*)(\\d+[,.]\\d{2})/i;
    const NOISE_RE = /livraison|delivery|minimum|frais|tip|total|sous.total|subtotal|coupon|promo/i;

    // Container tags that typically wrap a single menu item
    const ITEM_TAGS = new Set(['LI', 'ARTICLE', 'TR', 'DIV', 'SECTION']);

    function parseEur(text) {
        const m = text.match(/(?:€\\s*|EUR\\s*)(\\d+[,.]\\d{2})|(\\d+[,.]\\d{2})\\s*(?:€|EUR)/i);
        if (!m) return null;
        const raw = (m[1] || m[2]).replace(',', '.');
        const v = parseFloat(raw);
        return (v >= 1 && v <= 200) ? v : null;
    }

    function getCategory(el) {
        // Walk siblings above and then parent's siblings above
        let current = el;
        for (let depth = 0; depth < 8; depth++) {
            let sib = current.previousElementSibling;
            while (sib) {
                const tag = sib.tagName;
                if (/^H[1-4]$/.test(tag)) {
                    const text = sib.textContent.trim();
                    if (text.length >= 2 && text.length <= 60) return text;
                }
                sib = sib.previousElementSibling;
            }
            current = current.parentElement;
            if (!current || current === document.body) break;
        }
        return 'Menu';
    }

    function getItemContainer(priceEl) {
        let el = priceEl.parentElement;
        for (let i = 0; i < 6; i++) {
            if (!el || el === document.body) break;
            if (ITEM_TAGS.has(el.tagName)) {
                const text = el.textContent || '';
                // Container must have enough non-price text to extract a name
                const stripped = text.replace(/\\d+[,.]\\d{2}/g, '').replace(/€|EUR/gi,'').trim();
                if (stripped.length >= 4) return el;
            }
            el = el.parentElement;
        }
        return null;
    }

    function extractName(container, priceText) {
        // Get all text content, strip price-looking fragments
        const full = container.textContent || '';
        // Remove the price itself
        const stripped = full.replace(/(?:€\\s*|EUR\\s*)\\d+[,.]\\d{2}/gi, '')
                             .replace(/\\d+[,.]\\d{2}\\s*(?:€|EUR)/gi, '')
                             .replace(/\\s+/g, ' ').trim();
        // Take longest token-group that looks like a dish name
        const parts = stripped.split(/[|\\n\\r\\t•·\\-]{1,3}/).map(p => p.trim()).filter(p => p.length >= 3 && p.length <= 120);
        if (!parts.length) return null;
        // Prefer the first part (usually dish name before description)
        return parts[0] || null;
    }

    const seen = new Set();
    const items = [];

    // Walk all text nodes to find price occurrences
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    let node;
    while ((node = walker.nextNode())) {
        const text = node.textContent.trim();
        const price = parseEur(text);
        if (price === null) continue;
        if (NOISE_RE.test(text)) continue;

        const priceEl = node.parentElement;
        if (!priceEl) continue;

        const container = getItemContainer(priceEl);
        if (!container) continue;

        const containerText = container.textContent || '';
        if (NOISE_RE.test(containerText)) continue;

        const name = extractName(container, text);
        if (!name || name.length < 3) continue;

        const key = `${name.toLowerCase()}|${price}`;
        if (seen.has(key)) continue;
        seen.add(key);

        const cat = getCategory(container);
        items.push({
            title: name,
            price: price,
            catalog_name: cat,
            description: null,
            image_url: null,
        });

        if (items.length >= 200) break;
    }

    return {source: 'dom_heuristic', items};
})()
"""


# ── Python helpers ─────────────────────────────────────────────────────────────

def _parse_price(raw: str) -> float | None:
    """Parse '12,50' or '12.50' to float, return None if out of range."""
    try:
        v = float(raw.replace(",", "."))
        return v if 1.0 <= v <= 200.0 else None
    except ValueError:
        return None


def _is_noise(text: str) -> bool:
    return bool(_NOISE_RE.search(text))


def _extract_json_ld_items(html: str) -> list[dict]:
    """Pure-Python JSON-LD extraction for testing without Playwright."""
    items: list[dict] = []
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    ):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if entry.get("@type") == "Menu":
                for section in entry.get("hasMenuSection", []):
                    cat = section.get("name", "Menu")
                    for item in section.get("hasMenuItem", []):
                        price_raw = (item.get("offers") or {}).get("price")
                        if item.get("name") and price_raw is not None:
                            price = _parse_price(str(price_raw))
                            if price:
                                items.append({
                                    "title": item["name"].strip(),
                                    "price": price,
                                    "catalog_name": cat,
                                    "description": item.get("description") or None,
                                    "image_url": item.get("image") or None,
                                })
            elif entry.get("@type") == "MenuItem":
                price_raw = (entry.get("offers") or {}).get("price")
                if entry.get("name") and price_raw is not None:
                    price = _parse_price(str(price_raw))
                    if price:
                        items.append({
                            "title": entry["name"].strip(),
                            "price": price,
                            "catalog_name": "Menu",
                            "description": entry.get("description") or None,
                            "image_url": entry.get("image") or None,
                        })
    return items


def _validate_items(items: list[dict]) -> list[dict]:
    """Filter and clean extracted items."""
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        title = (item.get("title") or "").strip()
        price = item.get("price")
        if not title or len(title) < 3 or len(title) > 120:
            continue
        if price is None or not (1.0 <= float(price) <= 200.0):
            continue
        if _is_noise(title):
            continue
        key = f"{title.lower()}|{price}"
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "title": title,
            "price": round(float(price), 2),
            "catalog_name": (item.get("catalog_name") or "Menu").strip() or "Menu",
            "description": item.get("description") or None,
            "image_url": item.get("image_url") or None,
        })
    return out


# ── Playwright scraper ─────────────────────────────────────────────────────────

async def _scrape_url(url: str, log: Callable, browser) -> list[dict]:
    """Load one URL and extract menu items. Returns [] on any error."""
    # Skip non-HTTP URLs
    scheme = urlparse(url).scheme
    if scheme not in ("http", "https"):
        return []

    page = await new_page(browser)
    try:
        try:
            await page.goto(url, timeout=20_000, wait_until="domcontentloaded")
            await asyncio.sleep(2)
        except Exception as e:
            log(f"    load error: {e}")
            return []

        try:
            result = await page.evaluate(_EXTRACT_JS)
        except Exception as e:
            log(f"    eval error: {e}")
            return []

        raw_items = result.get("items", []) if result else []
        source = result.get("source", "?") if result else "?"
        items = _validate_items(raw_items)
        log(f"    source={source} raw={len(raw_items)} valid={len(items)}")
        return items

    finally:
        await page.close()


# ── Entry point ────────────────────────────────────────────────────────────────

async def run(config: ScraperConfig | None = None, log: Callable = noop_log) -> ScraperResult:
    """Scrape menus from direct listings with url_type in (website, menu)."""
    client = db.get_client()
    listings = (
        client.table("platform_listings")
        .select("id, url, url_type")
        .eq("platform", "direct")
        .in_("url_type", ["website", "menu"])
        .not_.is_("url", "null")
        .execute()
    ).data

    log(f"dom_menu: {len(listings)} website/menu listings")

    max_items = config.max_items if config else None
    if max_items:
        listings = listings[:max_items]

    total_saved = 0
    browser = await new_browser(headed=False)
    try:
        for listing in listings:
            url = listing["url"]
            log(f"  → {url[:70]}")
            items = await _scrape_url(url, log, browser)
            if not items:
                continue
            saved = db.insert_menu_items(listing["id"], items)
            total_saved += saved
            log(f"     {saved} items saved")
            await asyncio.sleep(1.0)
    finally:
        await browser.close()

    log(f"\ndone — {total_saved} total items")
    return ScraperResult(records_saved=total_saved)
