#!/usr/bin/env python3
"""Enrich restaurants.neighborhood with Brussels commune names from lat/lng.

Usage:
    uv run backend/scripts/enrich_neighborhoods.py          # dry-run
    uv run backend/scripts/enrich_neighborhoods.py --commit # write to DB
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.db import get_client

POSTAL_TO_COMMUNE: dict[str, str] = {
    "1000": "Bruxelles-Ville",
    "1020": "Laeken",
    "1030": "Schaerbeek",
    "1040": "Etterbeek",
    "1050": "Ixelles",
    "1060": "Saint-Gilles",
    "1070": "Anderlecht",
    "1080": "Molenbeek",
    "1081": "Koekelberg",
    "1082": "Berchem-Sainte-Agathe",
    "1083": "Ganshoren",
    "1090": "Jette",
    "1120": "Neder-Over-Heembeek",
    "1130": "Haren",
    "1140": "Evere",
    "1150": "Woluwe-Saint-Pierre",
    "1160": "Auderghem",
    "1170": "Watermael-Boitsfort",
    "1180": "Uccle",
    "1190": "Forest",
    "1200": "Woluwe-Saint-Lambert",
    "1210": "Saint-Josse-ten-Noode",
}

VALID_COMMUNES = set(POSTAL_TO_COMMUNE.values())

HEADERS = {"User-Agent": "Forkeur/1.0 (food price comparison Brussels; geraud.marion@gmail.com)"}


def reverse_geocode(lat: float, lng: float) -> str | None:
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lng}&format=json"
    for attempt in range(4):
        try:
            r = httpx.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 429:
                wait = 5 * (2 ** attempt)
                print(f"  429 — sleeping {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            addr = r.json().get("address", {})
            postcode = addr.get("postcode", "").strip()[:4]
            if postcode in POSTAL_TO_COMMUNE:
                return POSTAL_TO_COMMUNE[postcode]
            return addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality")
        except httpx.HTTPStatusError:
            return None
        except Exception as e:
            print(f"  ERROR geocoding ({lat}, {lng}): {e}")
            return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true", help="Write changes to DB")
    args = parser.parse_args()

    dry_run = not args.commit
    if dry_run:
        print("DRY-RUN mode — pass --commit to write to DB\n")

    db = get_client()

    rows = (
        db.table("restaurants")
        .select("id, name, lat, lng, neighborhood")
        .not_.is_("lat", "null")
        .not_.is_("lng", "null")
        .execute()
        .data
    )

    total = len(rows)
    updated = skipped = errors = 0

    for i, row in enumerate(rows, 1):
        current = row.get("neighborhood") or ""
        # Skip if already a valid commune name
        if current in VALID_COMMUNES:
            skipped += 1
            continue

        name = row["name"]
        lat, lng = row["lat"], row["lng"]

        commune = reverse_geocode(lat, lng)
        time.sleep(2)  # Nominatim rate limit: be conservative

        if not commune:
            print(f"[{i}/{total}] {name!r} → no result, skipping")
            errors += 1
            continue

        print(f"[{i}/{total}] {name!r} → {commune}")

        if not dry_run:
            db.table("restaurants").update({"neighborhood": commune}).eq("id", row["id"]).execute()
        updated += 1

    print(f"\nDone. updated={updated} skipped={skipped} errors={errors} total={total}")
    if dry_run and updated:
        print("Re-run with --commit to apply.")


if __name__ == "__main__":
    main()
