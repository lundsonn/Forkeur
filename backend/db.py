import os
import re
import unicodedata
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_KEY"]
        _client = create_client(url, key)
    return _client


def _is_junk(name: str) -> bool:
    """Return True if the name looks like a scraped UI element, not a real restaurant."""
    s = name.strip().lower()
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
        # Geo provenance: a venue-grade source (uber_eats/direct) always wins and
        # stamps geo_source; a zone-grade source (deliveroo) only fills coords when
        # the row has none, and never clobbers venue-grade coords.
        incoming_src = data.get("geo_source")
        if data.get("lat") is not None and data.get("lng") is not None:
            if incoming_src in ("uber_eats", "direct"):
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
        cands = (
            client.table("restaurants")
            .select(f"website, {_MATCH_COLS}")
            .not_.is_("website", "null")
            .execute()
        )
        for c in cands.data:
            if _m.domain_of(c.get("website")) == incoming_domain:
                return _found(c["id"], c)

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
    return res.data[0]["id"]


def upsert_listing(data: dict) -> str:
    """Upsert platform_listing by restaurant_id + platform. Returns id."""
    client = get_client()
    existing = (
        client.table("platform_listings")
        .select("id")
        .eq("restaurant_id", data["restaurant_id"])
        .eq("platform", data["platform"])
        .execute()
    )
    if existing.data:
        lid = existing.data[0]["id"]
        client.table("platform_listings").update(data).eq("id", lid).execute()
        return lid
    res = client.table("platform_listings").insert(data).execute()
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
    res = client.table("menu_items").insert(rows).execute()
    return len(res.data)


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
    client = get_client()
    result = {}
    for platform in ("ubereats", "deliveroo", "takeaway", "fees", "direct", "direct_menu", "dom_menu", "match"):
        res = (
            client.table("scraper_runs")
            .select("*")
            .eq("platform", platform)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            result[platform] = res.data[0]
    return result


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
    deleted = 0
    for row in stale:
        res = client.table("menu_items").delete().eq("listing_id", row["id"]).execute()
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
    q = client.table("restaurants").select("*").range(offset, offset + limit - 1)
    if search:
        q = q.ilike("name", f"%{search}%")
    return q.execute().data


def get_menu_items(listing_id: str) -> list[dict]:
    client = get_client()
    return (
        client.table("menu_items")
        .select("*")
        .eq("listing_id", listing_id)
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


def patch_restaurant_website(restaurant_id: str, website: str | None, order_url: str | None) -> None:
    from datetime import datetime, timezone
    get_client().table("restaurants").update({
        "website": website,
        "order_url": order_url,
        "website_searched_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", restaurant_id).execute()


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


_SSRF_BLOCKLIST = re.compile(
    r'localhost|127\.|0\.0\.0\.0|169\.254\.|10\.\d|172\.(1[6-9]|2\d|3[01])\.|192\.168\.'
    r'|\.internal|\.local$|oast\.|interactsh\.|burpcollaborator\.|canarytokens\.',
    re.IGNORECASE,
)


def _validate_order_url(url: str) -> None:
    """Raise ValueError if the URL looks unsafe to publish."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must be http or https")
    host = parsed.netloc.lower().split(":")[0]
    if not host or "." not in host:
        raise ValueError("URL must have a valid domain")
    if _SSRF_BLOCKLIST.search(host):
        raise ValueError(f"URL domain not allowed: {host}")


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
    # The uq_match_pair uniqueness is an expression index (least/greatest) that
    # PostgREST cannot target via on_conflict, so reconcile the unordered pair
    # manually: update an existing row for either ordering, else insert.
    existing = (
        client.table("restaurant_match_decisions")
        .select("id")
        .or_(
            f"and(survivor_id.eq.{survivor_id},loser_id.eq.{loser_id}),"
            f"and(survivor_id.eq.{loser_id},loser_id.eq.{survivor_id})"
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


def _fetch_restaurant(client, rid: str) -> dict | None:
    res = client.table("restaurants").select(
        "id, phone, website, lat, lng, geo_source, cuisine, image_url"
    ).eq("id", rid).limit(1).execute()
    return res.data[0] if res.data else None


def merge_restaurants(survivor_id: str, loser_id: str) -> None:
    """Merge loser into survivor: move listings, fill nulls, delete loser.

    Idempotent: if loser is already gone, this is a no-op. Same-platform
    listing conflicts keep the row with the newer last_scraped_at.
    """
    if survivor_id == loser_id:
        return
    client = get_client()
    survivor = _fetch_restaurant(client, survivor_id)
    loser = _fetch_restaurant(client, loser_id)
    if survivor is None or loser is None:
        return  # already merged / missing

    # 1. Listings: detect same-platform conflicts.
    surv_listings = client.table("platform_listings").select(
        "id, platform, last_scraped_at"
    ).eq("restaurant_id", survivor_id).execute().data
    lose_listings = client.table("platform_listings").select(
        "id, platform, last_scraped_at"
    ).eq("restaurant_id", loser_id).execute().data

    from postgrest.exceptions import APIError
    surv_by_platform = {l["platform"]: l for l in surv_listings}
    for ll in lose_listings:
        clash = surv_by_platform.get(ll["platform"])
        if clash is not None:
            # Keep the row with the newer scrape; drop the other.
            keep_loser = (ll.get("last_scraped_at") or "") > (clash.get("last_scraped_at") or "")
            if not keep_loser:
                client.table("platform_listings").delete().eq("id", ll["id"]).execute()
                continue
            client.table("platform_listings").delete().eq("id", clash["id"]).execute()
        # Move the loser's listing to the survivor. Guard against any residual
        # (restaurant_id, platform) collision the pre-scan didn't catch — on a
        # unique-violation just drop the duplicate loser listing instead of
        # aborting the whole merge.
        try:
            client.table("platform_listings").update(
                {"restaurant_id": survivor_id}
            ).eq("id", ll["id"]).execute()
        except APIError:
            client.table("platform_listings").delete().eq("id", ll["id"]).execute()

    # 2. Fill survivor null fields from loser.
    fill = {}
    for k in ("phone", "website", "lat", "lng", "geo_source", "cuisine", "image_url"):
        if not survivor.get(k) and loser.get(k):
            fill[k] = loser[k]
    if fill:
        client.table("restaurants").update(fill).eq("id", survivor_id).execute()

    # 3. Delete loser.
    client.table("restaurants").delete().eq("id", loser_id).execute()


def get_queued_decisions() -> list[dict]:
    """Pending review-queue rows, newest first."""
    client = get_client()
    res = (
        client.table("restaurant_match_decisions")
        .select("*")
        .eq("status", "queued")
        .order("created_at", desc=True)
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
