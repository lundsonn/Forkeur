import os
import re
import unicodedata
from uuid import UUID
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


def _validate_uuid(value: str) -> str:
    """Return the value if it parses as a UUID, else raise ValueError.

    PostgREST filter expressions (`.or_(...)`) accept raw strings; interpolating
    unvalidated input there opens a filter-injection vector.
    """
    UUID(str(value))
    return str(value)


_MENU_INSERT_CHUNK = 500

_client: Client | None = None
_domain_cache: dict[str, str] | None = None  # domain → restaurant_id


def invalidate_domain_cache() -> None:
    global _domain_cache
    _domain_cache = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        # Use the service_role key so writes bypass RLS (anon key is public).
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = create_client(url, key)
    return _client


def _is_junk(name: str) -> bool:
    """Return True if the name looks like a scraped UI element, not a real restaurant."""
    s = name.strip().lower()
    # Cap input length before running the alternation regex — the `[\s-]?\d`
    # branches can backtrack quadratically on adversarial input. Real
    # restaurant names never exceed a few hundred characters.
    if len(s) > 300:
        return False
    return bool(re.match(
        r'^(around\s+\d|pre[\s-]?order\s+\d|pré[\s-]?commande\s+\d'
        r'|article\s+offert|\d+e?\s*à\s*moiti|\d+\s*%\s+off|-\s*\d+\s*%'
        r'|•\s*à\s+partir|\d+e\s+à\s+moitié)',
        s,
    ))


def _canonical(name: str) -> str:
    """Strip platform-specific location suffixes and noise for cross-platform matching.
    'Burger King - Ixelles' → 'Burger King'
    '🩷 Crousty Factory 🧡 - Bruxelles' → 'Crousty Factory'
    """
    # Strip leading/trailing whitespace
    name = name.strip()
    # Remove emoji and symbols outside Basic Latin + Latin Extended blocks
    name = re.sub(r'[^ -ɏḀ-ỿ\s\d\'\"\-&\(\)\.!,]', '', name).strip()
    # Strip location suffix after " - " (regular hyphen only — em-dash separates distinct branches)
    name = re.sub(r'\s+-\s+\S.*$', '', name).strip()
    return name


def _normalize_for_match(name: str) -> str:
    """Fully normalize for fuzzy duplicate detection.
    Handles mixed case, accents, smart quotes, emoji, extra whitespace.
    """
    # Normalize smart quotes to straight apostrophe BEFORE _canonical so they
    # aren't stripped by the Unicode-range filter (U+2018/U+2019 > U+024F).
    name = re.sub(r"[‘’ʼ´`]", "'", name)
    c = _canonical(name).lower()
    # Remove accents via NFD decomposition
    c = unicodedata.normalize('NFD', c)
    c = ''.join(ch for ch in c if unicodedata.category(ch) != 'Mn')
    # Collapse whitespace
    return re.sub(r'\s+', ' ', c).strip()


# Simple keyword-based cuisine inference — covers common Brussels chains
_CUISINE_RULES: list[tuple[str, list[str]]] = [
    ("Burgers",   ["burger", "mcdonald", "quick", "five guys", "smash", "belchicken", "b&w burger", "black.*white"]),
    ("Chicken",   ["kfc", "chicken", "poultry", "poulet", "belchicken"]),
    ("Pizza",     ["pizza", "domino", "napoli", "pizzeria"]),
    ("Asian",     ["sushi", "wok", "asian", "chinese", "thai", "vietnam", "hanoi", "seoul", "japanese", "ramen", "udon", "poke", "bowl", "bao", "dim sum"]),
    ("Indian",    ["indian", "indien", "curry", "tikka", "masala", "biryani", "daal", "bhavan"]),
    ("Mexican",   ["taco", "burrito", "mexican", "mexic", "nacho", "guac"]),
    ("Kebab",     ["kebab", "shawarma", "doner", "döner"]),
    ("Sandwiches",["sandwich", "sub", "bagel", "broodje", "toasties"]),
    ("Healthy",   ["salad", "salade", "healthy", "vegan", "green", "bowl", "acai", "oakberry", "juice"]),
    ("Grocery",   ["carrefour", "delhaize", "colruyt", "supermarkt", "supermarché", "grocery"]),
    ("Italian",   ["italian", "pasta", "risotto", "trattoria", "osteria", "gelato"]),
    ("Belgian",   ["friterie", "frituur", "waffle", "gaufre", "belgian", "frites"]),
]


