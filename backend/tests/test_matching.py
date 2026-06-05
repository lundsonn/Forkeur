"""
Tests for restaurant matching logic in db.py.

Mock-path reference (all under client.table.return_value.select.return_value):
  Step 1  (exact eq)   : .eq.return_value.limit.return_value.execute   ← shared with _found select
  Step 2/3/4 (ilike+limit): .ilike.return_value.limit.return_value.execute
  Step 5  (candidates) : .ilike.return_value.execute                   ← no .limit()
"""

import pytest
from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from db import _is_junk, _canonical, _normalize_for_match, infer_cuisine


# ---------------------------------------------------------------------------
# Pure function tests (no DB)
# ---------------------------------------------------------------------------

class TestIsJunk:
    def test_around_n(self):              assert _is_junk("Around 3")
    def test_pre_order_hyphen(self):      assert _is_junk("Pre-order 1")
    def test_precommande_accent(self):    assert _is_junk("Pré-commande 2")
    def test_article_offert(self):        assert _is_junk("Article offert")
    def test_pct_off(self):               assert _is_junk("30% off")
    def test_minus_pct(self):             assert _is_junk("- 50 %")
    def test_bullet_a_partir(self):       assert _is_junk("• à partir de 20€")
    def test_normal_restaurant(self):     assert not _is_junk("Burger King")
    def test_empty_string(self):          assert not _is_junk("")
    def test_sushi_place(self):           assert not _is_junk("Sushi World")


class TestCanonical:
    def test_strips_location_suffix(self):
        assert _canonical("Burger King - Ixelles") == "Burger King"

    def test_strips_emoji_and_suffix(self):
        assert _canonical("🩷 Crousty Factory 🧡 - Bruxelles") == "Crousty Factory"

    def test_no_suffix_unchanged(self):
        assert _canonical("Gomu") == "Gomu"

    def test_emdash_not_stripped(self):
        # Em-dash separates distinct branches — must NOT be treated as location suffix
        result = _canonical("Pizza – Bar (Ixelles)")
        assert "Bar" in result  # suffix after em-dash preserved

    def test_strips_outer_whitespace(self):
        assert _canonical("  Sushi World  ") == "Sushi World"

    def test_multiple_word_suffix_stripped(self):
        assert _canonical("Le Pain Quotidien - Place Flagey") == "Le Pain Quotidien"


class TestNormalizeForMatch:
    def test_lowercases(self):
        assert _normalize_for_match("BURGER KING") == "burger king"

    def test_strips_accents(self):
        assert _normalize_for_match("Café") == "cafe"

    def test_smart_quote_same_as_straight(self):
        # U+2019 RIGHT SINGLE QUOTATION MARK must round-trip to same form as U+0027
        assert _normalize_for_match("L’Atelier") == _normalize_for_match("L'Atelier")

    def test_smart_quote_normalized_form(self):
        assert _normalize_for_match("L’Atelier") == "l'atelier"

    def test_backtick_to_straight(self):
        assert _normalize_for_match("L`Atelier") == "l'atelier"

    def test_collapses_whitespace(self):
        assert _normalize_for_match("Pizza  Place") == "pizza place"

    def test_emoji_stripped(self):
        result = _normalize_for_match("🩷 Sushi")
        assert result == "sushi"

    def test_accent_roundtrip(self):
        # "Café au Lait" and "Cafe au Lait" normalize to the same string
        assert _normalize_for_match("Café au Lait") == _normalize_for_match("Cafe au Lait")


class TestInferCuisine:
    def test_burger(self):        assert infer_cuisine("Burger Palace") == "Burgers"
    def test_pizza(self):         assert infer_cuisine("Pizza Napoli") == "Pizza"
    def test_sushi(self):         assert infer_cuisine("Sushi World") == "Asian"
    def test_kfc(self):           assert infer_cuisine("KFC Brussels") == "Chicken"
    def test_kebab(self):         assert infer_cuisine("Doner Palace") == "Kebab"
    def test_no_match(self):      assert infer_cuisine("Random Place") is None
    def test_case_insensitive(self): assert infer_cuisine("PIZZA HUT") == "Pizza"


# ---------------------------------------------------------------------------
# upsert_restaurant — mocked Supabase client
# ---------------------------------------------------------------------------

def _mock_exec(data):
    """Return a MagicMock whose .execute() returns MagicMock(data=data)."""
    m = MagicMock()
    m.execute.return_value = MagicMock(data=data)
    return m


