"""
Tests for db.py functions not covered by test_db.py or test_matching.py.
Covers: upsert_listing, patch_listing, upsert_promotions, insert_menu_items,
        prune_stale_menu_items, orphan_stale_runs, get_run, get_last_successful_run,
        get_restaurants, get_listings_with_urls, _validate_order_url.
"""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# upsert_listing
# ---------------------------------------------------------------------------

@patch("db.get_client")
def test_upsert_listing_updates_when_exists(mock_get):
    client = MagicMock()
    client.table.return_value.select.return_value \
        .eq.return_value.eq.return_value.execute.return_value.data = [{"id": "lid-1"}]
    mock_get.return_value = client
    import db
    result = db.upsert_listing({"restaurant_id": "r1", "platform": "uber_eats", "url": "https://x.com"})
    assert result == "lid-1"
    client.table.return_value.update.assert_called_once()
    client.table.return_value.insert.assert_not_called()


@patch("db.get_client")
def test_upsert_listing_inserts_when_not_exists(mock_get):
    client = MagicMock()
    client.table.return_value.select.return_value \
        .eq.return_value.eq.return_value.execute.return_value.data = []
    client.table.return_value.insert.return_value.execute.return_value.data = [{"id": "lid-new"}]
    mock_get.return_value = client
    import db
    result = db.upsert_listing({"restaurant_id": "r1", "platform": "uber_eats"})
    assert result == "lid-new"
    client.table.return_value.update.assert_not_called()


# ---------------------------------------------------------------------------
# patch_listing
# ---------------------------------------------------------------------------

@patch("db.get_client")
def test_patch_listing_calls_update(mock_get):
    client = MagicMock()
    mock_get.return_value = client
    import db
    db.patch_listing("lid-1", {"delivery_fee": 2.99})
    client.table.return_value.update.assert_called_once_with({"delivery_fee": 2.99})


# ---------------------------------------------------------------------------
# upsert_promotions
# ---------------------------------------------------------------------------

@patch("db.get_client")
def test_upsert_promotions_deletes_then_inserts(mock_get):
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "p1"}, {"id": "p2"}
    ]
    mock_get.return_value = client
    import db
    count = db.upsert_promotions("lid-1", [{"type": "free_delivery"}, {"type": "pct_discount", "value": 10}])
    assert count == 2
    client.table.return_value.delete.return_value.eq.assert_called_with("listing_id", "lid-1")


@patch("db.get_client")
def test_upsert_promotions_empty_only_deletes(mock_get):
    client = MagicMock()
    mock_get.return_value = client
    import db
    count = db.upsert_promotions("lid-1", [])
    assert count == 0
    client.table.return_value.delete.assert_called_once()
    client.table.return_value.insert.assert_not_called()


@patch("db.get_client")
def test_upsert_promotions_injects_listing_id(mock_get):
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = [{"id": "p1"}]
    mock_get.return_value = client
    import db
    db.upsert_promotions("lid-42", [{"type": "free_delivery"}])
    inserted_rows = client.table.return_value.insert.call_args[0][0]
    assert inserted_rows[0]["listing_id"] == "lid-42"


# ---------------------------------------------------------------------------
# insert_menu_items
# ---------------------------------------------------------------------------

@patch("db.get_client")
def test_insert_menu_items_deletes_then_inserts(mock_get):
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "m1"}, {"id": "m2"}
    ]
    mock_get.return_value = client
    import db
    count = db.insert_menu_items("lid-1", [{"title": "Burger", "price": 12.0}, {"title": "Fries", "price": 3.5}])
    assert count == 2


@patch("db.get_client")
def test_insert_menu_items_bumps_last_scraped_at(mock_get):
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = []
    mock_get.return_value = client
    import db
    db.insert_menu_items("lid-1", [{"title": "Item", "price": 5.0}])
    update_payload = client.table.return_value.update.call_args[0][0]
    assert "last_scraped_at" in update_payload


@patch("db.get_client")
def test_insert_menu_items_empty_skips_insert_but_bumps_timestamp(mock_get):
    client = MagicMock()
    mock_get.return_value = client
    import db
    count = db.insert_menu_items("lid-1", [])
    assert count == 0
    # timestamp bumped even when no items
    client.table.return_value.update.assert_called_once()
    client.table.return_value.insert.assert_not_called()


@patch("db.get_client")
def test_insert_menu_items_injects_listing_id(mock_get):
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = [{"id": "m1"}]
    mock_get.return_value = client
    import db
    db.insert_menu_items("lid-99", [{"title": "Salad", "price": 8.0}])
    rows = client.table.return_value.insert.call_args[0][0]
    assert rows[0]["listing_id"] == "lid-99"


# ---------------------------------------------------------------------------
# prune_stale_menu_items
# ---------------------------------------------------------------------------

