import pytest
from unittest.mock import patch


def test_insert_claim_returns_id():
    with patch("pgpool.fetchone", return_value={"id": "claim-abc"}):
        import db
        result = db.insert_claim(
            restaurant_id="rest-1",
            owner_email="owner@example.com",
            direct_order_url="https://myrest.com/order",
        )
    assert result == "claim-abc"


def test_insert_claim_uses_correct_table():
    with patch("pgpool.fetchone", return_value={"id": "claim-xyz"}) as mock_fo:
        import db
        db.insert_claim(owner_email="a@b.com")
    sql = mock_fo.call_args[0][0]
    assert "restaurant_claims" in sql
    assert "RETURNING id" in sql


def test_get_claims_pending_only():
    rows = [
        {"id": "c1", "restaurant_id": "r1", "owner_email": "a@b.com",
         "direct_order_url": "https://x.com", "verified": False,
         "claimed_at": "2026-06-03T10:00:00Z"},
    ]
    with patch("pgpool.fetchall", return_value=rows):
        import db
        result = db.get_claims(verified=False)
    assert len(result) == 1
    assert result[0]["id"] == "c1"


def test_get_claims_pending_filters_verified():
    with patch("pgpool.fetchall", return_value=[]) as mock_fa:
        import db
        db.get_claims(verified=False)
    sql, params = mock_fa.call_args[0]
    assert "WHERE c.verified = %s" in sql
    assert False in params


def test_get_claims_all_when_none():
    with patch("pgpool.fetchall", return_value=[]) as mock_fa:
        import db
        db.get_claims(verified=None)
    sql = mock_fa.call_args[0][0]
    assert "WHERE" not in sql


def test_approve_claim_updates_restaurant_and_listing():
    claim = {
        "id": "c1", "restaurant_id": "rest-1",
        "direct_order_url": "https://myrest.com/order",
        "inquiry_type": "add_url",
    }
    executed_sqls = []

    def fake_execute(sql, params=None):
        executed_sqls.append(sql)
        return 1

    with patch("pgpool.fetchone", return_value=claim), \
         patch("pgpool.execute", side_effect=fake_execute), \
         patch("db.upsert_listing") as mock_upsert, \
         patch("db._validate_order_url"):
        import db
        db.approve_claim("c1")

    # restaurants.order_url updated
    assert any("UPDATE restaurants" in s for s in executed_sqls)
    # claim marked verified
    assert any("UPDATE restaurant_claims" in s and "verified = true" in s
               for s in executed_sqls)
    # direct listing upserted
    mock_upsert.assert_called_once_with({
        "restaurant_id": "rest-1",
        "platform": "direct",
        "url": "https://myrest.com/order",
        "is_available": True,
    })


def test_reject_claim_deletes_row():
    with patch("pgpool.execute") as mock_exec:
        import db
        db.reject_claim("c1")
    mock_exec.assert_called_once()
    sql, params = mock_exec.call_args[0]
    assert "DELETE FROM restaurant_claims" in sql
    assert "c1" in params


def test_approve_claim_raises_when_not_found():
    with patch("pgpool.fetchone", return_value=None):
        import db
        with pytest.raises(ValueError, match="Claim not found"):
            db.approve_claim("nonexistent-id")


def test_approve_claim_skips_url_update_for_other_type():
    """inquiry_type != add_url: only marks verified, no restaurant update."""
    claim = {
        "id": "c2", "restaurant_id": "rest-2",
        "direct_order_url": "https://myrest.com/order",
        "inquiry_type": "general_inquiry",
    }
    executed_sqls = []

    def fake_execute(sql, params=None):
        executed_sqls.append(sql)
        return 1

    with patch("pgpool.fetchone", return_value=claim), \
         patch("pgpool.execute", side_effect=fake_execute), \
         patch("db.upsert_listing") as mock_upsert:
        import db
        db.approve_claim("c2")

    assert not any("UPDATE restaurants" in s for s in executed_sqls)
    mock_upsert.assert_not_called()
    assert any("UPDATE restaurant_claims" in s for s in executed_sqls)
