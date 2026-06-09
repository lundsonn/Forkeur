import re
import unicodedata
import json as _json
from uuid import UUID

import pgpool
from dotenv import load_dotenv

load_dotenv()


def _build_insert(table: str, data: dict, on_conflict: str | None = None,
                  returning: str = "id") -> tuple[str, list]:
    cols = list(data.keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    if on_conflict:
        # mirror Supabase upsert: on conflict, overwrite every non-conflict column.
        # on_conflict may be composite ("a,b") — exclude each conflict column.
        conflict_cols = {c.strip() for c in on_conflict.split(",")}
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in cols if c not in conflict_cols
        )
        sql += f" ON CONFLICT ({on_conflict}) DO UPDATE SET {updates}" if updates \
            else f" ON CONFLICT ({on_conflict}) DO NOTHING"
    if returning:
        sql += f" RETURNING {returning}"
    return sql, [_coerce(v) for v in data.values()]


def _build_update(table: str, data: dict, where_col: str, where_val) -> tuple[str, list]:
    sets = ", ".join(f"{c} = %s" for c in data.keys())
    sql = f"UPDATE {table} SET {sets} WHERE {where_col} = %s"
    return sql, [_coerce(v) for v in data.values()] + [where_val]


def _coerce(v):
    """psycopg adapts dict/list to jsonb only with an explicit Jsonb wrapper;
    Supabase accepted raw dicts. Wrap dict/list as JSON strings for jsonb cols
    (features, opening_hours)."""
    if isinstance(v, (dict, list)):
        return _json.dumps(v)
    return v


def _validate_uuid(value: str) -> str:
    """Return the value if it parses as a UUID, else raise ValueError.

    PostgREST filter expressions (`.or_(...)`) accept raw strings; interpolating
    unvalidated input there opens a filter-injection vector.
    """
    UUID(str(value))
    return str(value)


_MENU_INSERT_CHUNK = 500

_SUFFIX_RE = re.compile(r"\s+-\s+\S.*$")

_domain_cache: dict[str, str] | None = None  # domain → restaurant_id


def invalidate_domain_cache() -> None:
    global _domain_cache
    _domain_cache = None


