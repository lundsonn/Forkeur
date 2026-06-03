"""
Verify all scrapers load complete restaurant listings (not just first page).
Stubs DB calls — no writes. Phase 1 only (listing_only=True).
Usage: uv run python test_pagination.py
"""
import asyncio
import uuid
import db as _db_module

# ── Stub all DB writes before scrapers import db ─────────────────────────────
_counts: dict[str, int] = {"restaurants": 0, "listings": 0}


def _fake_upsert_restaurant(data: dict) -> str:
    _counts["restaurants"] += 1
    return str(uuid.uuid4())


def _fake_upsert_listing(data: dict) -> str:
    _counts["listings"] += 1
    return str(uuid.uuid4())


def _fake_upsert_promotions(listing_id: str, promotions: list) -> int:
    return 0


def _fake_insert_menu_items(listing_id: str, items: list) -> int:
    return 0


def _fake_patch_listing(listing_id: str, data: dict) -> None:
    pass


_db_module.upsert_restaurant = _fake_upsert_restaurant
_db_module.upsert_listing = _fake_upsert_listing
_db_module.upsert_promotions = _fake_upsert_promotions
_db_module.insert_menu_items = _fake_insert_menu_items
_db_module.patch_listing = _fake_patch_listing

# ── Now import scrapers (they will use the patched db module) ─────────────────
from models import ScraperConfig, ScraperResult  # noqa: E402
from scrapers import ubereats, deliveroo, takeaway  # noqa: E402


def make_log(platform: str):
    def log(line: str):
        print(f"[{platform}] {line}", flush=True)
    return log


async def test_scraper(name: str, module, config: ScraperConfig) -> ScraperResult:
    print(f"\n{'='*60}", flush=True)
    print(f"SCRAPER: {name}", flush=True)
    print(f"{'='*60}", flush=True)
    _counts["restaurants"] = 0
    _counts["listings"] = 0
    result = await module.run(config, log_fn=make_log(name))
    return result


async def main():
    config = ScraperConfig(listing_only=True)
    results: dict[str, int] = {}

    r = await test_scraper("ubereats", ubereats, config)
    results["ubereats"] = r.records_saved

    r = await test_scraper("deliveroo", deliveroo, config)
    results["deliveroo"] = r.records_saved

    r = await test_scraper("takeaway", takeaway, config)
    results["takeaway"] = r.records_saved

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for platform, count in results.items():
        status = "OK" if count > 50 else "LOW — pagination may be broken"
        print(f"  {platform:12s}: {count:4d} listings  [{status}]")
    print()


if __name__ == "__main__":
    asyncio.run(main())
