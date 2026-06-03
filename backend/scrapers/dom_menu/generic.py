"""
Generic DOM menu extractor: JSON-LD first, then price-proximity heuristic.
Runs inside a Playwright browser page.
"""
from __future__ import annotations

import asyncio
import re
from typing import Callable
from urllib.parse import urlparse

from scrapers.base import new_page

# ── Noise filter ──────────────────────────────────────────────────────────────

_NOISE_RE = re.compile(
    r'livraison|delivery|minimum|commande min|bestelling|frais de port'
    r'|frais de livr|tip|pourboire|total|sous-total|subtotal'
    r'|service fee|order fee|coupon|promo|reduction|réduction|discount',
    re.IGNORECASE,
)

# ── JS that runs inside the page ──────────────────────────────────────────────

_EXTRACT_JS = r"""
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

    // ── 2. Price-proximity heuristic ────────────────────────────────────────
    const PRICE_RE = /(?:€\s*|EUR\s*)(\d+[,.]\d{2})|(\d+[,.]\d{2})\s*(?:€|EUR)/i;
    const NOISE_RE = /livraison|delivery|minimum|frais|tip|total|sous.total|subtotal|coupon|promo/i;
    const ITEM_TAGS = new Set(['LI', 'ARTICLE', 'TR', 'DIV', 'SECTION']);

    function parseEur(text) {
        const m = text.match(PRICE_RE);
        if (!m) return null;
        const raw = (m[1] || m[2]).replace(',', '.');
        const v = parseFloat(raw);
        return (v >= 1 && v <= 200) ? v : null;
    }

    function getCategory(el) {
        let current = el;
        for (let depth = 0; depth < 8; depth++) {
            let sib = current.previousElementSibling;
            while (sib) {
                if (/^H[1-4]$/.test(sib.tagName)) {
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
                const stripped = (el.textContent || '')
                    .replace(/\d+[,.]\d{2}/g, '').replace(/€|EUR/gi, '').trim();
                if (stripped.length >= 4) return el;
            }
            el = el.parentElement;
        }
        return null;
    }

    function extractName(container) {
        const full = container.textContent || '';
        const stripped = full
            .replace(/(?:€\s*|EUR\s*)\d+[,.]\d{2}/gi, '')
            .replace(/\d+[,.]\d{2}\s*(?:€|EUR)/gi, '')
            .replace(/\s+/g, ' ').trim();
        const parts = stripped
            .split(/[|\n\r\t•·\-]{1,3}/)
            .map(p => p.trim())
            .filter(p => p.length >= 3 && p.length <= 120);
        return parts[0] || null;
    }

    const seen = new Set();
    const items = [];
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
        if (NOISE_RE.test(container.textContent || '')) continue;

        const name = extractName(container);
        if (!name || name.length < 3) continue;

        const key = `${name.toLowerCase()}|${price}`;
        if (seen.has(key)) continue;
        seen.add(key);

        items.push({
            title: name,
            price: price,
            catalog_name: getCategory(container),
            description: null,
            image_url: null,
        });
        if (items.length >= 200) break;
    }
    return {source: 'dom_heuristic', items};
})()
"""


def _validate_items(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        title = (item.get("title") or "").strip()
        price = item.get("price")
        if not title or len(title) < 3 or len(title) > 120:
            continue
        if price is None or not (1.0 <= float(price) <= 200.0):
            continue
        if _NOISE_RE.search(title):
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


async def scrape_url(url: str, browser, log: Callable) -> list[dict]:
    """Load URL with Playwright, extract menu items. Returns [] on any error."""
    if urlparse(url).scheme not in ("http", "https"):
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

        raw_items = (result or {}).get("items", [])
        source = (result or {}).get("source", "?")
        items = _validate_items(raw_items)
        log(f"    source={source} raw={len(raw_items)} valid={len(items)}")
        return items
    finally:
        await page.close()