def _make_client(
    *,
    eq_results=None,         # side_effect list for step-1 eq chain (also _found select)
    ilike_limit_results=None,# side_effect list for steps 2/3/4
    ilike_results=None,      # return_value for step-5 candidates (no limit)
    upsert_id="new-rid",
):
    """
    Build a MagicMock Supabase client wired for upsert_restaurant call chains.

    eq_results:
        List of {data: [...]} values returned in sequence by
        .select().eq().limit().execute() — consumed by step 1 then _found's
        cuisine/image select.  Defaults to [[], {"cuisine": None, "image_url": None}].

    ilike_limit_results:
        List of {data: [...]} values returned in sequence by
        .select().ilike().limit().execute() — consumed by steps 2, 3, 4 in order.
        Defaults to [[], [], []] (all miss).

    ilike_results:
        data value for .select().ilike().execute() (step-5 candidates, no limit).
        Defaults to [] (no candidates).
    """
    if eq_results is None:
        eq_results = [[], {"cuisine": None, "image_url": None}]
    if ilike_limit_results is None:
        ilike_limit_results = [[], [], []]
    if ilike_results is None:
        ilike_results = []

    client = MagicMock()
    sel = client.table.return_value.select.return_value

    # Step 1 / _found select  (.eq().limit().execute())
    sel.eq.return_value.limit.return_value.execute.side_effect = [
        MagicMock(data=d if isinstance(d, list) else [d]) if isinstance(d, (list, dict))
        else MagicMock(data=d)
        for d in eq_results
    ]

    # Steps 2/3/4  (.ilike().limit().execute())
    sel.ilike.return_value.limit.return_value.execute.side_effect = [
        MagicMock(data=d) for d in ilike_limit_results
    ]

    # Step 5  (.ilike().execute() — no .limit())
    sel.ilike.return_value.execute.return_value = MagicMock(data=ilike_results)

    # Insert path
    client.table.return_value.upsert.return_value.execute.return_value = MagicMock(
        data=[{"id": upsert_id}]
    )

    return client


@patch("db.get_client")
def test_junk_name_raises(mock_get):
    mock_get.return_value = MagicMock()
    import db
    with pytest.raises(ValueError, match="Junk entry skipped"):
        db.upsert_restaurant({"name": "Around 3", "slug": "around-3"})


@patch("db.get_client")
def test_step1_exact_match_returns_existing_id(mock_get):
    """Same scraper re-running: exact name already in DB."""
    client = _make_client(
        eq_results=[
            [{"id": "rid-existing"}],           # step 1: exact hit
            {"cuisine": None, "image_url": None}, # _found: nothing to update
        ],
    )
    mock_get.return_value = client
    import db
    result = db.upsert_restaurant({"name": "Burger King", "slug": "burger-king"})
    assert result == "rid-existing"
    client.table.return_value.upsert.assert_not_called()


@patch("db.get_client")
def test_step2_ilike_match_different_case(mock_get):
    """'GOMU' in data matches existing 'Gomu' via case-insensitive ilike."""
    client = _make_client(
        eq_results=[
            [],                                   # step 1: miss
            {"cuisine": None, "image_url": None}, # _found: nothing to update
        ],
        ilike_limit_results=[
            [{"id": "rid-gomu"}],  # step 2: ilike exact hit
        ],
    )
    mock_get.return_value = client
    import db
    result = db.upsert_restaurant({"name": "GOMU", "slug": "gomu"})
    assert result == "rid-gomu"
    client.table.return_value.upsert.assert_not_called()


@patch("db.get_client")
def test_step3_canonical_matches_base_name(mock_get):
    """'Burger King - Ixelles' finds existing 'Burger King' via canonical strip."""
    client = _make_client(
        eq_results=[
            [],                                   # step 1: miss
            {"cuisine": None, "image_url": None}, # _found
        ],
        ilike_limit_results=[
            [],                    # step 2: exact ilike miss
            [{"id": "rid-bk"}],   # step 3: canonical hit ("Burger King")
        ],
    )
    mock_get.return_value = client
    import db
    result = db.upsert_restaurant({"name": "Burger King - Ixelles", "slug": "burger-king-ixelles"})
    assert result == "rid-bk"
    client.table.return_value.upsert.assert_not_called()


@patch("db.get_client")
def test_step4_suffixed_variant_matches(mock_get):
    """'Burger King' finds existing 'Burger King - Ixelles' via suffix wildcard."""
    # canonical == name for "Burger King", so step 3 is skipped
    client = _make_client(
        eq_results=[
            [],                                   # step 1: miss
            {"cuisine": None, "image_url": None}, # _found
        ],
        ilike_limit_results=[
            [],                          # step 2: exact ilike miss
            [{"id": "rid-bk-suffix"}],  # step 4: "Burger King -%" hit (step 3 skipped)
        ],
    )
    mock_get.return_value = client
    import db
    result = db.upsert_restaurant({"name": "Burger King", "slug": "burger-king"})
    assert result == "rid-bk-suffix"
    client.table.return_value.upsert.assert_not_called()


