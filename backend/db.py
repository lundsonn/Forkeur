import re
import unicodedata
import json as _json
from uuid import UUID

import pgpool
from dotenv import load_dotenv

load_dotenv()


def _build_insert(table: str, data: dict, on_conflict: str | None = None,
                  returning: str = "id",
                  preserve_if_null: set[str] | None = None) -> tuple[str, list]:
    cols = list(data.keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    if on_conflict:
        # mirror Supabase upsert: on conflict, overwrite every non-conflict column.
        # on_conflict may be composite ("a,b") — exclude each conflict column.
        # For columns in preserve_if_null, keep the existing value when the
        # incoming EXCLUDED value is NULL (a fee-only refresh shouldn't wipe a
        # previously-scraped rating, eta, etc.).
        conflict_cols = {c.strip() for c in on_conflict.split(",")}
        preserve = preserve_if_null or set()
        update_cols = [c for c in cols if c not in conflict_cols]
        updates = ", ".join(
            f"{c} = COALESCE(EXCLUDED.{c}, {table}.{c})" if c in preserve
            else f"{c} = EXCLUDED.{c}"
            for c in update_cols
        )
        sql += f" ON CONFLICT ({on_conflict}) DO UPDATE SET {updates}" if updates \
            else f" ON CONFLICT ({on_conflict}) DO NOTHING"
    if returning:
        sql += f" RETURNING {returning}"
    return sql, [_coerce(v) for v in data.values()]


# Fee/quality columns whose incoming NULL should NOT clobber a prior scrape:
# a fee-only refresh (or a scrape that missed these) keeps the existing value.
# Deliberately excludes is_available/discount_label/url/opening_hours/url_type/
# street_address/postal_code — those must hard-update on every upsert.
_PRESERVE_ON_NULL = {
    "delivery_fee", "eta_min", "eta_max", "service_fee",
    "min_order", "rating", "review_count",
}

# Fee/timing columns captured per-upsert into fee_snapshots for historical trends.
_FEE_SNAPSHOT_KEYS = ("delivery_fee", "eta_min", "eta_max", "min_order")


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
    """Return True if the name looks like a scraped UI element, not a real restaurant.

    Deliveroo's feed interleaves promo tiles and ETA labels with restaurant
    cards; the scraper occasionally captures one as a name ("Environ 25 min",
    "Profitez de -10 %", "1 plat acheté = 1 plat offert"). Two robustness
    fixes over the original: strip Unicode format/bidi marks first (Deliveroo
    wraps percentages in U+202A/U+202C, which split "-10 %" so an anchored
    minus-digits-percent pattern never matched), and use re.search so a promo
    phrase anywhere in the string is caught, not only at the start.
    """
    # Drop Unicode "format" chars (Cf: bidi embeds, ZWJ, soft hyphen) that
    # Deliveroo injects around numbers and would otherwise break the patterns.
    cleaned = "".join(ch for ch in name if unicodedata.category(ch) != "Cf")
    s = cleaned.strip().lower()
    # Cap input length before the alternation regex — the `[\s-]?\d` branches
    # can backtrack quadratically. Real restaurant names stay under a few
    # hundred chars. (Empty-name validation lives at the caller, not here.)
    if len(s) > 300:
        return False
    return bool(re.search(
        r'(around\s+\d|environ\s+\d+\s*min|pre[\s-]?order\s+\d'
        r'|pré[\s-]?commande\s+\d|article\s+offert|\bplats?\s+offert'
        r'|\d+\s*plats?\s+achet|profitez\s+de|\d+e?\s*à\s*moiti'
        r'|\d+\s*%\s+off|-\s*\d+\s*%|•\s*à\s+partir|\d+e\s+à\s+moitié)',
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


def insert_fee_snapshot(listing_id: str, data: dict) -> None:
    """Append a row to fee_snapshots for the present fee/timing keys.

    Best-effort: any failure (e.g. the table not yet created pre-migration)
    is swallowed so it can never break the listing upsert.
    """
    present = {k: data[k] for k in _FEE_SNAPSHOT_KEYS if data.get(k) is not None}
    if not present:
        return
    cols = ["listing_id"] + list(present.keys())
    vals = [listing_id] + list(present.values())
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    try:
        pgpool.execute(
            f"INSERT INTO fee_snapshots ({col_list}) VALUES ({placeholders})", vals
        )
    except Exception:  # pragma: no cover - defensive (missing table, etc.)
        pass


def upsert_listing(data: dict) -> str:
    sql, params = _build_insert(
        "platform_listings", data, on_conflict="restaurant_id,platform",
        preserve_if_null=_PRESERVE_ON_NULL,
    )
    row = pgpool.fetchone(sql, params)
    lid = str(row["id"])
    # Always refresh freshness so a fee-only refresh keeps the listing visible.
    pgpool.execute(
        "UPDATE platform_listings SET last_scraped_at = now() WHERE id = %s", [lid]
    )
    insert_fee_snapshot(lid, data)
    return lid


def patch_listing(listing_id: str, data: dict) -> None:
    sql, params = _build_update("platform_listings", data, "id", listing_id)
    pgpool.execute(sql, params)


def upsert_promotions(listing_id: str, promotions: list[dict]) -> int:
    # One connection = one transaction: the DELETE and every INSERT commit or
    # roll back together. The previous version ran the DELETE and each INSERT on
    # SEPARATE pooled connections, so a mid-loop failure committed the DELETE and
    # lost the listing's promos (and cost one pool round-trip per promo).
    with pgpool.get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM promotions WHERE listing_id = %s", [listing_id])
        if not promotions:
            return 0
        for p in promotions:
            row = {"listing_id": listing_id, **p}
            cols = ", ".join(row.keys())
            ph = ", ".join(["%s"] * len(row))
            # column names come from scraper-controlled promo dicts (hardcoded
            # field names), never end-user input — safe to interpolate (mirrors
            # insert_menu_items).
            cur.execute(
                f"INSERT INTO promotions ({cols}) VALUES ({ph})",
                [_coerce(v) for v in row.values()],
            )
        return len(promotions)


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
            # Stamp scraped_at = now() so insert-time freshness is recorded even
            # when last_scraped_at on the listing later goes NULL (drives the
            # COALESCE cleanup predicates and reaps immortal rows).
            cur.execute(
                f"INSERT INTO menu_items ({cols}, scraped_at) VALUES ({ph}, now())",
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


def finish_run(
    run_id: str, status: str, records_saved: int = 0, error_msg: str | None = None, *,
    peak_ram_mb: int | None = None, avg_ram_mb: int | None = None,
    phase_durations: dict | None = None, cooldown_hits: int = 0,
    items_attempted: int = 0, items_skipped: int = 0, items_failed: int = 0,
    concurrent_with: list[str] | None = None,
) -> None:
    import json as _json
    pgpool.execute(
        "UPDATE scraper_runs SET status = %s, records_saved = %s, "
        "finished_at = now(), error_msg = %s, "
        "peak_ram_mb = %s, avg_ram_mb = %s, "
        "phase_durations = %s::jsonb, "
        "cooldown_hits = %s, items_attempted = %s, items_skipped = %s, items_failed = %s, "
        "concurrent_with = %s WHERE id = %s",
        [
            status, records_saved, error_msg,
            peak_ram_mb, avg_ram_mb,
            _json.dumps(phase_durations) if phase_durations else None,
            cooldown_hits, items_attempted, items_skipped, items_failed,
            concurrent_with or [], run_id,
        ],
    )


def get_runs(limit: int = 50, offset: int = 0) -> list[dict]:
    return pgpool.fetchall(
        "SELECT * FROM scraper_runs ORDER BY started_at DESC LIMIT %s OFFSET %s",
        [limit, offset],
    )


def get_run(run_id: str) -> dict | None:
    return pgpool.fetchone("SELECT * FROM scraper_runs WHERE id = %s", [run_id])


def get_last_run_per_platform() -> dict[str, dict]:
    platforms = ("ubereats", "deliveroo", "takeaway", "direct", "direct_menu", "dom_menu", "match", "cleanup")
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
    # COALESCE last_scraped_at→scraped_at so a row that never had its listing
    # freshness bumped (NULL last_scraped_at) is still reaped via insert time.
    return pgpool.execute(
        "DELETE FROM platform_listings "
        "WHERE COALESCE(last_scraped_at, scraped_at) < now() - make_interval(days => %s)",
        [days],
    )


def prune_stale_menu_items(days: int = 30) -> int:
    stale = pgpool.fetchall(
        "SELECT id FROM platform_listings "
        "WHERE COALESCE(last_scraped_at, scraped_at) < now() - make_interval(days => %s)",
        [days],
    )
    if not stale:
        return 0
    ids = [row["id"] for row in stale]
    return pgpool.execute(
        "DELETE FROM menu_items WHERE listing_id = ANY(%s)", [ids]
    )


def orphan_stale_runs(max_age_hours: int = 2) -> int:
    return pgpool.execute(
        "UPDATE scraper_runs SET status = 'failed', finished_at = now(), "
        "error_msg = 'orphaned — backend restarted' "
        "WHERE status = 'running' AND started_at < now() - make_interval(hours => %s)",
        [max_age_hours],
    )


def get_restaurants(limit: int = 100, offset: int = 0, search: str | None = None) -> list[dict]:
    if search:
        return pgpool.fetchall(
            "SELECT * FROM restaurants WHERE name ILIKE %s ORDER BY id LIMIT %s OFFSET %s",
            [f"%{search}%", limit, offset],
        )
    return pgpool.fetchall(
        "SELECT * FROM restaurants ORDER BY id LIMIT %s OFFSET %s", [limit, offset]
    )


def set_restaurant_chain(restaurant_id: str, is_chain: bool) -> dict:
    return pgpool.fetchone(
        "UPDATE restaurants SET is_chain = %s WHERE id = %s RETURNING *",
        [is_chain, restaurant_id],
    )


def get_menu_items(listing_id: str) -> list[dict]:
    return pgpool.fetchall(
        "SELECT * FROM menu_items WHERE listing_id = %s LIMIT 2000", [listing_id]
    )


def get_listings_with_urls(platform: str) -> list[dict]:
    return pgpool.fetchall(
        "SELECT id, restaurant_id, url, delivery_fee, min_order FROM platform_listings "
        "WHERE platform = %s AND url IS NOT NULL",
        [platform],
    )


_GEO_RANK = {"uber_eats": 3, "direct": 3, "deliveroo_venue": 2, "deliveroo": 1}


def patch_restaurant_geo(restaurant_id: str, lat: float, lng: float, geo_source: str) -> None:
    existing = pgpool.fetchone(
        "SELECT geo_source FROM restaurants WHERE id = %s LIMIT 1", [restaurant_id]
    )
    if existing:
        current_src = existing.get("geo_source")
        if _GEO_RANK.get(current_src, 0) >= _GEO_RANK.get(geo_source, 0):
            return
    pgpool.execute(
        "UPDATE restaurants SET lat = %s, lng = %s, geo_source = %s WHERE id = %s",
        [lat, lng, geo_source, restaurant_id],
    )


def patch_restaurant_website(restaurant_id: str, website: str | None, order_url: str | None) -> None:
    pgpool.execute(
        "UPDATE restaurants SET website = %s, order_url = %s, website_searched_at = now() "
        "WHERE id = %s",
        [website, order_url, restaurant_id],
    )
    invalidate_domain_cache()


def patch_restaurant_phone(restaurant_id: str, phone: str) -> None:
    existing = pgpool.fetchone(
        "SELECT phone FROM restaurants WHERE id = %s LIMIT 1", [restaurant_id]
    )
    if existing and not existing.get("phone"):
        pgpool.execute(
            "UPDATE restaurants SET phone = %s WHERE id = %s", [phone, restaurant_id]
        )


def mark_restaurant_searched(restaurant_id: str) -> None:
    pgpool.execute(
        "UPDATE restaurants SET website_searched_at = now() WHERE id = %s",
        [restaurant_id],
    )


def insert_claim(owner_email: str, inquiry_type: str = "add_url",
                 restaurant_id: str | None = None, direct_order_url: str | None = None,
                 restaurant_name_free: str | None = None) -> str:
    row = pgpool.fetchone(
        "INSERT INTO restaurant_claims "
        "(restaurant_id, owner_email, direct_order_url, inquiry_type, "
        " restaurant_name_free, verified) "
        "VALUES (%s, %s, %s, %s, %s, false) RETURNING id",
        [restaurant_id, owner_email, direct_order_url, inquiry_type, restaurant_name_free],
    )
    return str(row["id"])


def get_claims(verified: bool | None = None) -> list[dict]:
    base = (
        "SELECT c.id, c.restaurant_id, c.owner_email, c.direct_order_url, "
        "c.inquiry_type, c.restaurant_name_free, c.verified, c.claimed_at, "
        "json_build_object('name', r.name) AS restaurants "
        "FROM restaurant_claims c LEFT JOIN restaurants r ON r.id = c.restaurant_id"
    )
    if verified is not None:
        return pgpool.fetchall(
            base + " WHERE c.verified = %s ORDER BY c.claimed_at DESC", [verified]
        )
    return pgpool.fetchall(base + " ORDER BY c.claimed_at DESC")


def _validate_order_url(url: str) -> None:
    """Raise ValueError if the URL looks unsafe to publish (delegated to ssrf module)."""
    from ssrf_guard import validate_public_url
    validate_public_url(url)


def approve_claim(claim_id: str) -> None:
    claim = pgpool.fetchone(
        "SELECT id, restaurant_id, direct_order_url, inquiry_type "
        "FROM restaurant_claims WHERE id = %s", [claim_id]
    )
    if not claim:
        raise ValueError(f"Claim not found: {claim_id!r}")
    if (claim.get("inquiry_type") == "add_url" and claim.get("restaurant_id")
            and claim.get("direct_order_url")):
        _validate_order_url(claim["direct_order_url"])
        pgpool.execute(
            "UPDATE restaurants SET order_url = %s WHERE id = %s",
            [claim["direct_order_url"], claim["restaurant_id"]],
        )
        upsert_listing({
            "restaurant_id": claim["restaurant_id"],
            "platform": "direct",
            "url": claim["direct_order_url"],
            "is_available": True,
        })
    pgpool.execute(
        "UPDATE restaurant_claims SET verified = true WHERE id = %s", [claim_id]
    )


def reject_claim(claim_id: str) -> None:
    pgpool.execute("DELETE FROM restaurant_claims WHERE id = %s", [claim_id])


# ---------------------------------------------------------------------------
# Restaurant matching helpers (Tasks 7 & 8)
# ---------------------------------------------------------------------------

def load_restaurants_for_match() -> list[dict]:
    return pgpool.fetchall(
        "SELECT id, name, website, phone, lat, lng, geo_source, cuisine, created_at, "
        "is_chain FROM restaurants WHERE merged_into IS NULL ORDER BY id"
    )


def enqueue_decision(*, survivor_id: str, loser_id: str, score: float,
                     features: dict, status: str) -> str:
    s = _validate_uuid(survivor_id)
    l = _validate_uuid(loser_id)
    if s == l:
        raise ValueError("survivor_id and loser_id must differ")
    existing = pgpool.fetchone(
        "SELECT id FROM restaurant_match_decisions "
        "WHERE (survivor_id = %s AND loser_id = %s) "
        "   OR (survivor_id = %s AND loser_id = %s) LIMIT 1",
        [s, l, l, s],
    )
    if existing:
        did = existing["id"]
        pgpool.execute(
            "UPDATE restaurant_match_decisions "
            "SET survivor_id = %s, loser_id = %s, score = %s, features = %s, status = %s "
            "WHERE id = %s",
            [survivor_id, loser_id, score, _coerce(features), status, did],
        )
        return str(did)
    row = pgpool.fetchone(
        "INSERT INTO restaurant_match_decisions "
        "(survivor_id, loser_id, score, features, status) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        [survivor_id, loser_id, score, _coerce(features), status],
    )
    return str(row["id"])


def merge_restaurants(survivor_id: str, loser_id: str) -> None:
    if survivor_id == loser_id:
        return
    s = _validate_uuid(survivor_id)
    l = _validate_uuid(loser_id)
    pgpool.execute("SELECT merge_restaurants_atomic(%s, %s)", [s, l])


def delete_decisions(ids: list[str]) -> None:
    if not ids:
        return
    validated = [_validate_uuid(i) for i in ids]
    pgpool.execute(
        "DELETE FROM restaurant_match_decisions WHERE id = ANY(%s)", [validated]
    )


def get_stale_queued_decisions() -> list[dict]:
    rows = pgpool.fetchall(
        "SELECT * FROM restaurant_match_decisions WHERE status = 'queued'"
    )
    return [r for r in rows if (r.get("features") or {}).get("geo_dist") is None]


def get_queued_decisions(limit: int = 100, offset: int = 0) -> list[dict]:
    rows = pgpool.fetchall(
        "SELECT * FROM restaurant_match_decisions WHERE status = 'queued' "
        "ORDER BY created_at DESC LIMIT %s OFFSET %s",
        [limit, offset],
    )
    if not rows:
        return rows
    rid_set: set[str] = set()
    for d in rows:
        if d.get("survivor_id"):
            rid_set.add(d["survivor_id"])
        if d.get("loser_id"):
            rid_set.add(d["loser_id"])
    listings_by_rid: dict[str, list[dict]] = {}
    if rid_set:
        lrows = pgpool.fetchall(
            "SELECT restaurant_id, platform, url FROM platform_listings "
            "WHERE restaurant_id = ANY(%s)",
            [list(rid_set)],
        )
        for row in lrows:
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
    d = pgpool.fetchone(
        "SELECT id, survivor_id, loser_id, status FROM restaurant_match_decisions "
        "WHERE id = %s LIMIT 1", [decision_id]
    )
    if not d:
        return
    if approve:
        merge_restaurants(d["survivor_id"], d["loser_id"])
    pgpool.execute(
        "UPDATE restaurant_match_decisions SET status = %s, resolved_at = now(), "
        "resolved_by = %s WHERE id = %s",
        ["approved" if approve else "rejected", resolved_by, decision_id],
    )


def load_menu_items_for_match() -> dict[str, set[str]]:
    import re as _re
    import unicodedata as _ud
    rows = pgpool.fetchall(
        "SELECT mi.title, pl.restaurant_id "
        "FROM menu_items mi JOIN platform_listings pl ON pl.id = mi.listing_id"
    )
    result: dict[str, set[str]] = {}
    for row in rows:
        rid = str(row.get("restaurant_id") or "")
        if not rid or rid == "None":
            continue
        raw = row.get("title") or ""
        nfkd = _ud.normalize("NFD", raw)
        no_acc = "".join(ch for ch in nfkd if _ud.category(ch) != "Mn")
        norm = _re.sub(r"[^a-z0-9]", "", no_acc.lower())
        if norm and len(norm) >= 3:
            result.setdefault(rid, set()).add(norm)
    return result


def load_slugs_for_match() -> dict[str, list[str]]:
    from urllib.parse import urlparse
    rows = pgpool.fetchall(
        "SELECT restaurant_id, url FROM platform_listings WHERE url IS NOT NULL"
    )
    result: dict[str, list[str]] = {}
    for row in rows:
        rid = str(row.get("restaurant_id") or "")
        url = row.get("url") or ""
        if not rid or rid == "None" or not url:
            continue
        try:
            path = urlparse(url).path.rstrip("/")
            segments = [s for s in path.split("/") if s]
            slug = None
            for seg in reversed(segments):
                if len(seg) >= 3 and not re.match(r'^[A-Za-z0-9_\-]{20,}$', seg):
                    slug = seg
                    break
            if slug:
                result.setdefault(rid, []).append(slug)
        except Exception:
            continue
    return result


def load_listing_addresses_for_match() -> dict[str, dict]:
    rows = pgpool.fetchall(
        "SELECT restaurant_id, street_address, postal_code FROM platform_listings "
        "WHERE street_address IS NOT NULL"
    )
    result: dict[str, dict] = {}
    for row in rows:
        rid = str(row.get("restaurant_id") or "")
        if not rid or rid == "None":
            continue
        if rid not in result or (not result[rid].get("postal_code") and row.get("postal_code")):
            result[rid] = {
                "street_address": row.get("street_address"),
                "postal_code": row.get("postal_code"),
            }
    return result


# ---------------------------------------------------------------------------
# Public reads (frontend) — return PostgREST-shaped nested JSON
# ---------------------------------------------------------------------------

def get_public_restaurants() -> list[dict]:
    """Homepage: every non-merged restaurant with its listings (short shape)."""
    return pgpool.fetchall(
        """
        SELECT r.id, r.name, r.cuisine, r.neighborhood, r.lat, r.lng,
               r.order_url, r.image_url, r.is_chain,
               COALESCE(
                 json_agg(
                   json_build_object(
                     'platform', pl.platform, 'delivery_fee', pl.delivery_fee,
                     'min_order', pl.min_order,
                     'eta_min', pl.eta_min, 'url_type', pl.url_type,
                     'is_available', pl.is_available, 'opening_hours', pl.opening_hours,
                     'last_scraped_at', pl.last_scraped_at
                   )
                 ) FILTER (WHERE pl.id IS NOT NULL), '[]'
               ) AS platform_listings
        FROM restaurants r
        LEFT JOIN platform_listings pl ON pl.restaurant_id = r.id
          AND pl.last_scraped_at > now() - interval '72 hours'
        WHERE r.merged_into IS NULL
        GROUP BY r.id
        """
    )

def get_public_restaurant_detail(restaurant_id: str) -> dict | None:
    """Detail page: one restaurant, listings with nested menu_items + promotions."""
    _validate_uuid(restaurant_id)
    return pgpool.fetchone(
        """
        SELECT r.id, r.name, r.neighborhood, r.cuisine, r.phone,
               r.phone_confidence, r.order_channel,
               r.order_url, r.image_url,
               COALESCE(
                 json_agg(
                   json_build_object(
                     'id', pl.id, 'platform', pl.platform, 'url', pl.url,
                     'url_type', pl.url_type, 'is_available', pl.is_available,
                     'opening_hours', pl.opening_hours, 'delivery_fee', pl.delivery_fee,
                     'min_order', pl.min_order, 'eta_min', pl.eta_min,
                     'eta_max', pl.eta_max, 'rating', pl.rating,
                     'last_scraped_at', pl.last_scraped_at,
                     'menu_items', COALESCE((
                       SELECT json_agg(json_build_object(
                         'title', mi.title, 'price', mi.price,
                         'catalog_name', mi.catalog_name, 'image_url', mi.image_url,
                         'description', mi.description))
                       FROM menu_items mi WHERE mi.listing_id = pl.id), '[]'),
                     'promotions', COALESCE((
                       SELECT json_agg(json_build_object(
                         'promo_type', pr.promo_type, 'label', pr.label, 'value', pr.value))
                       FROM promotions pr WHERE pr.listing_id = pl.id), '[]')
                   )
                 ) FILTER (WHERE pl.id IS NOT NULL), '[]'
               ) AS platform_listings
        FROM restaurants r
        LEFT JOIN platform_listings pl ON pl.restaurant_id = r.id
        WHERE r.id = %s
        GROUP BY r.id
        """,
        [restaurant_id],
    )

def get_public_deals() -> list[dict]:
    """Deals page: promotions joined to listing + restaurant (nested shape)."""
    return pgpool.fetchall(
        """
        SELECT p.id, p.promo_type, p.label, p.value, p.min_order,
               json_build_object(
                 'platform', pl.platform, 'url', pl.url, 'rating', pl.rating,
                 'review_count', pl.review_count, 'is_available', pl.is_available,
                 'opening_hours', pl.opening_hours,
                 'last_scraped_at', pl.last_scraped_at,
                 'restaurants', json_build_object(
                   'id', r.id, 'name', r.name, 'cuisine', r.cuisine,
                   'neighborhood', r.neighborhood)
               ) AS platform_listings
        FROM promotions p
        JOIN platform_listings pl ON pl.id = p.listing_id
        JOIN restaurants r ON r.id = pl.restaurant_id
        WHERE p.promo_type NOT IN ('other', 'spend_save')
          AND pl.last_scraped_at > now() - interval '72 hours'
        """
    )

def get_latest_run(platform: str, since_iso: str | None = None) -> dict | None:
    """Most recent run for a platform, optionally only if started since a cutoff."""
    if since_iso:
        return pgpool.fetchone(
            "SELECT started_at FROM scraper_runs WHERE platform = %s "
            "AND started_at >= %s ORDER BY started_at DESC LIMIT 1",
            [platform, since_iso],
        )
    return pgpool.fetchone(
        "SELECT started_at FROM scraper_runs WHERE platform = %s "
        "ORDER BY started_at DESC LIMIT 1",
        [platform],
    )


# ---------------------------------------------------------------------------
# PostgREST compatibility shim
# ---------------------------------------------------------------------------
# direct.py, direct_menu.py, dom_menu/, scheduler.py, website_finder.py and a
# few one-off scripts were written against the Supabase python client's
# query-builder and were never ported to explicit SQL during the
# self-hosted-Postgres migration. Instead of rewriting each call site,
# get_client() returns a minimal builder that translates the exact subset of
# the PostgREST API those modules use into parameterised SQL via pgpool.
# Identifiers come from hardcoded module strings (never user input) but are
# still validated to be safe SQL identifiers.

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_ident(name: str) -> str:
    if not _IDENT_RE.match(name.strip()):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name.strip()


def _check_cols(cols: str) -> str:
    if cols.strip() == "*":
        return "*"
    parts = [_check_ident(c) for c in cols.split(",")]
    return ", ".join(parts)


class _Result:
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data


class _Query:
    """Accumulates a PostgREST-style chain, then runs one SQL statement."""

    def __init__(self, table: str):
        self._table = _check_ident(table)
        self._op = "select"
        self._cols = "*"
        self._payload = None
        self._on_conflict = None
        self._where: list[tuple[str, list]] = []
        self._negate = False
        self._order_col: str | None = None
        self._limit_val: int | None = None

    # operation selectors ------------------------------------------------
    def select(self, cols: str = "*"):
        self._op, self._cols = "select", _check_cols(cols)
        return self

    def insert(self, data):
        self._op, self._payload = "insert", data
        return self

    def update(self, data):
        self._op, self._payload = "update", data
        return self

    def upsert(self, data, on_conflict=None):
        self._op, self._payload, self._on_conflict = "upsert", data, on_conflict
        return self

    def delete(self):
        self._op = "delete"
        return self

    # filters ------------------------------------------------------------
    @property
    def not_(self):
        self._negate = True
        return self

    def _push(self, pos: str, neg: str, params: list):
        self._where.append((neg if self._negate else pos, params))
        self._negate = False
        return self

    def eq(self, col, val):
        c = _check_ident(col)
        return self._push(f"{c} = %s", f"{c} <> %s", [val])

    def neq(self, col, val):
        c = _check_ident(col)
        return self._push(f"{c} <> %s", f"{c} = %s", [val])

    def is_(self, col, _val="null"):
        # only ever called as .is_(col, 'null') / .not_.is_(col, 'null')
        c = _check_ident(col)
        return self._push(f"{c} IS NULL", f"{c} IS NOT NULL", [])

    def in_(self, col, vals):
        c = _check_ident(col)
        vals = list(vals)
        if not vals:
            return self._push("false", "true", [])
        ph = ", ".join(["%s"] * len(vals))
        return self._push(f"{c} IN ({ph})", f"{c} NOT IN ({ph})", vals)

    def order(self, col: str, desc: bool = False):
        self._order_col = f"{_check_ident(col)} {'DESC' if desc else 'ASC'}"
        return self

    def limit(self, n: int):
        self._limit_val = int(n)
        return self

    # terminal -----------------------------------------------------------
    def _where_clause(self) -> tuple[str, list]:
        if not self._where:
            return "", []
        frags, params = [], []
        for frag, p in self._where:
            frags.append(frag)
            params.extend(p)
        return " WHERE " + " AND ".join(frags), params

    def execute(self) -> "_Result":
        if self._op == "select":
            where, params = self._where_clause()
            sql = f"SELECT {self._cols} FROM {self._table}{where}"
            if self._order_col:
                sql += f" ORDER BY {self._order_col}"
            if self._limit_val is not None:
                sql += f" LIMIT {self._limit_val}"
            rows = pgpool.fetchall(sql, params)
            return _Result(rows)

        if self._op in ("insert", "upsert"):
            rows = self._payload if isinstance(self._payload, list) else [self._payload]
            out = []
            for row in rows:
                sql, params = _build_insert(
                    self._table, row,
                    on_conflict=self._on_conflict if self._op == "upsert" else None,
                    returning="*",
                )
                r = pgpool.fetchone(sql, params)
                if r is not None:
                    out.append(r)
            return _Result(out)

        if self._op == "update":
            sets = ", ".join(f"{_check_ident(c)} = %s" for c in self._payload.keys())
            set_params = [_coerce(v) for v in self._payload.values()]
            where, where_params = self._where_clause()
            pgpool.execute(
                f"UPDATE {self._table} SET {sets}{where}", set_params + where_params
            )
            return _Result([])

        if self._op == "delete":
            where, params = self._where_clause()
            pgpool.execute(f"DELETE FROM {self._table}{where}", params)
            return _Result([])

        raise ValueError(f"unsupported op {self._op!r}")  # pragma: no cover


class _PgRestClient:
    def table(self, name: str) -> _Query:
        return _Query(name)


_pgrest_client = _PgRestClient()


def get_client() -> _PgRestClient:
    """Back-compat: a PostgREST-style builder backed by the psycopg3 pool."""
    return _pgrest_client