def close_client() -> None:
    """Back-compat shim — closes the psycopg pool."""
    pgpool.close_pool()


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
    'Barakah Halal' → 'Barakah'
    """
    name = name.strip()
    name = re.sub(r'[^ -ɏḀ-ỿ\s\d\'\"\-&\(\)\.!,]', '', name).strip()
    name = _SUFFIX_RE.sub("", name).strip()
    name = re.sub(r"\s+(?:brussels|bruxelles|bxl|bsl)\s*$", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(r"\s+(?:halal|bio|vegan|végétalien|casher|kosher)\s*$", "", name, flags=re.IGNORECASE).strip()
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

    5 escalating steps: exact → case-insensitive → domain lock → canonical base
    → suffixed variant → fully-normalized.
    """
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
            row = pgpool.fetchone(
                "SELECT cuisine, image_url, lat, lng, geo_source, phone, neighborhood "
                "FROM restaurants WHERE id = %s LIMIT 1", [rid]
            ) or {}
        updates: dict = {}
        if data.get("cuisine") and not row.get("cuisine"):
            updates["cuisine"] = data["cuisine"]
        if data.get("image_url") and not row.get("image_url"):
            updates["image_url"] = data["image_url"]
        if data.get("phone") and not row.get("phone"):
            updates["phone"] = data["phone"]
        if data.get("neighborhood") and not row.get("neighborhood"):
            updates["neighborhood"] = data["neighborhood"]
        incoming_src = data.get("geo_source")
        _VENUE = {"uber_eats", "direct", "takeaway"}
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
            sql, params = _build_update("restaurants", updates, "id", rid)
            pgpool.execute(sql, params)
        return str(rid)

    # 1. Exact name match
    row = pgpool.fetchone(
        f"SELECT {_MATCH_COLS} FROM restaurants WHERE name = %s LIMIT 1", [name]
    )
    if row:
        return _found(row["id"], row)

    # 2. Case-insensitive exact match
    row = pgpool.fetchone(
        f"SELECT {_MATCH_COLS} FROM restaurants WHERE name ILIKE %s LIMIT 1", [name]
    )
    if row:
        return _found(row["id"], row)

    # 2b. Website-domain lock
    import matching as _m
    incoming_domain = _m.domain_of(data.get("website"))
    if incoming_domain:
        global _domain_cache
        if _domain_cache is None:
            cands = pgpool.fetchall(
                "SELECT id, website FROM restaurants WHERE website IS NOT NULL"
            )
            _domain_cache = {}
            for c in cands:
                d = _m.domain_of(c.get("website"))
                if d:
                    _domain_cache[d] = c["id"]
        if incoming_domain in _domain_cache:
            return _found(_domain_cache[incoming_domain])

    # 3. Canonical base match
    if canonical != name:
        row = pgpool.fetchone(
            f"SELECT {_MATCH_COLS} FROM restaurants WHERE name ILIKE %s LIMIT 1",
            [canonical],
        )
        if row:
            return _found(row["id"], row)

    # 4. Suffixed variant match ("Burger King" → "Burger King - Ixelles")
    row = pgpool.fetchone(
        f"SELECT {_MATCH_COLS} FROM restaurants WHERE name ILIKE %s LIMIT 1",
        [f"{canonical} -%"],
    )
    if row:
        return _found(row["id"], row)

    # 5. Fully-normalized match by significant-word prefix
    _ARTICLES = {"le", "la", "les", "l'", "au", "aux", "un", "une", "de", "du", "the", "a"}
    words = canonical.split()
    sig_words = [w for w in words if w.lower().rstrip("'") not in _ARTICLES]
    prefix = sig_words[0] if sig_words else (words[0] if words else canonical[:5])
    if len(prefix) >= 3:
        candidates = pgpool.fetchall(
            f"SELECT name, {_MATCH_COLS} FROM restaurants WHERE name ILIKE %s",
            [f"{prefix}%"],
        )
        for cand in candidates:
            cand_norm = _normalize_for_match(cand["name"])
            cand_norm_can = _normalize_for_match(_canonical(cand["name"]))
            if cand_norm in (norm, norm_canonical) or cand_norm_can in (norm, norm_canonical):
                return _found(cand["id"], cand)

    # Not found — insert
    sql, params = _build_insert("restaurants", data, on_conflict="slug")
    row = pgpool.fetchone(sql, params)
    rid = str(row["id"])
    invalidate_domain_cache()
    return rid


def upsert_listing(data: dict) -> str:
    sql, params = _build_insert(
        "platform_listings", data, on_conflict="restaurant_id,platform"
    )
    row = pgpool.fetchone(sql, params)
    return str(row["id"])


def patch_listing(listing_id: str, data: dict) -> None:
    sql, params = _build_update("platform_listings", data, "id", listing_id)
    pgpool.execute(sql, params)


def upsert_promotions(listing_id: str, promotions: list[dict]) -> int:
    pgpool.execute("DELETE FROM promotions WHERE listing_id = %s", [listing_id])
    if not promotions:
        return 0
    saved = 0
    for p in promotions:
        sql, params = _build_insert("promotions", {"listing_id": listing_id, **p})
        pgpool.fetchone(sql, params)
        saved += 1
    return saved


def delete_menu_items(listing_id: str) -> None:
    pgpool.execute("DELETE FROM menu_items WHERE listing_id = %s", [listing_id])


def insert_menu_items(listing_id: str, items: list[dict]) -> int:
    with pgpool.get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM menu_items WHERE listing_id = %s", [listing_id])
        cur.execute(
            "UPDATE platform_listings SET last_scraped_at = now() WHERE id = %s",
            [listing_id],
        )
        if not items:
            return 0
        total = 0
        for item in items:
            row = {**item, "listing_id": listing_id}
            cols = ", ".join(row.keys())
            ph = ", ".join(["%s"] * len(row))
            # NOTE: column names come from scraper-controlled item dicts (hardcoded
            # field names), never end-user input — safe to interpolate.
            cur.execute(
                f"INSERT INTO menu_items ({cols}) VALUES ({ph})",
                [_coerce(v) for v in row.values()],
            )
            total += 1
        return total




