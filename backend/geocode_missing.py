"""One-shot script: geocode restaurants with missing lat/lng via Nominatim (OpenStreetMap).

Usage:
    uv run python geocode_missing.py

Rate limit: 1.1s between requests (Nominatim ToS: max 1 req/s).
"""

import os
import time

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "forkeur-geocoder/1.0 (geraud.marion@gmail.com)"}
RATE_LIMIT_S = 1.1


def fetch_missing(client) -> list[dict]:
    """Fetch all restaurants where lat or lng is NULL."""
    res = (
        client.table("restaurants")
        .select("id, name")
        .is_("lat", "null")
        .execute()
    )
    return res.data


def geocode(name: str) -> tuple[float, float] | None:
    """Query Nominatim for '{name} Brussels Belgium'. Returns (lat, lng) or None."""
    params = {
        "q": f"{name} Brussels Belgium",
        "format": "json",
        "limit": 1,
    }
    try:
        resp = httpx.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=10.0)
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except httpx.HTTPError as exc:
        print(f"  HTTP error: {exc}")
    except (KeyError, ValueError, IndexError) as exc:
        print(f"  Parse error: {exc}")
    return None


def update_coords(client, restaurant_id: str, lat: float, lng: float) -> None:
    client.table("restaurants").update({"lat": lat, "lng": lng}).eq("id", restaurant_id).execute()


def main() -> None:
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    restaurants = fetch_missing(client)
    total = len(restaurants)
    print(f"Found {total} restaurants without coordinates.\n")

    if total == 0:
        print("Nothing to do.")
        return

    geocoded = 0

    for i, row in enumerate(restaurants, start=1):
        rid = row["id"]
        name = row["name"]

        coords = geocode(name)

        if coords:
            lat, lng = coords
            update_coords(client, rid, lat, lng)
            print(f"[{i}/{total}] {name} → {lat:.6f}, {lng:.6f}")
            geocoded += 1
        else:
            print(f"[{i}/{total}] {name} → not found")

        if i < total:
            time.sleep(RATE_LIMIT_S)

    print(f"\nGeocoded {geocoded}/{total} restaurants.")


if __name__ == "__main__":
    main()