def infer_cuisine(name: str) -> str | None:
    low = name.lower()
    for cuisine, keywords in _CUISINE_RULES:
        if any(re.search(kw, low) for kw in keywords):
            return cuisine
    return None


def upsert_restaurant(data: dict) -> str:
    """Match restaurant by name across platforms, insert if new. Returns id.

    Matching is done in 5 escalating steps to handle cross-platform name
    variations: exact → case-insensitive → canonical base → suffixed variant
    → fully-normalized (accents, quotes, emoji).
    """
    client = get_client()
    name: str = data["name"].strip()
    data = {**data, "name": name}

    if _is_junk(name):
        raise ValueError(f"Junk entry skipped: {name!r}")

    canonical = _canonical(name)
    norm = _normalize_for_match(name)
    norm_canonical = _normalize_for_match(canonical)

    if not data.get("cuisine"):
        data = {**data, "cuisine": infer_cuisine(name)}

    _MATCH_COLS = "id, cuisine, image_url, lat, lng, geo_source"

    def _found(rid: str, row: dict | None = None) -> str:
        if row is None:
            existing = client.table("restaurants").select("cuisine, image_url, lat, lng, geo_source").eq("id", rid).limit(1).execute()
            row = existing.data[0] if existing.data else {}
        updates: dict = {}
        if data.get("cuisine") and not row.get("cuisine"):
            updates["cuisine"] = data["cuisine"]
        if data.get("image_url") and not row.get("image_url"):
            updates["image_url"] = data["image_url"]
        # Geo provenance hierarchy: uber_eats/direct > deliveroo_venue > deliveroo (zone centroid).
        # venue-grade always overwrites; deliveroo_venue upgrades over zone centroid only;
        # plain deliveroo only fills when row has no coords.
        incoming_src = data.get("geo_source")
        _VENUE = {"uber_eats", "direct"}
        if data.get("lat") is not None and data.get("lng") is not None:
            if incoming_src in _VENUE:
                updates["lat"] = data["lat"]
                updates["lng"] = data["lng"]
                updates["geo_source"] = incoming_src
            elif incoming_src == "deliveroo_venue" and row.get("geo_source") not in _VENUE:
                updates["lat"] = data["lat"]
                updates["lng"] = data["lng"]
                updates["geo_source"] = incoming_src
            elif row.get("lat") is None:
                updates["lat"] = data["lat"]
                updates["lng"] = data["lng"]
                if incoming_src:
                    updates["geo_source"] = incoming_src
        if updates:
            client.table("restaurants").update(updates).eq("id", rid).execute()
        return rid

    # 1. Exact name match (same scraper re-running)
    res = client.table("restaurants").select(_MATCH_COLS).eq("name", name).limit(1).execute()
    if res.data:
        return _found(res.data[0]["id"], res.data[0])

    # 2. Case-insensitive exact match ("GOMU" ↔ "Gomu", "Bombay Inn" ↔ "bombay inn")
    res = client.table("restaurants").select(_MATCH_COLS).ilike("name", name).limit(1).execute()
    if res.data:
        return _found(res.data[0]["id"], res.data[0])

    # 2b. Website-domain lock — strongest deterministic signal. A new listing
    #     whose website resolves to a domain we already store is the same venue.
    import matching as _m
    incoming_domain = _m.domain_of(data.get("website"))
    if incoming_domain:
        global _domain_cache
        if _domain_cache is None:
            cands = (
                client.table("restaurants")
                .select("id, website")
                .not_.is_("website", "null")
                .execute()
            ).data or []
            _domain_cache = {}
            for c in cands:
                d = _m.domain_of(c.get("website"))
                if d:
                    _domain_cache[d] = c["id"]
        if incoming_domain in _domain_cache:
            return _found(_domain_cache[incoming_domain])

    # 3. Canonical base match ("Burger King - Ixelles" → find "Burger King")
    if canonical != name:
        res = client.table("restaurants").select(_MATCH_COLS).ilike("name", canonical).limit(1).execute()
        if res.data:
            return _found(res.data[0]["id"], res.data[0])

    # 4. Suffixed variant match ("Burger King" → find "Burger King - Ixelles")
    res = (
        client.table("restaurants")
        .select(_MATCH_COLS)
        .ilike("name", f"{canonical} -%")
        .limit(1)
        .execute()
    )
    if res.data:
        return _found(res.data[0]["id"], res.data[0])

    # 5. Fully-normalized match: handles accents, smart quotes, emoji, trailing
    #    spaces. Fetch candidates by the first non-article word of canonical.
    _ARTICLES = {"le", "la", "les", "l'", "au", "aux", "un", "une", "de", "du", "the", "a"}
    words = canonical.split()
    sig_words = [w for w in words if w.lower().rstrip("'") not in _ARTICLES]
    prefix = sig_words[0] if sig_words else (words[0] if words else canonical[:5])
    if len(prefix) >= 3:
        candidates = (
            client.table("restaurants")
            .select(f"name, {_MATCH_COLS}")
            .ilike("name", f"{prefix}%")
            .execute()
        )
        for cand in candidates.data:
            cand_norm = _normalize_for_match(cand["name"])
            cand_norm_can = _normalize_for_match(_canonical(cand["name"]))
            if cand_norm in (norm, norm_canonical) or cand_norm_can in (norm, norm_canonical):
                return _found(cand["id"], cand)

    # Not found — insert new row
    res = client.table("restaurants").upsert(data, on_conflict="slug").execute()
    rid = res.data[0]["id"]
    invalidate_domain_cache()
    return rid


