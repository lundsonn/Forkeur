import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)

@pytest.fixture()
def seeded(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    import pgpool, db
    pgpool.close_pool()
    pgpool.execute("TRUNCATE restaurants, platform_listings, menu_items, promotions, scraper_runs RESTART IDENTITY CASCADE")
    rid = db.upsert_restaurant({"name": "Test Diner", "slug": "test-diner", "cuisine": "Burgers"})
    lid = db.upsert_listing({"restaurant_id": rid, "platform": "uber_eats", "url": "https://x", "delivery_fee": 2.5, "eta_min": 20, "is_available": True})
    db.insert_menu_items(lid, [{"title": "Cheeseburger", "price": 9.0}])
    return rid

def test_public_restaurants_shape(seeded):
    import db
    rows = db.get_public_restaurants()
    assert len(rows) == 1
    r = rows[0]
    assert r["name"] == "Test Diner"
    assert isinstance(r["platform_listings"], list)
    assert r["platform_listings"][0]["platform"] == "uber_eats"

def test_public_detail_shape(seeded):
    import db
    detail = db.get_public_restaurant_detail(seeded)
    assert detail["name"] == "Test Diner"
    listing = detail["platform_listings"][0]
    assert listing["menu_items"][0]["title"] == "Cheeseburger"

def test_public_detail_missing_returns_none(seeded):
    import db
    assert db.get_public_restaurant_detail("00000000-0000-0000-0000-000000000000") is None
