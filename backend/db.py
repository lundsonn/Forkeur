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
    c = _canonical(name).lower()
    # Remove accents via NFD decomposition
    c = unicodedata.normalize('NFD', c)
    c = ''.join(ch for ch in c if unicodedata.category(ch) != 'Mn')
    # Normalize all apostrophe/quote variants to straight single quote
    c = re.sub(r"[''`ʼ´]", "'", c)
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

    def _found(rid: str) -> str:
        if data.get("cuisine"):
            existing = client.table("restaurants").select("cuisine").eq("id", rid).limit(1).execute()
            if existing.data and not existing.data[0].get("cuisine"):
                client.table("restaurants").update({"cuisine": data["cuisine"]}).eq("id", rid).execute()
        updates = {k: data[k] for k in ("lat", "lng") if data.get(k) is not None}
        if updates:
            client.table("restaurants").update(updates).eq("id", rid).execute()
        return rid

    # 1. Exact name match (same scraper re-running)
    res = client.table("restaurants").select("id").eq("name", name).limit(1).execute()
    if res.data:
        return _found(res.data[0]["id"])

    # 2. Case-insensitive exact match ("GOMU" ↔ "Gomu", "Bombay Inn" ↔ "bombay inn")
    res = client.table("restaurants").select("id").ilike("name", name).limit(1).execute()
    if res.data:
        return _found(res.data[0]["id"])

    # 3. Canonical base match ("Burger King - Ixelles" → find "Burger King")
    if canonical != name:
        res = client.table("restaurants").select("id").ilike("name", canonical).limit(1).execute()
        if res.data:
            return _found(res.data[0]["id"])

    # 4. Suffixed variant match ("Burger King" → find "Burger King - Ixelles")
    res = (
        client.table("restaurants")
        .select("id")
        .ilike("name", f"{canonical} -%")
        .limit(1)
        .execute()
    )
    if res.data:
        return _found(res.data[0]["id"])

    # 5. Fully-normalized match: handles accents, smart quotes, emoji, trailing
    #    spaces. Fetch candidates by the first non-article word of canonical.
    _ARTICLES = {"le", "la", "les", "l'", "au", "aux", "un", "une", "de", "du", "the", "a"}
    words = canonical.split()
    sig_words = [w for w in words if w.lower().rstrip("'") not in _ARTICLES]
    prefix = sig_words[0] if sig_words else (words[0] if words else canonical[:5])
    if len(prefix) >= 3:
        candidates = (
            client.table("restaurants")
            .select("id, name")
            .ilike("name", f"{prefix}%")
            .execute()
        )
        for cand in candidates.data:
            cand_norm = _normalize_for_match(cand["name"])
            cand_norm_can = _normalize_for_match(_canonical(cand["name"]))
            if cand_norm in (norm, norm_canonical) or cand_norm_can in (norm, norm_canonical):
                return _found(cand["id"])

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


def insert_menu_items(listing_id: str, items: list[dict]) -> int:
    """Delete existing items for listing, insert new ones. Returns count."""
    client = get_client()
    client.table("menu_items").delete().eq("listing_id", listing_id).execute()
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
    for platform in ("ubereats", "deliveroo", "takeaway"):
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