def upsert_listing(data: dict) -> str:
    """Upsert platform_listing by restaurant_id + platform. Returns id."""
    res = (
        get_client()
        .table("platform_listings")
        .upsert(data, on_conflict="restaurant_id,platform")
        .execute()
    )
    return res.data[0]["id"]


def patch_listing(listing_id: str, data: dict) -> None:
    """Patch specific fields on a platform_listing row by id."""
    get_client().table("platform_listings").update(data).eq("id", listing_id).execute()


def upsert_promotions(listing_id: str, promotions: list[dict]) -> int:
    """Replace all promotions for a listing. Returns count saved."""
    client = get_client()
    client.table("promotions").delete().eq("listing_id", listing_id).execute()
    if not promotions:
        return 0
    rows = [{"listing_id": listing_id, **p} for p in promotions]
    res = client.table("promotions").insert(rows).execute()
    return len(res.data)


def delete_menu_items(listing_id: str) -> None:
    """Delete all menu items for a listing."""
    get_client().table("menu_items").delete().eq("listing_id", listing_id).execute()


def insert_menu_items(listing_id: str, items: list[dict]) -> int:
    """Delete existing items for listing, insert new ones. Returns count.

    Also bumps last_scraped_at on the listing so the frontend can show staleness.
    """
    from datetime import datetime, timezone
    client = get_client()
    client.table("menu_items").delete().eq("listing_id", listing_id).execute()
    now = datetime.now(timezone.utc).isoformat()
    client.table("platform_listings").update({"last_scraped_at": now}).eq("id", listing_id).execute()
    if not items:
        return 0
    rows = [{**item, "listing_id": listing_id} for item in items]
    total = 0
    for i in range(0, len(rows), _MENU_INSERT_CHUNK):
        res = client.table("menu_items").insert(rows[i : i + _MENU_INSERT_CHUNK]).execute()
        total += len(res.data)
    return total


def run_exists(run_id: str) -> bool:
    """Return True if a scraper_run with this id exists."""
    client = get_client()
    res = client.table("scraper_runs").select("id").eq("id", run_id).limit(1).execute()
    return bool(res.data)


def create_run(platform: str) -> str:
    """Insert a scraper_run row with status=running. Returns run id."""
    client = get_client()
    res = (
        client.table("scraper_runs")
        .insert({"platform": platform, "status": "running"})
        .execute()
    )
    return res.data[0]["id"]


def update_run_progress(run_id: str, records_saved: int) -> None:
    get_client().table("scraper_runs").update({
        "records_saved": records_saved,
    }).eq("id", run_id).execute()


def finish_run(
    run_id: str,
    status: str,
    records_saved: int = 0,
    error_msg: str | None = None,
) -> None:
    client = get_client()
    from datetime import datetime, timezone
    client.table("scraper_runs").update({
        "status": status,
        "records_saved": records_saved,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "error_msg": error_msg,
    }).eq("id", run_id).execute()


