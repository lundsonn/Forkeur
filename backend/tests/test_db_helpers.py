import db
import pgpool


def test_build_insert_simple():
    sql, params = db._build_insert("restaurants", {"name": "X", "slug": "x"})
    assert sql == 'INSERT INTO restaurants (name, slug) VALUES (%s, %s) RETURNING id'
    assert params == ["X", "x"]


def test_build_insert_on_conflict():
    sql, params = db._build_insert(
        "restaurants", {"name": "X", "slug": "x"}, on_conflict="slug"
    )
    assert "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name" in sql
    assert params == ["X", "x"]


def test_build_update():
    sql, params = db._build_update("restaurants", {"cuisine": "Pizza"}, "id", "abc")
    assert sql == 'UPDATE restaurants SET cuisine = %s WHERE id = %s'
    assert params == ["Pizza", "abc"]


def test_build_insert_composite_conflict_excludes_both():
    sql, params = db._build_insert(
        "platform_listings",
        {"restaurant_id": "r", "platform": "uber_eats", "url": "u"},
        on_conflict="restaurant_id,platform",
    )
    assert "ON CONFLICT (restaurant_id,platform) DO UPDATE SET url = EXCLUDED.url" in sql
    assert "restaurant_id = EXCLUDED" not in sql
    assert "platform = EXCLUDED" not in sql


# --- A1: NULL-preserve upsert ---------------------------------------------

def test_build_insert_preserve_emits_coalesce():
    sql, _ = db._build_insert(
        "platform_listings",
        {"restaurant_id": "r", "platform": "uber_eats", "delivery_fee": 2.5},
        on_conflict="restaurant_id,platform",
        preserve_if_null={"delivery_fee"},
    )
    assert (
        "delivery_fee = COALESCE(EXCLUDED.delivery_fee, platform_listings.delivery_fee)"
        in sql
    )


def test_build_insert_non_preserved_uses_excluded():
    sql, _ = db._build_insert(
        "platform_listings",
        {"restaurant_id": "r", "platform": "uber_eats", "is_available": True},
        on_conflict="restaurant_id,platform",
        preserve_if_null={"delivery_fee"},
    )
    assert "is_available = EXCLUDED.is_available" in sql
    assert "COALESCE" not in sql


def test_build_insert_default_no_preserve():
    sql, _ = db._build_insert(
        "platform_listings",
        {"restaurant_id": "r", "platform": "uber_eats", "delivery_fee": 2.5,
         "is_available": True},
        on_conflict="restaurant_id,platform",
    )
    assert "delivery_fee = EXCLUDED.delivery_fee" in sql
    assert "is_available = EXCLUDED.is_available" in sql
    assert "COALESCE" not in sql


def test_preserve_on_null_constant_membership():
    # Fee/quality cols preserve; hard-update cols do not.
    assert "delivery_fee" in db._PRESERVE_ON_NULL
    assert "rating" in db._PRESERVE_ON_NULL
    for hard in ("is_available", "discount_label", "url", "opening_hours",
                 "url_type", "street_address", "postal_code"):
        assert hard not in db._PRESERVE_ON_NULL


# --- E1/E2: upsert_listing freshness bump + fee snapshot (mock pgpool) -----

def _spy_pgpool(monkeypatch, *, fetchone_id="lid-1"):
    """Patch pgpool primitives, recording all execute() SQL+params."""
    calls = {"execute": [], "fetchone": []}

    def fake_fetchone(sql, params=None):
        calls["fetchone"].append((sql, params))
        return {"id": fetchone_id}

    def fake_execute(sql, params=None):
        calls["execute"].append((sql, params))
        return 1

    monkeypatch.setattr(pgpool, "fetchone", fake_fetchone)
    monkeypatch.setattr(pgpool, "execute", fake_execute)
    return calls


def test_upsert_listing_uses_preserve_set(monkeypatch):
    calls = _spy_pgpool(monkeypatch)
    db.upsert_listing({
        "restaurant_id": "r", "platform": "uber_eats", "url": "u",
        "delivery_fee": 2.5,
    })
    upsert_sql = calls["fetchone"][0][0]
    assert (
        "delivery_fee = COALESCE(EXCLUDED.delivery_fee, platform_listings.delivery_fee)"
        in upsert_sql
    )


