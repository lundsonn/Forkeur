"""Quick re-test of Deliveroo scroll fix. uv run python test_deliveroo.py"""
import asyncio
import uuid
import db as _db_module

_db_module.upsert_restaurant = lambda d: str(uuid.uuid4())
_db_module.upsert_listing = lambda d: str(uuid.uuid4())
_db_module.upsert_promotions = lambda lid, p: 0
_db_module.insert_menu_items = lambda lid, items: 0
_db_module.patch_listing = lambda lid, d: None

from models import ScraperConfig
from scrapers import deliveroo


async def main():
    config = ScraperConfig(listing_only=True)
    result = await deliveroo.run(config, log_fn=lambda l: print(f"[deliveroo] {l}", flush=True))
    print(f"\n>>> deliveroo: {result.records_saved} listings")


asyncio.run(main())
