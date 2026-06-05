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
    existing = [{"id": "R1", "website": "https://foo.be"}]
    client = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "restaurants":
            # Step 1 — exact name eq: no match
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
            # Step 2 — ilike name: no match
            t.select.return_value.ilike.return_value.limit.return_value.execute.return_value.data = []
            # Step 2b — domain lock: .select(...).not_.is_(...).execute()
            # .not_ is an attribute (not a call) in supabase-py
            t.select.return_value.not_.is_.return_value.execute.return_value.data = existing
            # _found: .select(...).eq(...).limit(1).execute()
            t.select.return_value.eq.return_value.execute.return_value.data = [{"cuisine": None, "image_url": None}]
            t.update.return_value.eq.return_value.execute.return_value.data = []
        return t

    client.table.side_effect = table
    with patch("db.get_client", return_value=client):
        rid = db.upsert_restaurant({"name": "Totally Different", "website": "http://www.foo.be/x"})
    assert rid == "R1"


def test_upsert_restaurant_stamps_geo_source():
    """geo_source is persisted when provided on insert."""
    import db
    captured = {}
    client = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "restaurants":
            # All name-matching steps return no match
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
            t.select.return_value.ilike.return_value.limit.return_value.execute.return_value.data = []
            # Domain lock: no existing rows with websites
            t.select.return_value.not_.is_.return_value.execute.return_value.data = []
            # Step 5 prefix scan: no candidates
            t.select.return_value.ilike.return_value.execute.return_value.data = []
            # Step 6 token scan: no candidates (ilike with limit)
            t.select.return_value.ilike.return_value.limit.return_value.execute.return_value.data = []

            def upsert(data, **k):
                captured.update(data)
                m = MagicMock()
                m.execute.return_value.data = [{"id": "NEW"}]
                return m
            t.upsert.side_effect = upsert
        return t

    client.table.side_effect = table
    with patch("db.get_client", return_value=client):
        rid = db.upsert_restaurant({"name": "Brand New", "slug": "brand-new",
                                    "lat": 50.8, "lng": 4.3, "geo_source": "uber_eats"})
    assert rid == "NEW"
    assert captured.get("geo_source") == "uber_eats"


def test_upsert_found_deliveroo_does_not_clobber_venue_geo():
    """A deliveroo re-scrape must not overwrite venue-grade coords/source."""
    import db
    existing_row = {"id": "R1", "cuisine": "Pizza", "image_url": "x",
                    "lat": 50.1, "lng": 4.1, "geo_source": "uber_eats"}
    captured = {}
    client = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "restaurants":
            def select(cols):
                s = MagicMock()
                if "geo_source" in cols:  # _found's existing-row fetch
                    s.eq.return_value.limit.return_value.execute.return_value.data = [existing_row]
                else:                      # step 1 select("id") exact-name match
                    s.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "R1"}]
                s.ilike.return_value.limit.return_value.execute.return_value.data = []
                return s
            t.select.side_effect = select
            def update(u):
                captured.update(u)
                m = MagicMock()
                m.eq.return_value.execute.return_value.data = []
                return m
            t.update.side_effect = update
        return t

    client.table.side_effect = table
    with patch("db.get_client", return_value=client):
        db.upsert_restaurant({"name": "Pizza Roma", "lat": 50.9, "lng": 4.9,
                              "geo_source": "deliveroo"})
    assert "lat" not in captured
    assert "geo_source" not in captured


def test_upsert_found_venue_grade_upgrades_geo():
    """An uber_eats re-scrape upgrades coords + stamps geo_source."""
    import db
    existing_row = {"id": "R1", "cuisine": "Pizza", "image_url": "x",
                    "lat": 50.1, "lng": 4.1, "geo_source": "deliveroo"}
    captured = {}
    client = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "restaurants":
            def select(cols):
                s = MagicMock()
                if "geo_source" in cols:
                    s.eq.return_value.limit.return_value.execute.return_value.data = [existing_row]
                else:
                    s.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "R1"}]
                s.ilike.return_value.limit.return_value.execute.return_value.data = []
                return s
            t.select.side_effect = select
            def update(u):
                captured.update(u)
                m = MagicMock()
                m.eq.return_value.execute.return_value.data = []
                return m
            t.update.side_effect = update
        return t

    client.table.side_effect = table
    with patch("db.get_client", return_value=client):
        db.upsert_restaurant({"name": "Pizza Roma", "lat": 50.9, "lng": 4.9,
                              "geo_source": "uber_eats"})
    assert captured.get("lat") == 50.9
    assert captured.get("geo_source") == "uber_eats"


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
