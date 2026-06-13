"""Light per-platform *presence search* for the presence probe.

A hit/miss check, NOT a scrape: it reuses each production scraper's address
handling, search entry point, and anti-bot/CF machinery (via scrapers.base) but
stops before any menu extraction and before the heavy "load every card" passes.

Each adapter returns ``(candidates, blocked, block_reason)``:
  - candidates: search-result cards near/at the restaurant's own pin
  - blocked: True if the search itself could not run to a trustworthy negative
    (Cloudflare/captcha, no feed, listing page never reached, missing pin input)
  - block_reason: short tag when blocked

``absent`` is NEVER concluded here — the adapter only reports what the search
returned; presence_probe.classify_presence turns cards into present/absent/
uncertain. A blocked search must therefore yield ``blocked=True`` so the
classifier returns ``uncertain`` (a negative can't be proven when blocked).

Coordinate availability per platform (drives match mode in the classifier):
  - uber_eats: feed cards carry venue mapMarker lat/lng -> true proximity match
  - deliveroo: card URL geohash is the *customer pin* (≈ our pin) not the venue,
    so cards carry NO usable venue coords -> name-only match (coords=None)
  - takeaway: zone listing cards carry no coords/cuisine -> name-only match
"""

from __future__ import annotations

import asyncio
import json
import re

from rapidfuzz.distance import JaroWinkler

from matching import normalize_name
from presence_probe import Candidate
from scrapers.base import (
    CloudflareBlockedError,
    check_cloudflare,
    new_page,
    noop_log,
    wait_for_cf_clear,
)

_STRONG_NAME_SIM = 0.92  # early-exit threshold (a confident on-pin name hit)

_DELIV_LISTING_JS = """anchors => {
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
        const ratingIdx = lines.findIndex(l => /^[1-5][,.]\\d(\\s|$|\\()/.test(l));
        const _isEta = l => /^\\d+(-\\d+)?\\s*min$|around\\s+\\d+/i.test(l);
        const name = ratingIdx > 0 ? lines[ratingIdx - 1]
            : (lines.find(l => !_isEta(l) && !l.includes('€') && l.length > 3) || slug);
        return { name, url: a.href, slug };
    });
}"""

_TAKEAWAY_LISTING_EVAL = """
() => {
    const cards = Array.from(document.querySelectorAll('[data-qa="restaurant-card"]'));
    const seen = new Set();
    return cards.flatMap(card => {
        const a = card.querySelector('a[href*="/menu/"]');
        if (!a) return [];
        const href = a.getAttribute('href') || '';
        const slug = (href.match(/\\/menu\\/([^?#]+)/) || [])[1] || '';
        if (!slug || seen.has(slug)) return [];
        seen.add(slug);
        const text = (card.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
        const nameCandidates = text.filter(l =>
            l.length > 2 &&
            !/^Sponsoris[eé]|^Gesponsord|^Sponsored|^Ad$/i.test(l) &&
            !/^\\d+([.,]\\d+)?$/.test(l) &&
            !/%/.test(l) &&
            !/^[€£$]/.test(l) &&
            !/à partir de|starting from|vanaf/i.test(l) &&
            !/gratuit|free delivery|gratis/i.test(l)
        );
        const name = nameCandidates[0] || slug;
        return [{ name, slug, href }];
    });
}
"""

_TAKEAWAY_LISTING_BASE = "https://www.takeaway.com/be-fr/livraison/repas/"


def _strong(target: str, name: str) -> bool:
    return JaroWinkler.similarity(normalize_name(target), normalize_name(name)) >= _STRONG_NAME_SIM


# ---------------------------------------------------------------------------
# UberEats — typeahead address -> getFeedV1 first batch(es); venue mapMarker coords
# ---------------------------------------------------------------------------

async def ubereats_search(browser, *, target_name: str, address: str, log_fn=noop_log):
    if not address:
        return [], True, "no_pin_address"

    page = await new_page(browser, lang="fr-BE")
    feed_event = asyncio.Event()
    feed_pages: list[list] = []

    async def on_response(response):
        if "getFeedV1" in response.url:
            try:
                parsed = json.loads(await response.text())
                items = parsed.get("data", {}).get("feedItems", [])
                if items:
                    feed_pages.append(items)
                    feed_event.set()
            except Exception:
                pass

    page.on("response", on_response)
    try:
        await page.goto("https://www.ubereats.com/be", wait_until="domcontentloaded", timeout=60000)
        check_cloudflare(await page.title())

        sel = "#location-typeahead-home-input"
        await page.wait_for_selector(sel, timeout=20000)
        await page.click(sel)
        await page.type(sel, address, delay=60)
        await asyncio.sleep(3)
        try:
            await page.wait_for_selector('[role="option"], li[role="option"], [data-testid*="suggestion"]', timeout=5000)
        except Exception:
            pass
        await page.keyboard.press("ArrowDown")
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        try:
            await page.wait_for_url("**/restaurants**", timeout=10000)
        except Exception:
            pass

        try:
            async with asyncio.timeout(25):
                await feed_event.wait()
        except asyncio.TimeoutError:
            pass

        if not feed_pages:
            # A valid address always returns SOME feed (other nearby venues even
            # if ours is absent). No feed => anti-bot / interstitial => can't
            # prove a negative.
            return [], True, "no_feed"

        # Let a couple more batches settle (the on-pin venue ranks top); no scroll.
        await asyncio.sleep(2)
        return _ue_cards(feed_pages), False, None
    except CloudflareBlockedError:
        return [], True, "cloudflare"
    except Exception as exc:  # noqa: BLE001
        return [], True, f"error:{type(exc).__name__}"
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
        await page.close()


