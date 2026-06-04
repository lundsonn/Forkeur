"""
Fee refresh scraper — updates delivery_fee + min_order for existing platform_listings.

UberEats:  load feed at Brussels address, capture fareInfo per restaurant, match by
           store UUID extracted from the stored listing URL.
Deliveroo: visit each known menu URL via Playwright, extract fee + min_order via DOM.
"""
from __future__ import annotations
import asyncio
import json
import re
from typing import Callable

from scrapers.base import browser_session, new_page, check_cloudflare, noop_log, CloudflareBlockedError
import db

_BRUSSELS_ADDRESS = "Rue de la Loi 16, Bruxelles"


# ── UberEats ────────────────────────────────────────────────────────────────

async def run_ubereats(log_fn: Callable[[str], None] = noop_log) -> int:
    """Re-load UberEats feed to capture fareInfo for known listings. Returns update count."""
    log_fn("Fees/UberEats: loading feed")
    updated = 0

    async with browser_session(lang="fr-BE") as browser:
        page = await new_page(browser, lang="fr-BE")
        feed_pages: list[str] = []

        async def _capture(response):
            if "getFeedV1" in response.url:
                try:
                    feed_pages.append(await response.text())
                except Exception:
                    pass

        page.on("response", _capture)
        await page.goto("https://www.ubereats.com/", wait_until="domcontentloaded", timeout=60000)
        check_cloudflare(await page.title())

        input_sel = "#location-typeahead-home-input"
        await page.wait_for_selector(input_sel, timeout=20000)
        await page.click(input_sel)
        await page.type(input_sel, _BRUSSELS_ADDRESS, delay=60)
        await asyncio.sleep(3)
        try:
            await page.wait_for_selector('[role="option"]', timeout=5000)
        except Exception:
            pass
        await page.keyboard.press("ArrowDown")
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        try:
            await page.wait_for_url("**/restaurants**", timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(2)

        deadline = asyncio.get_event_loop().time() + 15
        while not feed_pages and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.5)

        prev, stale = 0, 0
        while stale < 4:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2.5)
            cur = len(feed_pages)
            stale = stale + 1 if cur == prev else 0
            prev = cur

        page.remove_listener("response", _capture)
        log_fn(f"Fees/UberEats: {len(feed_pages)} feed pages captured")

        # Parse fareInfo keyed by storeUuid
        fare_by_uuid: dict[str, dict] = {}
        for raw in feed_pages:
            try:
                feed = json.loads(raw)
            except Exception:
                continue
            for item in feed.get("data", {}).get("feedItems", []):
                if item.get("type") != "REGULAR_STORE":
                    continue
                s = item.get("store", {})
                uuid = s.get("storeUuid") or item.get("uuid") or ""
                if not uuid or uuid in fare_by_uuid:
                    continue
                tracking = s.get("tracking") or {}
                payload = tracking.get("storePayload") or {}
                fare = payload.get("fareInfo") or {}
                fare_by_uuid[uuid] = fare

        log_fn(f"Fees/UberEats: {len(fare_by_uuid)} unique stores with fareInfo")

        # Match listings by UUID (last path segment of URL)
        listings = db.get_listings_with_urls("uber_eats")
        for listing in listings:
            url = listing.get("url") or ""
            uuid = url.rstrip("/").split("/")[-1]
            fare = fare_by_uuid.get(uuid)
            if fare is None:
                continue
            updates: dict = {}
            fee = fare.get("serviceFee")
            min_order = fare.get("minOrderSubtotal")
            if isinstance(fee, (int, float)):
                updates["delivery_fee"] = round(float(fee), 2)
            if isinstance(min_order, (int, float)):
                updates["min_order"] = round(float(min_order), 2)
            if updates:
                db.patch_listing(listing["id"], updates)
                updated += 1

        log_fn(f"Fees/UberEats: updated {updated} listings")
        return updated


# ── Deliveroo ────────────────────────────────────────────────────────────────

_DOM_FEE_SCRIPT = r"""() => {
    let fee = null, minOrder = null;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
        const t = node.textContent.trim();
        if (!t || t.length > 120) continue;

        if (!fee) {
            const hasDeliveryWord = /livraison|delivery|bezorging|frais/i.test(t);
            const hasFreeWord = /offert|gratuit|gratis|free/i.test(t);
            const hasPrice = /\d[,.]\d/.test(t);
            if (hasDeliveryWord && (hasPrice || hasFreeWord)) fee = t;
        }
        // Min order: "5,00 € minimum" or "minimum: 5,00 €"
        if (!minOrder && /minimum/i.test(t) && /\d[,.]\d/.test(t)) minOrder = t;

        if (fee && minOrder) break;
    }
    return [fee, minOrder];
}"""


async def _setup_deliveroo_address(page, log_fn: Callable[[str], None]) -> bool:
    """Navigate to Deliveroo and select Brussels address. Returns True on success."""
    try:
        await page.goto("https://deliveroo.be/fr", wait_until="domcontentloaded", timeout=60000)
        check_cloudflare(await page.title())
        try:
            await page.click('button:has-text("Accept all"), button:has-text("Tout accepter")', timeout=4000)
            await asyncio.sleep(0.5)
        except Exception:
            pass
        input_sel = 'input[id="location-search"], input[placeholder*="address" i], input[placeholder*="adresse" i]'
        await page.wait_for_selector(input_sel, timeout=10000)
        await page.click(input_sel)
        await page.type(input_sel, _BRUSSELS_ADDRESS, delay=60)
        suggestion_sel = "li.ccl-ee4ea4aaab604785"
        try:
            await page.wait_for_selector(suggestion_sel, timeout=8000)
            await page.click(suggestion_sel)
        except Exception:
            await asyncio.sleep(2)
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")
        try:
            await page.wait_for_url("**/restaurants**", timeout=20000)
        except Exception:
            pass
        log_fn("Fees/Deliveroo: address set, on restaurants page")
        return True
    except Exception as exc:
        log_fn(f"Fees/Deliveroo: address setup failed: {exc}")
        return False


