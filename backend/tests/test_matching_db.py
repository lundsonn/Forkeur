from unittest.mock import MagicMock, patch
import json

# Fixed valid UUIDs used by tests below — db.enqueue_decision /
# db.merge_restaurants now reject non-UUID input as a defence against
# filter injection.
_S = "11111111-1111-1111-1111-111111111111"
_L = "22222222-2222-2222-2222-222222222222"


def test_load_restaurants_for_match_selects_fields():
    rows = [{"id": "1", "name": "Foo", "website": None, "phone": None,
             "lat": None, "lng": None, "geo_source": None, "cuisine": None,
             "created_at": "2026-01-01T00:00:00Z", "is_chain": False}]
    with patch("pgpool.fetchall", return_value=rows) as mock_fetchall:
        import db
        out = db.load_restaurants_for_match()
    assert out == rows
    call_sql = mock_fetchall.call_args[0][0]
    assert "merged_into IS NULL" in call_sql
    assert "restaurants" in call_sql


def test_enqueue_decision_inserts_row():
    # No existing pair → INSERT path
    with patch("pgpool.fetchone") as mock_fetchone, \
         patch("pgpool.execute") as mock_execute:
        # First call: existence check → None (no existing pair)
        # Second call: INSERT RETURNING id → new row
        mock_fetchone.side_effect = [None, {"id": "d1"}]
        import db
        db.invalidate_domain_cache()
        out = db.enqueue_decision(
            survivor_id=_S, loser_id=_L, score=0.95,
            features={"name_sim": 0.95}, status="queued",
        )
    assert out == "d1"
    # execute should NOT have been called (no UPDATE needed)
    mock_execute.assert_not_called()
    # Two fetchone calls: existence check + INSERT RETURNING
    assert mock_fetchone.call_count == 2
    insert_sql = mock_fetchone.call_args_list[1][0][0]
    assert "INSERT INTO restaurant_match_decisions" in insert_sql


def test_enqueue_decision_updates_existing_pair():
    # Existing pair found → UPDATE path, no INSERT
    with patch("pgpool.fetchone") as mock_fetchone, \
         patch("pgpool.execute") as mock_execute:
        mock_fetchone.side_effect = [{"id": "existing1"}]
        import db
        db.invalidate_domain_cache()
        out = db.enqueue_decision(
            survivor_id=_S, loser_id=_L, score=0.99,
            features={"name_sim": 0.99}, status="queued",
        )
    assert out == "existing1"
    # UPDATE was called, not INSERT
    mock_execute.assert_called_once()
    update_sql = mock_execute.call_args[0][0]
    assert "UPDATE restaurant_match_decisions" in update_sql
    # fetchone called only once (existence check) — no INSERT RETURNING
    assert mock_fetchone.call_count == 1


def test_merge_restaurants_calls_atomic_rpc():
    """merge_restaurants delegates to merge_restaurants_atomic via pgpool.execute."""
    import db
    with patch("pgpool.execute") as mock_exec:
        db.merge_restaurants(_S, _L)
    mock_exec.assert_called_once()
    sql, params = mock_exec.call_args[0]
    assert "merge_restaurants_atomic" in sql
    assert _S in params
    assert _L in params


def test_merge_restaurants_noop_when_same_id():
    """merge_restaurants does nothing when survivor == loser."""
    import db
    with patch("pgpool.execute") as mock_exec:
        db.merge_restaurants(_S, _S)
    mock_exec.assert_not_called()


def test_delete_decisions_uses_any():
    import db
    d1 = "33333333-3333-3333-3333-333333333333"
    d2 = "44444444-4444-4444-4444-444444444444"
    with patch("pgpool.execute") as mock_exec:
        db.delete_decisions([d1, d2])
    mock_exec.assert_called_once()
    sql, params = mock_exec.call_args[0]
    assert "ANY(%s)" in sql
    assert d1 in params[0]
    assert d2 in params[0]


def test_delete_decisions_noop_on_empty():
    import db
    with patch("pgpool.execute") as mock_exec:
        db.delete_decisions([])
    mock_exec.assert_not_called()


def test_get_queued_decisions_filters_status():
    rows = [{"id": "d1", "status": "queued", "survivor_id": _S, "loser_id": _L}]
    with patch("pgpool.fetchall") as mock_fetchall:
        # First call: decisions query; second call: listings enrichment
        mock_fetchall.side_effect = [rows, []]
        import db
        out = db.get_queued_decisions()
    assert len(out) == 1
    assert out[0]["id"] == "d1"
    decisions_sql = mock_fetchall.call_args_list[0][0][0]
    assert "status = 'queued'" in decisions_sql


def test_get_queued_decisions_enriches_listings():
    rows = [{"id": "d1", "status": "queued", "survivor_id": _S, "loser_id": _L}]
    listing = {"restaurant_id": _S, "platform": "uber_eats", "url": "https://ubereats.com/x"}
    with patch("pgpool.fetchall") as mock_fetchall:
        mock_fetchall.side_effect = [rows, [listing]]
        import db
        out = db.get_queued_decisions()
    assert out[0]["survivor_listings"] == [{"platform": "uber_eats", "url": "https://ubereats.com/x"}]
    assert out[0]["loser_listings"] == []


