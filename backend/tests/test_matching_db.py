from unittest.mock import MagicMock, patch

# Fixed valid UUIDs used by tests below — db.enqueue_decision /
# db.merge_restaurants now reject non-UUID input as a defence against
# PostgREST filter-injection.
_S = "11111111-1111-1111-1111-111111111111"
_L = "22222222-2222-2222-2222-222222222222"


def test_load_restaurants_for_match_selects_fields():
    rows = [{"id": "1", "name": "Foo", "website": None, "phone": None,
             "lat": None, "lng": None, "geo_source": None, "cuisine": None,
             "created_at": "2026-01-01T00:00:00Z"}]
    with patch("db.get_client") as mock_get:
        client = MagicMock()
        # paginated: .select().is_().order().range().execute(); a short page ends the loop
        client.table.return_value.select.return_value.is_.return_value.order.return_value.range.return_value.execute.return_value.data = rows
        mock_get.return_value = client
        import db
        out = db.load_restaurants_for_match()
    assert out == rows
    client.table.assert_called_with("restaurants")


def test_enqueue_decision_inserts_row():
    with patch("db.get_client") as mock_get:
        client = MagicMock()
        client.table.return_value.select.return_value.or_.return_value.limit.return_value.execute.return_value.data = []
        client.table.return_value.insert.return_value.execute.return_value.data = [{"id": "d1"}]
        mock_get.return_value = client
        import db
        out = db.enqueue_decision(
            survivor_id=_S, loser_id=_L, score=0.95,
            features={"name_sim": 0.95}, status="queued",
        )
    assert out == "d1"


def test_enqueue_decision_updates_existing_pair():
    with patch("db.get_client") as mock_get:
        client = MagicMock()
        client.table.return_value.select.return_value.or_.return_value.limit.return_value.execute.return_value.data = [{"id": "existing1"}]
        client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []
        mock_get.return_value = client
        import db
        out = db.enqueue_decision(
            survivor_id=_S, loser_id=_L, score=0.99,
            features={"name_sim": 0.99}, status="queued",
        )
    assert out == "existing1"
    client.table.return_value.insert.assert_not_called()


def test_merge_restaurants_calls_atomic_rpc():
    """merge_restaurants delegates to the merge_restaurants_atomic Postgres RPC.

    The previous Python-side multi-step implementation has been replaced with a
    single transactional SQL function (migration 017). The test now verifies
    that the helper hands off correctly with validated UUID arguments rather
    than re-exercising the now-server-side merge logic.
    """
    import db
    client = MagicMock()
    with patch("db.get_client", return_value=client):
        db.merge_restaurants(_S, _L)
    client.rpc.assert_called_once_with(
        "merge_restaurants_atomic",
        {"p_survivor": _S, "p_loser": _L},
    )


def test_upsert_restaurant_website_domain_lock():
    """A new name with a known website domain attaches to the existing row."""
    import db
    # pgpool call sequence for "Totally Different" with website="http://www.foo.be/x":
    # fetchone(exact name)  → None
    # fetchone(ilike name)  → None
    # fetchall(website rows) → [{"id": "R1", "website": "https://foo.be"}]
    # _found: fetchone(existing row by id) → {"cuisine": None, "image_url": None, ...}
    # no updates → execute not called
    fetchone_results = iter([None, None, {"cuisine": None, "image_url": None,
                                          "lat": None, "lng": None, "geo_source": None,
                                          "phone": None, "neighborhood": None}])
    fetchall_results = iter([[{"id": "R1", "website": "https://foo.be"}]])

    with patch("pgpool.fetchone", side_effect=fetchone_results), \
         patch("pgpool.fetchall", side_effect=fetchall_results), \
         patch("pgpool.execute") as mock_exec:
        rid = db.upsert_restaurant({"name": "Totally Different", "website": "http://www.foo.be/x"})
    assert rid == "R1"
    mock_exec.assert_not_called()


def test_upsert_restaurant_stamps_geo_source():
    """geo_source is persisted when provided on insert."""
    import db
    captured_sql = {}

    # pgpool call sequence for "Brand New" (no match anywhere → insert):
    # fetchone(exact name)   → None
    # fetchone(ilike name)   → None
    # fetchall(website rows) → []  (no websites in db)
    # fetchone(canonical ilike) → None  (canonical != name only if suffix stripped)
    # fetchone(suffix variant)  → None
    # fetchall(prefix scan)     → []
    # fetchone(INSERT … RETURNING id) → {"id": "NEW"}
    # "Brand New" → canonical = "Brand New", so step 3 is skipped (canonical == name)
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
        rid = db.upsert_restaurant({"name": "Brand New", "slug": "brand-new",
                                    "lat": 50.8, "lng": 4.3, "geo_source": "uber_eats"})
    assert rid == "NEW"
    # geo_source was in the inserted data (passed as params to INSERT)
    params = captured_sql.get("insert_params", [])
    assert "uber_eats" in params


def test_upsert_found_deliveroo_does_not_clobber_venue_geo():
    """A deliveroo re-scrape must not overwrite venue-grade coords/source."""
    import db
    existing_row = {"id": "R1", "cuisine": "Pizza", "image_url": "x",
                    "lat": 50.1, "lng": 4.1, "geo_source": "uber_eats",
                    "phone": None, "neighborhood": None}

    # Step 1 exact-name match hits → _found called with row from step 1.
    # Step 1 row lacks phone/neighborhood so _found does a fetchone for full row.
    # Actually step 1 returns _MATCH_COLS = "id, cuisine, image_url, lat, lng, geo_source"
    # which IS passed as row to _found — no extra fetchone needed.
    step1_row = {"id": "R1", "cuisine": "Pizza", "image_url": "x",
                 "lat": 50.1, "lng": 4.1, "geo_source": "uber_eats"}

    fetchone_results = iter([step1_row])
    captured_updates = {}

    def fake_execute(sql, params=None):
        # Capture UPDATE calls
        if sql.strip().upper().startswith("UPDATE"):
            captured_updates["sql"] = sql
            captured_updates["params"] = params
        return 1

    with patch("pgpool.fetchone", side_effect=fetchone_results), \
         patch("pgpool.fetchall") as mock_fetchall, \
         patch("pgpool.execute", side_effect=fake_execute):
        db.upsert_restaurant({"name": "Pizza Roma", "lat": 50.9, "lng": 4.9,
                              "geo_source": "deliveroo"})

    # No UPDATE should have included lat/geo_source — deliveroo can't clobber uber_eats
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


def test_get_queued_decisions_filters_status():
    rows = [{"id": "d1", "status": "queued"}]
    with patch("db.get_client") as mock_get:
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = rows
        mock_get.return_value = client
        import db
        out = db.get_queued_decisions()
    assert out == rows


def test_resolve_decision_approve_merges():
    with patch("db.get_client") as mock_get, patch("db.merge_restaurants") as merge:
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "d1", "survivor_id": "S", "loser_id": "L", "status": "queued"}
        ]
        client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []
        mock_get.return_value = client
        import db
        db.resolve_decision("d1", approve=True, resolved_by="admin")
    merge.assert_called_once_with("S", "L")


def test_resolve_decision_reject_no_merge():
    with patch("db.get_client") as mock_get, patch("db.merge_restaurants") as merge:
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "d1", "survivor_id": "S", "loser_id": "L", "status": "queued"}
        ]
        client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []
        mock_get.return_value = client
        import db
        db.resolve_decision("d1", approve=False, resolved_by="admin")
    merge.assert_not_called()