def test_upsert_listing_bumps_last_scraped_at(monkeypatch):
    calls = _spy_pgpool(monkeypatch)
    lid = db.upsert_listing({
        "restaurant_id": "r", "platform": "uber_eats", "url": "u",
    })
    assert lid == "lid-1"
    bump = [c for c in calls["execute"]
            if "last_scraped_at = now()" in c[0] and "WHERE id" in c[0]]
    assert bump, "expected a last_scraped_at bump on the listing id"
    assert bump[0][1] == ["lid-1"]


def test_upsert_listing_writes_fee_snapshot_when_fee_present(monkeypatch):
    calls = _spy_pgpool(monkeypatch)
    db.upsert_listing({
        "restaurant_id": "r", "platform": "uber_eats", "url": "u",
        "delivery_fee": 1.99, "eta_min": 15,
    })
    snaps = [c for c in calls["execute"] if "fee_snapshots" in c[0]]
    assert snaps, "expected a fee_snapshots insert when fee data present"


def test_upsert_listing_skips_fee_snapshot_when_no_fee(monkeypatch):
    calls = _spy_pgpool(monkeypatch)
    db.upsert_listing({
        "restaurant_id": "r", "platform": "uber_eats", "url": "u",
        "is_available": True,
    })
    snaps = [c for c in calls["execute"] if "fee_snapshots" in c[0]]
    assert not snaps, "no fee keys → no snapshot insert"


def test_upsert_listing_survives_fee_snapshot_failure(monkeypatch):
    # Missing fee_snapshots table (pre-migration) must not break the upsert.
    calls = {"fetchone": []}

    def fake_fetchone(sql, params=None):
        calls["fetchone"].append(sql)
        return {"id": "lid-9"}

    def fake_execute(sql, params=None):
        if "fee_snapshots" in sql:
            raise RuntimeError('relation "fee_snapshots" does not exist')
        return 1

    monkeypatch.setattr(pgpool, "fetchone", fake_fetchone)
    monkeypatch.setattr(pgpool, "execute", fake_execute)
    lid = db.upsert_listing({
        "restaurant_id": "r", "platform": "uber_eats", "url": "u",
        "delivery_fee": 2.0,
    })
    assert lid == "lid-9"


def test_insert_fee_snapshot_only_present_keys(monkeypatch):
    captured = {}

    def fake_execute(sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return 1

    monkeypatch.setattr(pgpool, "execute", fake_execute)
    db.insert_fee_snapshot("lid-1", {"delivery_fee": 3.0, "min_order": 12.0})
    assert "fee_snapshots" in captured["sql"]
    assert "delivery_fee" in captured["sql"]
    assert "min_order" in captured["sql"]
    assert "eta_min" not in captured["sql"]
    assert captured["params"][0] == "lid-1"


# --- E2: cleanup predicates use COALESCE(last_scraped_at, scraped_at) ------

def test_delete_stale_listings_coalesces_scraped_at(monkeypatch):
    captured = {}

    def fake_execute(sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return 0

    monkeypatch.setattr(pgpool, "execute", fake_execute)
    db.delete_stale_listings(30)
    assert "COALESCE(last_scraped_at, scraped_at)" in captured["sql"]
    assert captured["params"] == [30]


def test_prune_stale_menu_items_coalesces_scraped_at(monkeypatch):
    captured = {}

    def fake_fetchall(sql, params=None):
        captured["sql"] = sql
        return []

    monkeypatch.setattr(pgpool, "fetchall", fake_fetchall)
    db.prune_stale_menu_items(30)
    assert "COALESCE(last_scraped_at, scraped_at)" in captured["sql"]


# --- A2: deals query gates on freshness ------------------------------------

def test_get_public_deals_filters_stale(monkeypatch):
    captured = {}

    def fake_fetchall(sql, params=None):
        captured["sql"] = sql
        return []

    monkeypatch.setattr(pgpool, "fetchall", fake_fetchall)
    db.get_public_deals()
    assert "pl.last_scraped_at" in captured["sql"]
    assert "72 hours" in captured["sql"]