def run_exists(run_id: str) -> bool:
    row = pgpool.fetchone("SELECT id FROM scraper_runs WHERE id = %s LIMIT 1", [run_id])
    return row is not None


def create_run(platform: str) -> str:
    row = pgpool.fetchone(
        "INSERT INTO scraper_runs (platform, status) VALUES (%s, 'running') RETURNING id",
        [platform],
    )
    return str(row["id"])


def update_run_progress(run_id: str, records_saved: int) -> None:
    pgpool.execute(
        "UPDATE scraper_runs SET records_saved = %s WHERE id = %s",
        [records_saved, run_id],
    )


def finish_run(run_id: str, status: str, records_saved: int = 0,
               error_msg: str | None = None) -> None:
    pgpool.execute(
        "UPDATE scraper_runs SET status = %s, records_saved = %s, "
        "finished_at = now(), error_msg = %s WHERE id = %s",
        [status, records_saved, error_msg, run_id],
    )


def get_runs(limit: int = 50, offset: int = 0) -> list[dict]:
    return pgpool.fetchall(
        "SELECT * FROM scraper_runs ORDER BY started_at DESC LIMIT %s OFFSET %s",
        [limit, offset],
    )


def get_run(run_id: str) -> dict | None:
    return pgpool.fetchone("SELECT * FROM scraper_runs WHERE id = %s", [run_id])


def get_last_run_per_platform() -> dict[str, dict]:
    platforms = ("ubereats", "deliveroo", "takeaway", "direct", "direct_menu", "dom_menu", "match")
    rows = pgpool.fetchall(
        "SELECT * FROM scraper_runs WHERE platform = ANY(%s) "
        "ORDER BY started_at DESC LIMIT 140",
        [list(platforms)],
    )
    seen: dict[str, dict] = {}
    for row in rows:
        p = row["platform"]
        if p not in seen:
            seen[p] = row
    return seen


def get_last_successful_run(platform: str) -> dict | None:
    return pgpool.fetchone(
        "SELECT * FROM scraper_runs WHERE platform = %s AND status = 'success' "
        "ORDER BY started_at DESC LIMIT 1",
        [platform],
    )