@patch("db.get_client")
def test_prune_stale_menu_items_deletes_stale(mock_get):
    client = MagicMock()
    # Two stale listings found
    client.table.return_value.select.return_value \
        .not_.is_.return_value.lt.return_value.execute.return_value.data = [
        {"id": "lid-1"}, {"id": "lid-2"}
    ]
    # Each delete returns 3 removed rows
    client.table.return_value.delete.return_value \
        .eq.return_value.execute.return_value.data = [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
    mock_get.return_value = client
    import db
    count = db.prune_stale_menu_items(days=30)
    assert count == 6  # 3 items × 2 listings


@patch("db.get_client")
def test_prune_stale_menu_items_no_stale_no_delete(mock_get):
    client = MagicMock()
    client.table.return_value.select.return_value \
        .not_.is_.return_value.lt.return_value.execute.return_value.data = []
    mock_get.return_value = client
    import db
    count = db.prune_stale_menu_items(days=30)
    assert count == 0
    client.table.return_value.delete.assert_not_called()


# ---------------------------------------------------------------------------
# orphan_stale_runs
# ---------------------------------------------------------------------------

@patch("db.get_client")
def test_orphan_stale_runs_marks_running_as_failed(mock_get):
    client = MagicMock()
    client.table.return_value.update.return_value \
        .eq.return_value.lt.return_value.execute.return_value.data = [
        {"id": "run-1"}, {"id": "run-2"}
    ]
    mock_get.return_value = client
    import db
    count = db.orphan_stale_runs(max_age_hours=2)
    assert count == 2
    payload = client.table.return_value.update.call_args[0][0]
    assert payload["status"] == "failed"
    assert "orphaned" in payload["error_msg"]


@patch("db.get_client")
def test_orphan_stale_runs_returns_zero_when_none(mock_get):
    client = MagicMock()
    client.table.return_value.update.return_value \
        .eq.return_value.lt.return_value.execute.return_value.data = []
    mock_get.return_value = client
    import db
    assert db.orphan_stale_runs() == 0


# ---------------------------------------------------------------------------
# get_run
# ---------------------------------------------------------------------------

@patch("db.get_client")
def test_get_run_returns_row(mock_get):
    client = MagicMock()
    client.table.return_value.select.return_value \
        .eq.return_value.execute.return_value.data = [{"id": "run-1", "status": "success"}]
    mock_get.return_value = client
    import db
    result = db.get_run("run-1")
    assert result["status"] == "success"


@patch("db.get_client")
def test_get_run_returns_none_when_missing(mock_get):
    client = MagicMock()
    client.table.return_value.select.return_value \
        .eq.return_value.execute.return_value.data = []
    mock_get.return_value = client
    import db
    assert db.get_run("nonexistent") is None


# ---------------------------------------------------------------------------
# get_last_successful_run
# ---------------------------------------------------------------------------

@patch("db.get_client")
def test_get_last_successful_run_returns_row(mock_get):
    client = MagicMock()
    client.table.return_value.select.return_value \
        .eq.return_value.eq.return_value.order.return_value.limit.return_value \
        .execute.return_value.data = [{"id": "run-5", "status": "success"}]
    mock_get.return_value = client
    import db
    result = db.get_last_successful_run("ubereats")
    assert result["id"] == "run-5"


@patch("db.get_client")
def test_get_last_successful_run_returns_none(mock_get):
    client = MagicMock()
    client.table.return_value.select.return_value \
        .eq.return_value.eq.return_value.order.return_value.limit.return_value \
        .execute.return_value.data = []
    mock_get.return_value = client
    import db
    assert db.get_last_successful_run("ubereats") is None


# ---------------------------------------------------------------------------
# get_restaurants
# ---------------------------------------------------------------------------

@patch("db.get_client")
def test_get_restaurants_no_search(mock_get):
    client = MagicMock()
    client.table.return_value.select.return_value \
        .range.return_value.execute.return_value.data = [{"id": "r1"}, {"id": "r2"}]
    mock_get.return_value = client
    import db
    result = db.get_restaurants()
    assert len(result) == 2


@patch("db.get_client")
def test_get_restaurants_with_search_uses_ilike(mock_get):
    client = MagicMock()
    client.table.return_value.select.return_value \
        .range.return_value.ilike.return_value.execute.return_value.data = [{"id": "r1"}]
    mock_get.return_value = client
    import db
    result = db.get_restaurants(search="pizza")
    assert len(result) == 1
    ilike_arg = client.table.return_value.select.return_value.range.return_value.ilike.call_args[0]
    assert "%pizza%" in ilike_arg


# ---------------------------------------------------------------------------
# get_listings_with_urls
# ---------------------------------------------------------------------------

@patch("db.get_client")
def test_get_listings_with_urls(mock_get):
    client = MagicMock()
    client.table.return_value.select.return_value \
        .eq.return_value.not_.is_.return_value.execute.return_value.data = [
        {"id": "lid-1", "url": "https://x.com"}
    ]
    mock_get.return_value = client
    import db
    result = db.get_listings_with_urls("uber_eats")
    assert result[0]["url"] == "https://x.com"


# ---------------------------------------------------------------------------
# _validate_order_url  (SSRF protection)
# ---------------------------------------------------------------------------

from db import _validate_order_url


def test_validate_accepts_normal_https():
    _validate_order_url("https://myrestaurant.be/order")  # no exception


def test_validate_accepts_http():
    _validate_order_url("http://myrestaurant.be/order")


def test_validate_rejects_localhost():
    with pytest.raises(ValueError):
        _validate_order_url("http://localhost:8080/order")


def test_validate_rejects_127():
    with pytest.raises(ValueError):
        _validate_order_url("http://127.0.0.1/order")


def test_validate_rejects_private_192():
    with pytest.raises(ValueError):
        _validate_order_url("http://192.168.1.1/order")


def test_validate_rejects_private_10():
    with pytest.raises(ValueError):
        _validate_order_url("http://10.0.0.1/order")


def test_validate_rejects_ftp_scheme():
    with pytest.raises(ValueError, match="http or https"):
        _validate_order_url("ftp://myrestaurant.be/order")


def test_validate_rejects_no_domain():
    with pytest.raises(ValueError, match="valid domain"):
        _validate_order_url("http://localhost/")


def test_validate_rejects_interactsh():
    with pytest.raises(ValueError):
        _validate_order_url("https://foo.interactsh.com/order")