def _ue_cards(feed_pages: list[list]) -> list[Candidate]:
    seen: set[str] = set()
    out: list[Candidate] = []
    for feed in feed_pages:
        for item in feed if isinstance(feed, list) else []:
            if item.get("type") != "REGULAR_STORE":
                continue
            s = item.get("store") or {}
            uuid = s.get("storeUuid") or item.get("uuid") or ""
            if uuid and uuid in seen:
                continue
            seen.add(uuid)
            marker = s.get("mapMarker") or {}
            action = s.get("actionUrl")
            out.append(Candidate(
                name=(s.get("title") or {}).get("text", "Unknown"),
                url=f"https://www.ubereats.com{action.split('?')[0]}" if action else "",
                lat=marker.get("latitude"),
                lng=marker.get("longitude"),
                cuisine=None,
            ))
    return out


# ---------------------------------------------------------------------------
# Deliveroo — address -> /restaurants; bounded virtualised scroll; name-only cards
# ---------------------------------------------------------------------------

async def deliveroo_search(browser, *, target_name: str, address: str, max_steps: int = 40, log_fn=noop_log):
    if not address:
        return [], True, "no_pin_address"

    page = await new_page(browser, lang="fr-BE")
    try:
        await page.goto("https://deliveroo.be/fr", wait_until="domcontentloaded", timeout=60000)
        check_cloudflare(await page.title())
        try:
            await page.click('button:has-text("Accept all"), button:has-text("Continue without accepting")', timeout=4000)
            await asyncio.sleep(0.5)
        except Exception:
            pass

        sel = 'input[id="location-search"], input[placeholder*="address" i], input[placeholder*="adresse" i]'
        await page.wait_for_selector(sel, timeout=10000)
        await page.click(sel)
        await page.type(sel, address, delay=60)
        try:
            await page.wait_for_selector('li.ccl-ee4ea4aaab604785', timeout=8000)
            await page.click('li.ccl-ee4ea4aaab604785')
        except Exception:
            await asyncio.sleep(2)
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")

        try:
            await page.wait_for_url("**/restaurants**", timeout=20000)
        except Exception:
            pass
        if "restaurants" not in page.url:
            # Valid venue address that never reaches a listing => anti-bot or
            # address rejected; can't prove a negative.
            return [], True, "no_listing_page"

        await page.wait_for_selector('a[href*="/menu/"]', timeout=10000)

        acc: dict[str, Candidate] = {}
        stale = 0
        for _ in range(max_steps):
            for c in await page.eval_on_selector_all('a[href*="/menu/"]', _DELIV_LISTING_JS):
                slug = c.get("slug")
                if slug and slug not in acc:
                    acc[slug] = Candidate(name=c.get("name") or slug, url=c.get("url") or "", lat=None, lng=None, cuisine=None)
                    if _strong(target_name, acc[slug].name):
                        return list(acc.values()), False, None  # confident hit, stop early
            before = len(acc)
            await page.evaluate("window.scrollBy(0, Math.round(window.innerHeight * 0.8))")
            await asyncio.sleep(0.25)
            if len(acc) == before:
                stale += 1
                if stale >= 8:
                    break
            else:
                stale = 0
        return list(acc.values()), False, None
    except CloudflareBlockedError:
        return [], True, "cloudflare"
    except Exception as exc:  # noqa: BLE001
        return [], True, f"error:{type(exc).__name__}"
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# Takeaway — postal-code zone URL -> server-rendered cards; name-only
# ---------------------------------------------------------------------------

_POSTAL_RE = re.compile(r"\b(1\d{3})\b")


def _zone_from_postal(postal_code: str | None) -> str | None:
    if not postal_code:
        return None
    m = _POSTAL_RE.search(str(postal_code))
    return f"bruxelles-{m.group(1)}" if m else None


async def takeaway_search(browser, *, target_name: str, postal_code: str | None, log_fn=noop_log):
    zone = _zone_from_postal(postal_code)
    if not zone:
        return [], True, "no_postal"

    page = await new_page(browser, lang="fr-BE")
    try:
        await page.goto(_TAKEAWAY_LISTING_BASE + zone, wait_until="domcontentloaded", timeout=60000)
        if "just a moment" in (await page.title()).lower():
            if not await wait_for_cf_clear(page, timeout_s=60):
                return [], True, "cloudflare"
        try:
            await page.wait_for_selector('[data-qa="restaurant-card"]', timeout=20000)
        except Exception:
            # No cards in a valid commune zone => CF/interstitial, not a real empty.
            return [], True, "no_cards"
        await page.wait_for_timeout(1000)
        rows = await page.evaluate(_TAKEAWAY_LISTING_EVAL)
        out: list[Candidate] = []
        for r in rows:
            href = r.get("href") or ""
            url = href if href.startswith("http") else f"https://www.takeaway.com{href}"
            out.append(Candidate(name=r.get("name") or r.get("slug") or "", url=url, lat=None, lng=None, cuisine=None))
        return out, False, None
    except CloudflareBlockedError:
        return [], True, "cloudflare"
    except Exception as exc:  # noqa: BLE001
        return [], True, f"error:{type(exc).__name__}"
    finally:
        await page.close()


# Dispatch by the platform_listings name (underscore form).
SEARCHERS = {
    "uber_eats": ("ubereats_search", False),   # (fn name, headed)
    "deliveroo": ("deliveroo_search", False),
    "takeaway": ("takeaway_search", True),
}