async def run_deliveroo(log_fn: Callable[[str], None] = noop_log) -> int:
    """Visit each Deliveroo menu URL to update delivery_fee + min_order. Returns update count."""
    listings = db.get_listings_with_urls("deliveroo")
    log_fn(f"Fees/Deliveroo: {len(listings)} listings to check")
    if not listings:
        return 0

    updated = 0
    n = len(listings)

    async with browser_session(lang="fr-BE") as browser:
        page = await new_page(browser, lang="fr-BE")

        # Must set address first so Deliveroo shows delivery fee on menu pages
        ok = await _setup_deliveroo_address(page, log_fn)
        if not ok:
            log_fn("Fees/Deliveroo: aborting — could not set address")
            return 0

        for i, listing in enumerate(listings):
            url = listing.get("url")
            if not url:
                continue
            log_fn(f"Fees/Deliveroo: {i + 1}/{n} — {url[:70]}")
            try:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
                try:
                    await page.wait_for_url("**/menu/**", timeout=8000)
                except Exception:
                    pass
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(1.5)
                check_cloudflare(await page.title())

                fee_text, min_text = await page.evaluate(_DOM_FEE_SCRIPT)

                updates: dict = {}
                fee = _parse_money(fee_text)
                if fee is not None:
                    updates["delivery_fee"] = fee
                min_val = _parse_money(min_text)
                if min_val is not None:
                    updates["min_order"] = min_val

                if updates:
                    db.patch_listing(listing["id"], updates)
                    updated += 1
                    log_fn(f"  → fee={updates.get('delivery_fee')} min={updates.get('min_order')}")
                else:
                    log_fn("  → no fee data found")

            except CloudflareBlockedError:
                log_fn("  → CF blocked, skipping")
            except Exception as exc:
                log_fn(f"  → error: {exc}")

        log_fn(f"Fees/Deliveroo: updated {updated} listings")
        return updated


# ── Takeaway ─────────────────────────────────────────────────────────────────

_DOM_TAKEAWAY_SCRIPT = r"""() => {
    let fee = null, minOrder = null;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
        const t = node.textContent.trim();
        if (!t || t.length > 120) continue;

        if (!fee) {
            const hasDeliveryWord = /livraison|delivery|bezorging|frais/i.test(t);
            const hasFreeWord = /gratuit|gratis|free|offert/i.test(t);
            const hasPrice = /\d[,.]\d/.test(t);
            if (hasDeliveryWord && (hasPrice || hasFreeWord)) fee = t;
        }
        if (!minOrder && /minimum|min\./i.test(t) && /\d[,.]\d/.test(t)) minOrder = t;

        if (fee && minOrder) break;
    }
    return [fee, minOrder];
}"""


async def run_takeaway(log_fn: Callable[[str], None] = noop_log) -> int:
    """Visit each Takeaway menu URL to update delivery_fee + min_order. Returns update count."""
    listings = db.get_listings_with_urls("takeaway")
    log_fn(f"Fees/Takeaway: {len(listings)} listings to check")
    if not listings:
        return 0

    updated = 0
    n = len(listings)

    async with browser_session(lang="fr-BE") as browser:
        page = await new_page(browser, lang="fr-BE")

        for i, listing in enumerate(listings):
            url = listing.get("url")
            if not url:
                continue
            log_fn(f"Fees/Takeaway: {i + 1}/{n} — {url[:70]}")
            try:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
                try:
                    await page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
                await asyncio.sleep(1.5)

                # Accept cookie banner if present
                try:
                    await page.click(
                        'button:has-text("Accept"), button:has-text("Accepter"), '
                        'button[data-testid*="accept"]',
                        timeout=3000,
                    )
                    await asyncio.sleep(0.5)
                except Exception:
                    pass

                fee_text, min_text = await page.evaluate(_DOM_TAKEAWAY_SCRIPT)

                updates: dict = {}
                fee = _parse_money(fee_text)
                if fee is not None:
                    updates["delivery_fee"] = fee
                min_val = _parse_money(min_text)
                if min_val is not None:
                    updates["min_order"] = min_val

                if updates:
                    db.patch_listing(listing["id"], updates)
                    updated += 1
                    log_fn(f"  → fee={updates.get('delivery_fee')} min={updates.get('min_order')}")
                else:
                    log_fn("  → no fee data found")

            except Exception as exc:
                log_fn(f"  → error: {exc}")

        log_fn(f"Fees/Takeaway: updated {updated} listings")
        return updated


# ── Combined entry point ─────────────────────────────────────────────────────

async def run(log_fn: Callable[[str], None] = noop_log) -> dict[str, int]:
    """Run fee refresh for all platforms. Returns {platform: updated_count}."""
    ue = await run_ubereats(log_fn)
    dr = await run_deliveroo(log_fn)
    tw = await run_takeaway(log_fn)
    return {"uber_eats": ue, "deliveroo": dr, "takeaway": tw}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_money(val: str | None) -> float | None:
    if val is None:
        return None
    if val == "0":
        return 0.0
    low = val.lower()
    if any(w in low for w in ("gratuit", "free", "gratis", "offert")):
        return 0.0
    m = re.search(r"(\d+)[,.](\d{2})", val)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"(\d+)", val)
    return float(m.group(1)) if m else None
