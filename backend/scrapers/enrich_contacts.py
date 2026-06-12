"""
Contact enrichment — backfill restaurant phone/website + order channel.

Measured rationale: any single scraped phone is only ~63% reliable (FSQ vs the
existing DB phone agree only 63% even on exact-name, <30m matches). So this
module NEVER blind-overwrites. Each free source (google_maps, website, fsq)
writes a *candidate* row into `restaurant_contact_candidates`, then a pure
resolver computes the winning phone + a confidence tier from cross-source
corroboration:

    - same phone from >=2 distinct sources  -> 'high'
    - single source google_maps | website   -> 'medium'
    - fsq/osm only                           -> 'low'

The resolver also derives `order_channel` ('direct' | 'covered_platform' |
'unknown'): a venue whose only contact is a link to a platform we already cover
(UberEats/Deliveroo/Takeaway/...) has no "order direct" advantage to surface.

Sources, per restaurant (one candidate row each, upserted in place):
    1. google_maps — headed Playwright lookup by "{name} {neighborhood|Bruxelles}"
    2. website     — fetch the known/discovered site, parse schema.org telephone
    3. fsq         — geo+name match against the offline `fsq_places` slice

The resolver and the fsq matcher are pure functions over plain dicts so they can
be unit-tested without a network, browser, or DB.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
from typing import Callable
from urllib.parse import urlparse

import httpx
import phonenumbers
from rapidfuzz import fuzz

import db
import pgpool
from models import ScraperConfig, ScraperResult
from scrapers.base import new_browser, new_page, noop_log, is_safe_url
from scrapers.direct import _extract_phone, _normalize_phone


def valid_phone(raw: str | None) -> str | None:
    """Return a validated E.164 Belgian number, or None.

    `direct._normalize_phone` only checks digit length, so a phone-shaped string
    scraped off a page (tracking ID, VAT, price) can pass it. We additionally
    require phonenumbers.is_valid_number — measured to reject ~40% of raw website
    extractions that are not real Belgian numbers (e.g. +32557714815).
    """
    if not raw:
        return None
    try:
        parsed = phonenumbers.parse(raw, "BE")  # region handles national 0-prefixed form
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


# ── Order-channel classification ──────────────────────────────────────────────
# Platforms already covered → an order link to these is NOT a direct channel.
# Lifted verbatim from _gmaps_test.py (tested/correct).
COVERED_DOMAINS = (
    "ubereats.com", "deliveroo.be", "deliveroo.com", "deliveroo.co",
    "takeaway.com", "pizza.be", "just-eat", "justeat", "lieferando",
    "thuisbezorgd", "wolt.com", "foodpanda",
)

# Source priority for tie-breaking the winning phone (highest first).
_SOURCE_PRIORITY = {"website": 3, "google_maps": 2, "fsq": 1, "osm": 0}

# fsq matcher thresholds — validated; do not loosen.
_FSQ_MIN_SCORE = 85
_FSQ_MAX_DIST_M = 60
_FSQ_BOX_M = 80  # candidate pre-filter box half-width (metres)

_DEFAULT_LIMIT = 10  # project rule: test runs use small limits

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (no network / browser / DB) — unit-tested
# ─────────────────────────────────────────────────────────────────────────────

def covered_domain(website: str | None) -> str | None:
    """Return the matched covered-platform domain if `website` is one, else None."""
    if not website:
        return None
    w = website.lower()
    for d in COVERED_DOMAINS:
        if d in w:
            return d
    return None


def classify_channel(website: str | None, phone: str | None = None) -> tuple[str, str | None]:
    """Classify a single candidate's order channel.

    Returns (order_channel, covered_via):
      - website on a covered platform   -> ('covered_platform', domain)
      - website present & not covered    -> ('direct', None)
      - no website but a phone present   -> ('direct', None)
      - nothing                          -> ('unknown', None)
    """
    via = covered_domain(website)
    if via:
        return "covered_platform", via
    if website:
        return "direct", None
    if phone:
        return "direct", None
    return "unknown", None


def _norm_name(name: str | None) -> str:
    """Lowercase, strip non-alphanumeric, collapse spaces."""
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def name_match_score(a: str | None, b: str | None) -> int:
    """0-100 fuzzy similarity of two names (token_sort_ratio on normalized text)."""
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return 0
    return int(round(fuzz.token_sort_ratio(na, nb)))


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def match_fsq_place(
    restaurant: dict, candidates: list[dict]
) -> dict | None:
    """Pick the best fsq_places row for a restaurant, or None.

    Accept the highest-scoring candidate only if name score >= 85 AND
    distance < 60m. `restaurant` needs name/lat/lng; each candidate needs
    name/latitude/longitude (+ tel/website passthrough). Pure — inject the
    geo-boxed candidate list; no DB access here.
    """
    rlat, rlng = restaurant.get("lat"), restaurant.get("lng")
    if rlat is None or rlng is None:
        return None
    rlat, rlng = float(rlat), float(rlng)  # psycopg numeric → Decimal
    best: dict | None = None
    best_score = -1
    for c in candidates:
        clat, clng = c.get("latitude"), c.get("longitude")
        if clat is None or clng is None:
            continue
        dist = _haversine_m(rlat, rlng, float(clat), float(clng))
        if dist >= _FSQ_MAX_DIST_M:
            continue
        score = name_match_score(restaurant.get("name"), c.get("name"))
        if score < _FSQ_MIN_SCORE:
            continue
        # Prefer higher name score, then closer.
        key = (score, -dist)
        if best is None or key > (best_score, -best["_dist"]):
            best = dict(c)
            best["_dist"] = dist
            best["_score"] = score
            best_score = score
    return best


def resolve_contacts(restaurant: dict, candidates: list[dict]) -> dict:
    """Compute the resolved phone/confidence/channel from candidate rows.

    `restaurant` must carry the current `phone` (to honour the never-overwrite
    rule). Each candidate is a dict with keys: source, phone_e164, website,
    order_channel, covered_via.

    Returns a dict:
      {phone, phone_confidence, phone_source, order_channel,
       set_phone (bool — write phone only if currently empty)}
    """
    # ── Winning phone by corroboration ────────────────────────────────────────
    # phone_e164 -> set of distinct sources that produced it.
    phone_sources: dict[str, set[str]] = {}
    for c in candidates:
        ph = c.get("phone_e164")
        if not ph:
            continue
        phone_sources.setdefault(ph, set()).add(c.get("source", ""))

    winning_phone: str | None = None
    winning_srcs: set[str] = set()
    if phone_sources:
        # Rank: most distinct sources, then source-priority, then phone string
        # for determinism.
        def _rank(item: tuple[str, set[str]]) -> tuple:
            phone, srcs = item
            top_prio = max((_SOURCE_PRIORITY.get(s, -1) for s in srcs), default=-1)
            return (len(srcs), top_prio, phone)

        winning_phone, winning_srcs = max(phone_sources.items(), key=_rank)

    # ── Confidence tier ───────────────────────────────────────────────────────
    confidence: str | None = None
    if winning_phone:
        if len(winning_srcs) >= 2:
            confidence = "high"
        elif winning_srcs & {"google_maps", "website"}:
            confidence = "medium"
        else:
            confidence = "low"

    phone_source = "+".join(sorted(winning_srcs)) if winning_srcs else None

    # ── Order channel: direct wins, else covered, else unknown ────────────────
    order_channel = "unknown"
    if any(c.get("order_channel") == "direct" for c in candidates):
        order_channel = "direct"
    elif any(c.get("order_channel") == "covered_platform" for c in candidates):
        order_channel = "covered_platform"

    # ── Never overwrite an existing phone ─────────────────────────────────────
    existing = (restaurant.get("phone") or "").strip()
    set_phone = bool(winning_phone) and not existing

    return {
        "phone": winning_phone,
        "phone_confidence": confidence,
        "phone_source": phone_source,
        "order_channel": order_channel,
        "set_phone": set_phone,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Source: google_maps (headed Playwright) — lifted from _gmaps_test.py
# ─────────────────────────────────────────────────────────────────────────────

async def _accept_consent(page) -> bool:
    for sel in (
        'button[aria-label*="Tout accepter"]',
        'button[aria-label*="Accept all"]',
        'form[action*="consent"] button',
        'button:has-text("Tout accepter")',
    ):
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await asyncio.sleep(2)
                return True
        except Exception:
            pass
    return False


async def _scrape_place(page) -> tuple[str | None, str | None]:
    """From a place page in [role=main]: phone + website."""
    main = await page.query_selector('[role="main"]')
    if not main:
        return None, None
    phone = _extract_phone(await main.inner_text())
    website = None
    el = await page.query_selector('a[data-item-id="authority"]')
    if el:
        website = await el.get_attribute("href")
    return phone, website


async def gmaps_lookup(page, name: str, area: str) -> tuple[str | None, str | None]:
    """Per-restaurant Google Maps lookup → (phone, website)."""
    q = f"{name} {area}".replace(" ", "+")
    url = f"https://www.google.com/maps/search/{q}/@50.8503,4.3517,12z?hl=fr"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await _accept_consent(page)
        await asyncio.sleep(1)
        phone, website = await _scrape_place(page)
        if phone or website:
            return phone, website
        card = await page.query_selector('a[href*="/maps/place/"]')
        if card:
            href = await card.get_attribute("href")
            await page.goto(href, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            await _accept_consent(page)
            return await _scrape_place(page)
    except Exception:
        pass
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Source: website (sync httpx, run via asyncio.to_thread)
# ─────────────────────────────────────────────────────────────────────────────

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_ITEMPROP_TEL_RE = re.compile(
    r'itemprop=["\']telephone["\'][^>]*>([^<]+)<'
    r'|itemprop=["\']telephone["\'][^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _jsonld_phones(obj) -> list[str]:
    """Recursively collect `telephone` values from parsed JSON-LD."""
    out: list[str] = []
    if isinstance(obj, dict):
        tel = obj.get("telephone")
        if isinstance(tel, str) and tel.strip():
            out.append(tel)
        for v in obj.values():
            out.extend(_jsonld_phones(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_jsonld_phones(v))
    return out


def _phone_from_html(html: str) -> str | None:
    """Prefer schema.org telephone, fall back to free-text phone extraction."""
    for block in _JSONLD_RE.findall(html):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        for tel in _jsonld_phones(data):
            ph = _normalize_phone(tel)
            if ph:
                return ph
    m = _ITEMPROP_TEL_RE.search(html)
    if m:
        ph = _normalize_phone(m.group(1) or m.group(2) or "")
        if ph:
            return ph
    return _extract_phone(html)


def fetch_website(url: str) -> tuple[str | None, str | None]:
    """Fetch a site (following redirects); return (phone, final_url). Sync."""
    if not url or not is_safe_url(url):
        return None, None
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=10.0,
            headers={"User-Agent": _UA, "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8"},
        ) as client:
            resp = client.get(url)
            final_url = str(resp.url)
            phone = _phone_from_html(resp.text)
            return phone, final_url
    except Exception:
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Source: fsq (offline geo+name match against fsq_places)
# ─────────────────────────────────────────────────────────────────────────────

def _fsq_geo_candidates(lat: float, lng: float) -> list[dict]:
    """Fetch fsq_places rows within a ~80m lat/lng box around (lat, lng)."""
    lat, lng = float(lat), float(lng)  # psycopg returns numeric as Decimal
    # 1 deg lat ≈ 111_320 m; lng scaled by cos(lat).
    dlat = _FSQ_BOX_M / 111_320.0
    dlng = _FSQ_BOX_M / (111_320.0 * max(0.01, math.cos(math.radians(lat))))
    return pgpool.fetchall(
        "SELECT fsq_place_id, name, latitude, longitude, tel, website "
        "FROM fsq_places "
        "WHERE latitude BETWEEN %s AND %s AND longitude BETWEEN %s AND %s",
        [lat - dlat, lat + dlat, lng - dlng, lng + dlng],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Candidate persistence
# ─────────────────────────────────────────────────────────────────────────────

def _upsert_candidate(
    restaurant_id: str,
    source: str,
    *,
    phone_e164: str | None,
    phone_raw: str | None,
    website: str | None,
    order_channel: str | None,
    covered_via: str | None,
    name_match: int | None,
) -> None:
    pgpool.execute(
        "INSERT INTO restaurant_contact_candidates "
        "(restaurant_id, source, phone_e164, phone_raw, website, "
        " order_channel, covered_via, name_match, fetched_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()) "
        "ON CONFLICT (restaurant_id, source) DO UPDATE SET "
        "  phone_e164 = EXCLUDED.phone_e164, "
        "  phone_raw = EXCLUDED.phone_raw, "
        "  website = EXCLUDED.website, "
        "  order_channel = EXCLUDED.order_channel, "
        "  covered_via = EXCLUDED.covered_via, "
        "  name_match = EXCLUDED.name_match, "
        "  fetched_at = now()",
        [restaurant_id, source, phone_e164, phone_raw, website,
         order_channel, covered_via, name_match],
    )


def _apply_resolution(restaurant_id: str, res: dict) -> None:
    sets = [
        "phone_confidence = %s",
        "phone_source = %s",
        "order_channel = %s",
        "contacts_enriched_at = now()",
    ]
    params: list = [res["phone_confidence"], res["phone_source"], res["order_channel"]]
    if res["set_phone"]:
        sets.insert(0, "phone = %s")
        params.insert(0, res["phone"])
    params.append(restaurant_id)
    pgpool.execute(
        f"UPDATE restaurants SET {', '.join(sets)} WHERE id = %s",
        params,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Per-restaurant pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def _enrich_one(page, restaurant: dict, log_fn: Callable[[str], None]) -> dict:
    """Gather all sources for one restaurant, write candidates, resolve+apply.

    Returns the resolution dict. Network/DB calls are isolated so a single
    failure cannot abort the whole run (caller wraps in try/except too).
    """
    rid = str(restaurant["id"])
    name = restaurant.get("name") or ""
    area = restaurant.get("neighborhood") or "Bruxelles"
    candidates: list[dict] = []

    # 1) google_maps ----------------------------------------------------------
    g_web = None
    try:
        g_phone, g_web = await gmaps_lookup(page, name, area)
        g_phone = valid_phone(g_phone)
        g_chan, g_via = classify_channel(g_web, g_phone)
        _upsert_candidate(
            rid, "google_maps",
            phone_e164=g_phone, phone_raw=g_phone, website=g_web,
            order_channel=g_chan, covered_via=g_via,
            name_match=100 if (g_phone or g_web) else 0,
        )
        candidates.append({"source": "google_maps", "phone_e164": g_phone,
                           "website": g_web, "order_channel": g_chan, "covered_via": g_via})
    except Exception as e:
        log_fn(f"    google_maps err {name[:24]}: {str(e)[:60]}")

    # 2) website (from gmaps result or restaurants.website) -------------------
    site = g_web or restaurant.get("website")
    if site and not covered_domain(site):
        try:
            w_phone, w_final = await asyncio.to_thread(fetch_website, site)
            w_phone = valid_phone(w_phone)
            w_chan, w_via = classify_channel(w_final or site, w_phone)
            _upsert_candidate(
                rid, "website",
                phone_e164=w_phone, phone_raw=w_phone, website=w_final or site,
                order_channel=w_chan, covered_via=w_via,
                name_match=100 if w_phone else 0,
            )
            candidates.append({"source": "website", "phone_e164": w_phone,
                               "website": w_final or site,
                               "order_channel": w_chan, "covered_via": w_via})
        except Exception as e:
            log_fn(f"    website err {name[:24]}: {str(e)[:60]}")

    # 3) fsq (offline geo+name match) -----------------------------------------
    lat, lng = restaurant.get("lat"), restaurant.get("lng")
    if lat is not None and lng is not None:
        try:
            geo = await asyncio.to_thread(_fsq_geo_candidates, lat, lng)
            match = match_fsq_place(restaurant, geo)
            if match:
                f_raw = match.get("tel")
                f_phone = valid_phone(f_raw)
                f_web = match.get("website")
                f_chan, f_via = classify_channel(f_web, f_phone)
                _upsert_candidate(
                    rid, "fsq",
                    phone_e164=f_phone, phone_raw=f_raw, website=f_web,
                    order_channel=f_chan, covered_via=f_via,
                    name_match=match.get("_score", 0),
                )
                candidates.append({"source": "fsq", "phone_e164": f_phone,
                                   "website": f_web, "order_channel": f_chan,
                                   "covered_via": f_via})
        except Exception as e:
            log_fn(f"    fsq err {name[:24]}: {str(e)[:60]}")

    # Resolve + persist -------------------------------------------------------
    res = resolve_contacts(restaurant, candidates)
    await asyncio.to_thread(_apply_resolution, rid, res)
    log_fn(
        f"  {name[:32]:32} phone={res['phone'] or '-':14} "
        f"conf={res['phone_confidence'] or '-':6} chan={res['order_channel']} "
        f"src={res['phone_source'] or '-'}"
    )
    return res


def _select_targets(limit: int) -> list[dict]:
    return pgpool.fetchall(
        "SELECT id, name, lat, lng, phone, website, neighborhood "
        "FROM restaurants "
        "WHERE (phone IS NULL OR phone = '') "
        "  AND lat IS NOT NULL AND lng IS NOT NULL "
        "ORDER BY contacts_enriched_at ASC NULLS FIRST, name "
        "LIMIT %s",
        [limit],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

async def run(
    config: ScraperConfig | None = None,
    log_fn: Callable[[str], None] = noop_log,
) -> ScraperResult:
    if config is None:
        config = ScraperConfig()
    # Default to a small batch unless an explicit larger limit is passed.
    limit = config.max_items if config.max_items else _DEFAULT_LIMIT

    run_id = db.create_run("enrich")
    saved = 0
    try:
        targets = await asyncio.to_thread(_select_targets, limit)
        log_fn(f"enrich: {len(targets)} restaurant(s) missing a phone (limit {limit})")
        if not targets:
            db.finish_run(run_id, "success", records_saved=0)
            return ScraperResult(records_saved=0)

        browser = await new_browser(headed=True)
        try:
            page = await new_page(browser)
            for i, restaurant in enumerate(targets, 1):
                try:
                    res = await _enrich_one(page, restaurant, log_fn)
                    if res["phone"]:
                        saved += 1
                except Exception as e:  # one failure must not abort the run
                    log_fn(f"  ✗ {str(restaurant.get('name'))[:32]}: {str(e)[:80]}")
                if i % 5 == 0:
                    await asyncio.to_thread(db.update_run_progress, run_id, saved)
                await asyncio.sleep(1)
        finally:
            try:
                await asyncio.wait_for(browser.close(), timeout=15)
            except Exception:
                pass

        db.finish_run(run_id, "success", records_saved=saved)
        return ScraperResult(records_saved=saved)
    except Exception as e:
        db.finish_run(run_id, "failed", error_msg=str(e))
        raise