@patch("db.get_client")
def test_step5_normalized_accent_match(mock_get):
    """'Cafe de Paris' (no accent) matches existing 'Café de Paris' via normalization."""
    client = _make_client(
        eq_results=[
            [],                                   # step 1: miss
            {"cuisine": None, "image_url": None}, # _found
        ],
        ilike_limit_results=[[], []],             # steps 2/4: miss
        ilike_results=[
            {"id": "rid-cafe", "name": "Café de Paris"},  # step 5: candidate
        ],
    )
    mock_get.return_value = client
    import db
    result = db.upsert_restaurant({"name": "Cafe de Paris", "slug": "cafe-de-paris"})
    assert result == "rid-cafe"
    client.table.return_value.upsert.assert_not_called()


@patch("db.get_client")
def test_step5_smart_quote_match(mock_get):
    """Incoming name with U+2019 smart quote matches DB row stored with U+0027."""
    # Stored name uses straight apostrophe (U+0027)
    stored_name = "L’Atelier"
    # Incoming scrape uses curly right-single-quote (U+2019)
    incoming_name = "L’Atelier"
    client = _make_client(
        eq_results=[
            [],
            {"cuisine": None, "image_url": None},
        ],
        # _canonical strips U+2019 → "LAtelier" ≠ incoming "L’Atelier",
        # so step 3 fires: slots needed for steps 2, 3, 4
        ilike_limit_results=[[], [], []],
        ilike_results=[{"id": "rid-atelier", "name": stored_name}],
    )
    mock_get.return_value = client
    import db
    result = db.upsert_restaurant({"name": incoming_name, "slug": "l-atelier"})
    assert result == "rid-atelier"


@patch("db.get_client")
def test_no_match_inserts_new_row(mock_get):
    """All 5 steps miss → upsert called, new id returned."""
    client = _make_client(upsert_id="brand-new")
    mock_get.return_value = client
    import db
    result = db.upsert_restaurant({"name": "Brand New Place", "slug": "brand-new-place"})
    assert result == "brand-new"
    client.table.return_value.upsert.assert_called_once()


@patch("db.get_client")
def test_cuisine_inferred_when_absent(mock_get):
    """cuisine is auto-inferred from name when not supplied."""
    client = _make_client(upsert_id="new-pizza")
    mock_get.return_value = client
    import db
    db.upsert_restaurant({"name": "Pizza Nova", "slug": "pizza-nova"})
    upsert_args = client.table.return_value.upsert.call_args[0][0]
    assert upsert_args["cuisine"] == "Pizza"


@patch("db.get_client")
def test_explicit_cuisine_not_overridden(mock_get):
    """Caller-supplied cuisine is preserved even when name would infer differently."""
    client = _make_client(upsert_id="new")
    mock_get.return_value = client
    import db
    db.upsert_restaurant({"name": "Pizza Nova", "slug": "pizza-nova", "cuisine": "Italian"})
    upsert_args = client.table.return_value.upsert.call_args[0][0]
    assert upsert_args["cuisine"] == "Italian"


@patch("db.get_client")
def test_found_enriches_cuisine(mock_get):
    """_found pushes inferred cuisine onto an existing row that has none."""
    client = _make_client(
        eq_results=[
            [{"id": "rid-123"}],
            {"cuisine": None, "image_url": None},  # existing: no cuisine
        ],
    )
    mock_get.return_value = client
    import db
    db.upsert_restaurant({"name": "Burger Palace", "slug": "burger-palace"})
    update_payload = client.table.return_value.update.call_args[0][0]
    assert update_payload.get("cuisine") == "Burgers"


@patch("db.get_client")
def test_found_does_not_overwrite_existing_cuisine(mock_get):
    """_found leaves cuisine alone when the existing row already has one."""
    client = _make_client(
        eq_results=[
            [{"id": "rid-123"}],
            {"cuisine": "Belgian", "image_url": None},  # already set
        ],
    )
    mock_get.return_value = client
    import db
    db.upsert_restaurant({"name": "Burger Palace", "slug": "burger-palace"})
    # update should not be called with cuisine (or not called at all if only cuisine changed)
    calls = client.table.return_value.update.call_args_list
    for c in calls:
        assert "cuisine" not in c[0][0]


@patch("db.get_client")
def test_found_always_updates_coords(mock_get):
    """lat/lng are always pushed to the existing row (coords can shift)."""
    client = _make_client(
        eq_results=[
            [{"id": "rid-123"}],
            {"cuisine": "Burgers", "image_url": None},
        ],
    )
    mock_get.return_value = client
    import db
    db.upsert_restaurant({"name": "Burger King", "slug": "bk", "lat": 50.85, "lng": 4.35})
    update_payload = client.table.return_value.update.call_args[0][0]
    assert update_payload["lat"] == 50.85
    assert update_payload["lng"] == 4.35