def get_last_successful_run_batch(platforms: list[str]) -> dict[str, dict]:
    if not platforms:
        return {}
    rows = pgpool.fetchall(
        "SELECT platform, status, started_at, finished_at, records_saved "
        "FROM scraper_runs WHERE status = 'success' AND platform = ANY(%s) "
        "ORDER BY finished_at DESC LIMIT %s",
        [platforms, len(platforms) * 5],
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
    return pgpool.execute(
        "UPDATE scraper_runs SET status = 'failed', finished_at = now(), "
        "error_msg = 'orphaned — backend restarted' "
        "WHERE status = 'running' AND started_at < now() - make_interval(hours => %s)",
        [max_age_hours],
    )


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


def set_restaurant_chain(restaurant_id: str, is_chain: bool) -> dict:
    client = get_client()
    result = (
        client.table("restaurants")
        .update({"is_chain": is_chain})
        .eq("id", restaurant_id)
        .execute()
    )
    return result.data[0]


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


def patch_restaurant_phone(restaurant_id: str, phone: str) -> None:
    """Write phone to restaurants row only if currently empty."""
    existing = get_client().table("restaurants").select("phone").eq("id", restaurant_id).limit(1).execute()
    if existing.data and not existing.data[0].get("phone"):
        get_client().table("restaurants").update({"phone": phone}).eq("id", restaurant_id).execute()


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
    cols = "id, name, website, phone, lat, lng, geo_source, cuisine, created_at, is_chain"
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


def delete_decisions(ids: list[str]) -> None:
    """Delete match decision rows by id — used to prune stale SEPARATE verdicts."""
    if not ids:
        return
    validated = [_validate_uuid(i) for i in ids]
    client = get_client()
    client.table("restaurant_match_decisions").delete().in_("id", validated).execute()


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
    """Pending review-queue rows, newest first. Bounded to prevent OOM.

    Each row is enriched with `survivor_listings` / `loser_listings`
    (platform + url) so the reviewer can open each restaurant on every
    platform to compare before approving/rejecting.
    """
    client = get_client()
    res = (
        client.table("restaurant_match_decisions")
        .select("*")
        .eq("status", "queued")
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return rows

    # Collect every restaurant id involved, fetch their listings in one query.
    rid_set: set[str] = set()
    for d in rows:
        if d.get("survivor_id"):
            rid_set.add(d["survivor_id"])
        if d.get("loser_id"):
            rid_set.add(d["loser_id"])

    listings_by_rid: dict[str, list[dict]] = {}
    if rid_set:
        lres = (
            client.table("platform_listings")
            .select("restaurant_id, platform, url")
            .in_("restaurant_id", list(rid_set))
            .execute()
        )
        for row in lres.data or []:
            rid = row.get("restaurant_id")
            if not rid or not row.get("url"):
                continue
            listings_by_rid.setdefault(rid, []).append(
                {"platform": row.get("platform"), "url": row["url"]}
            )

    for d in rows:
        d["survivor_listings"] = listings_by_rid.get(d.get("survivor_id"), [])
        d["loser_listings"] = listings_by_rid.get(d.get("loser_id"), [])
    return rows


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
    result: dict[str, set[str]] = {}
    page = 1000
    offset = 0
    while True:
        res = (
            client.table("menu_items")
            .select("title, platform_listings(restaurant_id)")
            .range(offset, offset + page - 1)
            .execute()
        )
        batch = res.data or []
        for row in batch:
            rid_obj = row.get("platform_listings") or {}
            rid = str(rid_obj.get("restaurant_id", "")) if isinstance(rid_obj, dict) else ""
            if not rid or rid == "None":
                continue
            raw = row.get("title") or ""
            nfkd = _ud.normalize("NFD", raw)
            no_acc = "".join(ch for ch in nfkd if _ud.category(ch) != "Mn")
            norm = _re.sub(r"[^a-z0-9]", "", no_acc.lower())
            if norm and len(norm) >= 3:
                result.setdefault(rid, set()).add(norm)
        if len(batch) < page:
            break
        offset += page
    return result


def load_slugs_for_match() -> dict[str, list[str]]:
    """Return {restaurant_id: [url_path_segment, ...]} from platform_listings.url.

    Extracts the last meaningful path segment from each listing URL so the
    location-token detector can read e.g. 'sushi-palace-ixelles' from a
    Deliveroo/UberEats URL. No 'slug' column exists on platform_listings.
    """
    from urllib.parse import urlparse
    client = get_client()
    result: dict[str, list[str]] = {}
    page = 1000
    offset = 0
    while True:
        res = (
            client.table("platform_listings")
            .select("restaurant_id, url")
            .not_.is_("url", "null")
            .range(offset, offset + page - 1)
            .execute()
        )
        batch = res.data or []
        for row in batch:
            rid = str(row.get("restaurant_id") or "")
            url = row.get("url") or ""
            if not rid or rid == "None" or not url:
                continue
            try:
                path = urlparse(url).path.rstrip("/")
                segments = [s for s in path.split("/") if s]
                # Skip UUID/hash-like final segments (e.g. UberEats
                # /store/{slug}/{UUID} — last segment is opaque, second-to-last
                # is the human-readable slug).
                slug = None
                for seg in reversed(segments):
                    if len(seg) >= 3 and not re.match(r'^[A-Za-z0-9_\-]{20,}$', seg):
                        slug = seg
                        break
                if slug:
                    result.setdefault(rid, []).append(slug)
            except Exception:
                continue
        if len(batch) < page:
            break
        offset += page
    return result


def load_listing_addresses_for_match() -> dict[str, dict]:
    """Return {restaurant_id: {"street_address": ..., "postal_code": ...}} from platform_listings."""
    client = get_client()
    res = (
        client.table("platform_listings")
        .select("restaurant_id, street_address, postal_code")
        .not_.is_("street_address", "null")
        .execute()
    )
    result: dict[str, dict] = {}
    for row in res.data or []:
        rid = str(row.get("restaurant_id") or "")
        if not rid or rid == "None":
            continue
        if rid not in result or (not result[rid].get("postal_code") and row.get("postal_code")):
            result[rid] = {
                "street_address": row.get("street_address"),
                "postal_code": row.get("postal_code"),
            }
    return result
