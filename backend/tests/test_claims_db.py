import pytest
from unittest.mock import MagicMock, patch


def _make_client(insert_data=None, select_data=None, update_data=None):
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = insert_data or []
    client.table.return_value.select.return_value.order.return_value.execute.return_value.data = select_data or []
    client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = update_data or []
    return client


def test_insert_claim_returns_id():
    with patch("db.get_client") as mock_get:
        mock_get.return_value = _make_client(insert_data=[{"id": "claim-abc"}])
        import db
        result = db.insert_claim(
            restaurant_id="rest-1",
            owner_email="owner@example.com",
            direct_order_url="https://myrest.com/order",
        )
    assert result == "claim-abc"


def test_get_claims_pending_only():
    rows = [
        {"id": "c1", "restaurant_id": "r1", "owner_email": "a@b.com",
         "direct_order_url": "https://x.com", "verified": False, "claimed_at": "2026-06-03T10:00:00Z"},
    ]
    with patch("db.get_client") as mock_get:
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = rows
        mock_get.return_value = client
        import db
        result = db.get_claims(verified=False)
    assert len(result) == 1
    assert result[0]["id"] == "c1"


def test_approve_claim_updates_restaurant_and_listing():
    claim = {
        "id": "c1", "restaurant_id": "rest-1",
        "direct_order_url": "https://myrest.com/order", "verified": False,
    }
    with patch("db.get_client") as mock_get, \
         patch("db.upsert_listing") as mock_upsert:
        client = MagicMock()
        # get_claim fetch
        client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [claim]
        mock_get.return_value = client
        import db
        db.approve_claim("c1")

        # restaurants.order_url updated
        client.table.return_value.update.assert_any_call({"order_url": "https://myrest.com/order"})
        # claim marked verified
        client.table.return_value.update.assert_any_call({"verified": True})
        # direct listing upserted
        mock_upsert.assert_called_once_with({
            "restaurant_id": "rest-1",
            "platform": "direct",
            "url": "https://myrest.com/order",
            "is_available": True,
        })


def test_reject_claim_deletes_row():
    with patch("db.get_client") as mock_get:
        client = MagicMock()
        mock_get.return_value = client
        import db
        db.reject_claim("c1")
        client.table.return_value.delete.return_value.eq.assert_called_once_with("id", "c1")


def test_approve_claim_raises_when_not_found():
    with patch("db.get_client") as mock_get:
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        mock_get.return_value = client
        import db
        with pytest.raises(ValueError, match="Claim not found"):
            db.approve_claim("nonexistent-id")