def get_runs(limit: int = 50, offset: int = 0) -> list[dict]:
    client = get_client()
    res = (
        client.table("scraper_runs")
        .select("*")
        .order("started_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return res.data


def get_run(run_id: str) -> dict | None:
    client = get_client()
    res = client.table("scraper_runs").select("*").eq("id", run_id).execute()
    return res.data[0] if res.data else None


def get_last_run_per_platform() -> dict[str, dict]:
    """Returns {platform: run_row} for the most recent run of each platform."""
    platforms = ("ubereats", "deliveroo", "takeaway", "direct", "direct_menu", "dom_menu", "match")
    rows = (
        get_client()
        .table("scraper_runs")
        .select("*")
        .in_("platform", list(platforms))
        .order("started_at", desc=True)
        .limit(140)
        .execute()
    ).data or []
    seen: dict[str, dict] = {}
    for row in rows:
        p = row["platform"]
        if p not in seen:
            seen[p] = row
    return seen


def get_last_successful_run(platform: str) -> dict | None:
    """Return the most recent successful run for a platform, or None."""
    res = (
        get_client()
        .table("scraper_runs")
        .select("*")
        .eq("platform", platform)
        .eq("status", "success")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_last_successful_run_batch(platforms: list[str]) -> dict[str, dict]:
    """Single query for last successful run across multiple platforms."""
    rows = (
        get_client()
        .table("scraper_runs")
        .select("platform,status,started_at,finished_at,records_saved")
        .eq("status", "success")
        .in_("platform", platforms)
        .order("finished_at", desc=True)
        .limit(len(platforms) * 5)
        .execute()
        .data
    )
    result: dict[str, dict] = {}
    for row in rows:
        p = row["platform"]
        if p not in result:
            result[p] = row
    return result


def delete_stale_listings(days: int = 30) -> int:
    """Delete platform_listings older than `days` days. Returns count deleted."""
    from datetime import datetime, timezone, timedelta
    client = get_client()
    threshold = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = (
        client.table("platform_listings")
        .delete()
        .not_.is_("last_scraped_at", "null")
        .lt("last_scraped_at", threshold)
        .execute()
    )
    return len(result.data) if result.data else 0


def prune_stale_menu_items(days: int = 30) -> int:
    """Delete menu_items for listings not scraped in the last N days.

    Only touches listings where last_scraped_at IS NOT NULL — avoids removing
    data from listings that have never been through a scraper (e.g. manual imports).
    """
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    client = get_client()
    stale = (
        client.table("platform_listings")
        .select("id")
        .not_.is_("last_scraped_at", "null")
        .lt("last_scraped_at", cutoff)
        .execute()
    ).data
    if not stale:
        return 0
    ids = [row["id"] for row in stale]
    deleted = 0
    # PostgREST `in_` builds a URL query param; chunk to keep it under typical limits.
    for i in range(0, len(ids), 200):
        res = (
            client.table("menu_items")
            .delete()
            .in_("listing_id", ids[i : i + 200])
            .execute()
        )
        deleted += len(res.data)
    return deleted


def orphan_stale_runs(max_age_hours: int = 2) -> int:
    """Mark any 'running' rows older than max_age_hours as failed/orphaned.

    Called on backend startup to clean up runs that were interrupted by a
    previous restart and will never finish.
    """
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=max_age_hours)).isoformat()
    res = (
        get_client()
        .table("scraper_runs")
        .update({
            "status": "failed",
            "finished_at": now.isoformat(),
            "error_msg": "orphaned — backend restarted",
        })
        .eq("status", "running")
        .lt("started_at", cutoff)
        .execute()
    )
    return len(res.data)


def get_restaurants(
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
) -> list[dict]:
    client = get_client()
    q = client.table("restaurants").select("*").order("id").range(offset, offset + limit - 1)
    if search:
        q = q.ilike("name", f"%{search}%")
    return q.execute().data


def get_menu_items(listing_id: str) -> list[dict]:
    client = get_client()
    return (
        client.table("menu_items")
        .select("*")
        .eq("listing_id", listing_id)
        .limit(2000)
        .execute()
        .data
    )


def get_listings_with_urls(platform: str) -> list[dict]:
    """Return all platform_listings for a platform that have a URL."""
    client = get_client()
    return (
        client.table("platform_listings")
        .select("id, restaurant_id, url, delivery_fee, min_order")
        .eq("platform", platform)
        .not_.is_("url", "null")
        .execute()
        .data
    )


_GEO_RANK = {"uber_eats": 3, "direct": 3, "deliveroo_venue": 2, "deliveroo": 1}


def patch_restaurant_geo(restaurant_id: str, lat: float, lng: float, geo_source: str) -> None:
    """Update restaurant coords only if incoming source outranks the current one."""
    client = get_client()
    existing = client.table("restaurants").select("geo_source").eq("id", restaurant_id).limit(1).execute()
    if existing.data:
        current_src = existing.data[0].get("geo_source")
        if _GEO_RANK.get(current_src, 0) >= _GEO_RANK.get(geo_source, 0):
            return
    client.table("restaurants").update(
        {"lat": lat, "lng": lng, "geo_source": geo_source}
    ).eq("id", restaurant_id).execute()


def patch_restaurant_website(restaurant_id: str, website: str | None, order_url: str | None) -> None:
    from datetime import datetime, timezone
    get_client().table("restaurants").update({
        "website": website,
        "order_url": order_url,
        "website_searched_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", restaurant_id).execute()
    invalidate_domain_cache()


def mark_restaurant_searched(restaurant_id: str) -> None:
    from datetime import datetime, timezone
    get_client().table("restaurants").update({
        "website_searched_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", restaurant_id).execute()


def insert_claim(
    owner_email: str,
    inquiry_type: str = "add_url",
    restaurant_id: str | None = None,
    direct_order_url: str | None = None,
    restaurant_name_free: str | None = None,
) -> str:
    """Insert an owner inquiry (verified=False). Returns claim id."""
    client = get_client()
    res = client.table("restaurant_claims").insert({
        "restaurant_id": restaurant_id,
        "owner_email": owner_email,
        "direct_order_url": direct_order_url,
        "inquiry_type": inquiry_type,
        "restaurant_name_free": restaurant_name_free,
        "verified": False,
    }).execute()
    return res.data[0]["id"]


def get_claims(verified: bool | None = None) -> list[dict]:
    """Return claims, optionally filtered by verified status."""
    client = get_client()
    q = client.table("restaurant_claims").select(
        "id, restaurant_id, owner_email, direct_order_url, inquiry_type, "
        "restaurant_name_free, verified, claimed_at, restaurants(name)"
    )
    if verified is not None:
        q = q.eq("verified", verified)
    return q.order("claimed_at", desc=True).execute().data


def _validate_order_url(url: str) -> None:
    """Raise ValueError if the URL looks unsafe to publish (delegated to ssrf module)."""
    from ssrf_guard import validate_public_url
    validate_public_url(url)


def approve_claim(claim_id: str) -> None:
    """Approve a claim: for add_url type, update restaurants.order_url and upsert direct listing."""
    client = get_client()
    rows = client.table("restaurant_claims").select(
        "id, restaurant_id, direct_order_url, inquiry_type"
    ).eq("id", claim_id).execute().data
    if not rows:
        raise ValueError(f"Claim not found: {claim_id!r}")
    claim = rows[0]

    if claim.get("inquiry_type") == "add_url" and claim.get("restaurant_id") and claim.get("direct_order_url"):
        _validate_order_url(claim["direct_order_url"])

        client.table("restaurants").update(
            {"order_url": claim["direct_order_url"]}
        ).eq("id", claim["restaurant_id"]).execute()

        upsert_listing({
            "restaurant_id": claim["restaurant_id"],
            "platform": "direct",
            "url": claim["direct_order_url"],
            "is_available": True,
        })

    client.table("restaurant_claims").update(
        {"verified": True}
    ).eq("id", claim_id).execute()


def reject_claim(claim_id: str) -> None:
    """Delete a claim (rejected — not approved)."""
    get_client().table("restaurant_claims").delete().eq("id", claim_id).execute()


# ---------------------------------------------------------------------------
# Restaurant matching helpers (Tasks 7 & 8)
# ---------------------------------------------------------------------------

def load_restaurants_for_match() -> list[dict]:
    """Load ALL restaurants with the fields the matcher scores on.

    Supabase/PostgREST caps a single response at 1000 rows, so page through
    with .range() until a short page is returned — otherwise the matcher would
    silently ignore every restaurant past the first 1000.
    """
    client = get_client()
    cols = "id, name, website, phone, lat, lng, geo_source, cuisine, created_at"
    page = 1000
    offset = 0
    rows: list[dict] = []
    while True:
        res = (
            client.table("restaurants")
            .select(cols)
            .is_("merged_into", "null")  # skip already-merged losers
            .order("id")
            .range(offset, offset + page - 1)
            .execute()
        )
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


def enqueue_decision(
    *, survivor_id: str, loser_id: str, score: float,
    features: dict, status: str,
) -> str:
    """Insert/replace a match decision row (queue or audit log). Returns id.

    Upsert on the unordered-pair unique index so re-runs don't duplicate.
    """
    client = get_client()
    # Validate before interpolating into PostgREST filter DSL — `.or_()` accepts
    # raw strings and would otherwise be a filter-injection vector.
    s = _validate_uuid(survivor_id)
    l = _validate_uuid(loser_id)
    if s == l:
        raise ValueError("survivor_id and loser_id must differ")
    existing = (
        client.table("restaurant_match_decisions")
        .select("id")
        .or_(
            f"and(survivor_id.eq.{s},loser_id.eq.{l}),"
            f"and(survivor_id.eq.{l},loser_id.eq.{s})"
        )
        .limit(1)
        .execute()
    )
    row = {
        "survivor_id": survivor_id,
        "loser_id": loser_id,
        "score": score,
        "features": features,
        "status": status,
    }
    if existing.data:
        did = existing.data[0]["id"]
        client.table("restaurant_match_decisions").update(row).eq("id", did).execute()
        return did
    res = client.table("restaurant_match_decisions").insert(row).execute()
    return res.data[0]["id"]


def merge_restaurants(survivor_id: str, loser_id: str) -> None:
    """Merge loser into survivor atomically via the merge_restaurants_atomic RPC.

    The previous Python-side multi-step implementation could leave the DB in an
    inconsistent state if any single .execute() failed mid-merge; the SQL
    function wraps the entire sequence in one transaction with row locks.
    """
    if survivor_id == loser_id:
        return
    s = _validate_uuid(survivor_id)
    l = _validate_uuid(loser_id)
    client = get_client()
    client.rpc(
        "merge_restaurants_atomic",
        {"p_survivor": s, "p_loser": l},
    ).execute()


def get_stale_queued_decisions() -> list[dict]:
    """Queued decisions where geo_dist was null at scoring time (both sides may now be venue-grade)."""
    client = get_client()
    res = (
        client.table("restaurant_match_decisions")
        .select("*")
        .eq("status", "queued")
        .execute()
    )
    return [r for r in res.data if r.get("features", {}).get("geo_dist") is None]


def get_queued_decisions(limit: int = 100, offset: int = 0) -> list[dict]:
    """Pending review-queue rows, newest first. Bounded to prevent OOM."""
    client = get_client()
    res = (
        client.table("restaurant_match_decisions")
        .select("*")
        .eq("status", "queued")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return res.data


def resolve_decision(decision_id: str, *, approve: bool, resolved_by: str) -> None:
    """Approve (-> merge) or reject a queued decision."""
    from datetime import datetime, timezone
    client = get_client()
    row = (
        client.table("restaurant_match_decisions")
        .select("id, survivor_id, loser_id, status")
        .eq("id", decision_id)
        .limit(1)
        .execute()
    )
    if not row.data:
        return
    d = row.data[0]
    if approve:
        merge_restaurants(d["survivor_id"], d["loser_id"])
    client.table("restaurant_match_decisions").update({
        "status": "approved" if approve else "rejected",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "resolved_by": resolved_by,
    }).eq("id", decision_id).execute()


def load_menu_items_for_match() -> dict[str, set[str]]:
    """Return {restaurant_id: {normalized_item_name, ...}} for menu overlap scoring.

    Joins menu_items -> platform_listings -> restaurants. Returns only restaurants
    with >= 1 item. Normalizes names: strip accents, lowercase, keep [a-z0-9].
    """
    import re as _re
    import unicodedata as _ud

    client = get_client()
    res = (
        client.table("menu_items")
        .select("name, platform_listings(restaurant_id)")
        .execute()
    )
    result: dict[str, set[str]] = {}
    for row in (res.data or []):
        rid_obj = row.get("platform_listings") or {}
        rid = str(rid_obj.get("restaurant_id", "")) if isinstance(rid_obj, dict) else ""
        if not rid or rid == "None":
            continue
        raw = row.get("name") or ""
        # normalize: strip accents, lowercase, keep [a-z0-9]
        nfkd = _ud.normalize("NFD", raw)
        no_acc = "".join(ch for ch in nfkd if _ud.category(ch) != "Mn")
        norm = _re.sub(r"[^a-z0-9]", "", no_acc.lower())
        if norm and len(norm) >= 3:
            result.setdefault(rid, set()).add(norm)
    return result


def load_slugs_for_match() -> dict[str, list[str]]:
    """Return {restaurant_id: [slug, ...]} from platform_listings."""
    client = get_client()
    res = (
        client.table("platform_listings")
        .select("restaurant_id, slug")
        .not_.is_("slug", "null")
        .execute()
    )
    result: dict[str, list[str]] = {}
    for row in (res.data or []):
        rid = str(row["restaurant_id"])
        if row["slug"]:
            result.setdefault(rid, []).append(row["slug"])
    return result