def test_resolve_decision_approve_merges():
    with patch("pgpool.fetchone") as mock_fetchone, \
         patch("pgpool.execute") as mock_execute, \
         patch("db.merge_restaurants") as merge:
        mock_fetchone.return_value = {
            "id": "d1", "survivor_id": _S, "loser_id": _L, "status": "queued"
        }
        import db
        db.resolve_decision("d1", approve=True, resolved_by="admin")
    merge.assert_called_once_with(_S, _L)
    mock_execute.assert_called_once()
    update_sql = mock_execute.call_args[0][0]
    assert "approved" in mock_execute.call_args[0][1]


def test_resolve_decision_reject_no_merge():
    with patch("pgpool.fetchone") as mock_fetchone, \
         patch("pgpool.execute") as mock_execute, \
         patch("db.merge_restaurants") as merge:
        mock_fetchone.return_value = {
            "id": "d1", "survivor_id": _S, "loser_id": _L, "status": "queued"
        }
        import db
        db.resolve_decision("d1", approve=False, resolved_by="admin")
    merge.assert_not_called()
    mock_execute.assert_called_once()
    assert "rejected" in mock_execute.call_args[0][1]


def test_resolve_decision_noop_when_not_found():
    with patch("pgpool.fetchone", return_value=None), \
         patch("pgpool.execute") as mock_execute, \
         patch("db.merge_restaurants") as merge:
        import db
        db.resolve_decision("nonexistent", approve=True, resolved_by="admin")
    merge.assert_not_called()
    mock_execute.assert_not_called()


# --- Pre-existing pgpool-based upsert tests (kept from prior task) ---

def test_upsert_restaurant_website_domain_lock():
    """A new name with a known website domain attaches to the existing row."""
    import db
    fetchone_results = iter([None, None, {"cuisine": None, "image_url": None,
                                          "lat": None, "lng": None, "geo_source": None,
                                          "phone": None, "neighborhood": None}])
    fetchall_results = iter([[{"id": "R1", "website": "https://foo.be"}]])

    with patch("pgpool.fetchone", side_effect=fetchone_results), \
         patch("pgpool.fetchall", side_effect=fetchall_results), \
         patch("pgpool.execute") as mock_exec:
        db.invalidate_domain_cache()
        rid = db.upsert_restaurant({"name": "Totally Different", "website": "http://www.foo.be/x"})
    assert rid == "R1"
    mock_exec.assert_not_called()


def test_upsert_restaurant_stamps_geo_source():
    """geo_source is persisted when provided on insert."""
    import db
    captured_sql = {}

    fetchone_results = iter([None, None, None, {"id": "NEW"}])
    fetchall_results = iter([[], []])  # website rows, prefix scan

    def fake_fetchone(sql, params=None):
        result = next(fetchone_results)
        if result and result.get("id") == "NEW":
            captured_sql["insert_params"] = params
        return result

    with patch("pgpool.fetchone", side_effect=fake_fetchone), \
         patch("pgpool.fetchall", side_effect=fetchall_results), \
         patch("pgpool.execute"):
        db.invalidate_domain_cache()
        rid = db.upsert_restaurant({"name": "Brand New", "slug": "brand-new",
                                    "lat": 50.8, "lng": 4.3, "geo_source": "uber_eats"})
    assert rid == "NEW"
    params = captured_sql.get("insert_params", [])
    assert "uber_eats" in params


def test_upsert_found_deliveroo_does_not_clobber_venue_geo():
    """A deliveroo re-scrape must not overwrite venue-grade coords/source."""
    import db
    step1_row = {"id": "R1", "cuisine": "Pizza", "image_url": "x",
                 "lat": 50.1, "lng": 4.1, "geo_source": "uber_eats"}

    fetchone_results = iter([step1_row])
    captured_updates = {}

    def fake_execute(sql, params=None):
        if sql.strip().upper().startswith("UPDATE"):
            captured_updates["sql"] = sql
            captured_updates["params"] = params
        return 1

    with patch("pgpool.fetchone", side_effect=fetchone_results), \
         patch("pgpool.fetchall") as mock_fetchall, \
         patch("pgpool.execute", side_effect=fake_execute):
        db.upsert_restaurant({"name": "Pizza Roma", "lat": 50.9, "lng": 4.9,
                              "geo_source": "deliveroo"})

    params = captured_updates.get("params", [])
    assert 50.9 not in params
    assert "deliveroo" not in params


def test_upsert_found_venue_grade_upgrades_geo():
    """An uber_eats re-scrape upgrades coords + stamps geo_source."""
    import db
    step1_row = {"id": "R1", "cuisine": "Pizza", "image_url": "x",
                 "lat": 50.1, "lng": 4.1, "geo_source": "deliveroo"}

    fetchone_results = iter([step1_row])
    captured_updates = {}

    def fake_execute(sql, params=None):
        if sql.strip().upper().startswith("UPDATE"):
            captured_updates["params"] = params
        return 1

    with patch("pgpool.fetchone", side_effect=fetchone_results), \
         patch("pgpool.fetchall") as mock_fetchall, \
         patch("pgpool.execute", side_effect=fake_execute):
        db.upsert_restaurant({"name": "Pizza Roma", "lat": 50.9, "lng": 4.9,
                              "geo_source": "uber_eats"})

    params = captured_updates.get("params", [])
    assert 50.9 in params
    assert "uber_eats" in params
