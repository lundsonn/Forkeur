import os
import re
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


def _canonical(name: str) -> str:
    """Strip platform-specific location suffixes for cross-platform matching.
    'Burger King - Ixelles' → 'Burger King', 'McDonald's' → 'McDonald's'
    """
    return re.sub(r"\s+-\s+\S.*$", "", name).strip()


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

    Deliveroo appends location (' - Ixelles') that UberEats omits.
    We normalise both sides so the same chain maps to one row.
    """
    client = get_client()
    name: str = data["name"]
    canonical = _canonical(name)

    # Infer cuisine from name if not provided
    if not data.get("cuisine"):
        data = {**data, "cuisine": infer_cuisine(name)}

    def _found(rid: str) -> str:
        # Backfill cuisine if existing row has none
        if data.get("cuisine"):
            existing = client.table("restaurants").select("cuisine").eq("id", rid).limit(1).execute()
            if existing.data and not existing.data[0].get("cuisine"):
                client.table("restaurants").update({"cuisine": data["cuisine"]}).eq("id", rid).execute()
            # Also update lat/lng if provided
            updates = {k: data[k] for k in ("lat", "lng") if data.get(k) is not None}
            if updates:
                client.table("restaurants").update(updates).eq("id", rid).execute()
        return rid

    # 1. Exact name match (same scraper re-running)
    res = client.table("restaurants").select("id").eq("name", name).limit(1).execute()
    if res.data:
        return _found(res.data[0]["id"])

    # 2. We have a location suffix; check if canonical base name already exists
    #    e.g. inserting "Burger King - Ixelles", canonical = "Burger King" already stored
    if canonical != name:
        res = client.table("restaurants").select("id").eq("name", canonical).limit(1).execute()
        if res.data:
            return _found(res.data[0]["id"])

    # 3. We are the base name; check if a location-suffixed variant is already stored
    #    e.g. inserting "Burger King", Deliveroo already stored "Burger King - Ixelles"
    res = (
        client.table("restaurants")
        .select("id")
        .ilike("name", f"{canonical} -%")
        .limit(1)
        .execute()
    )
    if res.data:
        return _found(res.data[0]["id"])

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
