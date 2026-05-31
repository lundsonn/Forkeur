#!/usr/bin/env python3
"""Run all three scrapers and dump result.restaurants to forkeur-app/data/*.json.

The scrapers also write directly to Supabase (their normal behaviour).
The JSON files are consumed by seed-supabase.js for cross-platform matching.

Usage (from backend/):
    uv run python run_scrapers_to_json.py
    uv run python run_scrapers_to_json.py --platform ubereats
    uv run python run_scrapers_to_json.py --menus          # include menu scraping
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from models import ScraperConfig
from scrapers import deliveroo, takeaway, ubereats

OUT_DIR = Path(__file__).parent.parent / "forkeur-app" / "data"

SCRAPERS = {
    "ubereats":  ubereats.run,
    "deliveroo": deliveroo.run,
    "takeaway":  takeaway.run,
}


def log(platform: str, msg: str) -> None:
    print(f"  [{platform}] {msg}", flush=True)


async def run_one(platform: str, config: ScraperConfig) -> list[dict]:
    print(f"\n── {platform} {'─' * (60 - len(platform))}\n")
    try:
        result = await SCRAPERS[platform](config, log_fn=lambda m: log(platform, m))
        return result.restaurants
    except Exception as exc:
        print(f"\n❌ {platform} failed: {exc}", file=sys.stderr)
        return []


async def main(platforms: list[str], scrape_menus: bool) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    config = ScraperConfig(
        scrape_menus=scrape_menus,
        max_menus=999,
    )

    for platform in platforms:
        restaurants = await run_one(platform, config)
        if not restaurants:
            print(f"  ⚠  No data returned for {platform} — skipping JSON write")
            continue

        out_path = OUT_DIR / f"{platform}.json"
        out_path.write_text(
            json.dumps(restaurants, indent=2, ensure_ascii=False, default=str)
        )
        print(f"\n✅ {platform}: {len(restaurants)} restaurants → {out_path}")

    print("\nDone. Now run:\n  cd forkeur-app && node scripts/seed-supabase.js\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--platform",
        choices=list(SCRAPERS),
        help="Run only this platform (default: all)",
    )
    parser.add_argument(
        "--menus",
        action="store_true",
        help="Include menu scraping (slower)",
    )
    args = parser.parse_args()

    targets = [args.platform] if args.platform else list(SCRAPERS)
    asyncio.run(main(targets, scrape_menus=args.menus))
