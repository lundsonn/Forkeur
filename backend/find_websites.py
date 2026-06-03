"""Standalone runner for the website-finder scraper.

Usage:
    uv run python find_websites.py           # process all restaurants
    uv run python find_websites.py --limit 3 # process only 3 (for testing)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from scrapers.website_finder import run


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find websites + ordering URLs for restaurants")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N restaurants (default: all)",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    result = await run(log=print, limit=args.limit)
    print(f"\nSummary: {result}")


if __name__ == "__main__":
    asyncio.run(_main())
