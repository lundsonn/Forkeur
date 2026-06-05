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


# ---------------------------------------------------------------------------
# matching.py — pure scoring core for cross-platform restaurant matching
# ---------------------------------------------------------------------------

import matching


def test_normalize_match_key_strips_punctuation_and_case():
    assert matching.normalize_match_key("Pizza minute") == matching.normalize_match_key("PizzaMinute")
    assert matching.normalize_match_key("Mr. Cod") == matching.normalize_match_key("Mr Cod")
    assert matching.normalize_match_key("Pizza & Go") == matching.normalize_match_key("Pizza&Go")


def test_normalize_match_key_strips_accents_and_suffix():
    assert matching.normalize_match_key("Bô-Zin") == matching.normalize_match_key("Bozin")
    assert matching.normalize_match_key("O'Tacos - Jette") == matching.normalize_match_key("O'Tacos")


def test_significant_first_token_skips_articles():
    assert matching.significant_first_token("Le Sommet de Damas") == "sommet"
    assert matching.significant_first_token("Burger King - Ixelles") == "burger"


def test_domain_of_registrable():
    assert matching.domain_of("https://www.bk.be/order?x=1") == "bk.be"
    assert matching.domain_of("http://sub.example.co.uk/menu") == "example.co.uk"
    assert matching.domain_of(None) is None
    assert matching.domain_of("not a url") is None


def test_phone_digits_normalizes_belgian():
    assert matching.phone_digits("+32 2 123 45 67") == matching.phone_digits("02 123 45 67")
    assert matching.phone_digits(None) is None
    assert matching.phone_digits("abc") is None


def test_haversine_known_distance():
    d = matching.haversine_m(50.8467, 4.3525, 50.8447, 4.3495)
    assert 300 < d < 460


def test_haversine_same_point_zero():
    assert matching.haversine_m(50.85, 4.35, 50.85, 4.35) == 0.0


def test_is_venue_grade():
    assert matching.is_venue_grade({"lat": 50.8, "lng": 4.3, "geo_source": "uber_eats"})
    assert matching.is_venue_grade({"lat": 50.8, "lng": 4.3, "geo_source": "direct"})
    assert not matching.is_venue_grade({"lat": 50.8, "lng": 4.3, "geo_source": "deliveroo"})
    assert not matching.is_venue_grade({"lat": 50.8, "lng": 4.3, "geo_source": None})
    assert not matching.is_venue_grade({"lat": None, "lng": None, "geo_source": "uber_eats"})


def _r(name, **kw):
    base = {"id": kw.get("id", name), "name": name, "website": None,
            "phone": None, "lat": None, "lng": None, "geo_source": None,
            "cuisine": None}
    base.update(kw)
    return base


def _f(**kw) -> matching.MatchFeatures:
    """Build a MatchFeatures with sensible defaults for all fields."""
    defaults = dict(
        name_sim=0.95,
        website_match=False,
        phone_match=False,
        geo_dist=None,
        cuisine_match=False,
        cuisine_conflict=False,
        location_conflict=False,
        menu_overlap=None,
        soft_geo_dist=None,
        is_chain_name=False,
    )
    defaults.update(kw)
    return matching.MatchFeatures(**defaults)


def test_score_pair_identical_normalized_name():
    f = matching.score_pair(_r("Pizza minute"), _r("PizzaMinute"))
    assert f.name_sim >= matching.HIGH_NAME_SIM
    assert f.website_match is False
    assert f.geo_dist is None


def test_score_pair_website_match():
    f = matching.score_pair(
        _r("Foo", website="https://www.foo.be/order"),
        _r("Foo Resto", website="http://foo.be/menu"),
    )
    assert f.website_match is True


def test_score_pair_geo_only_when_both_venue_grade():
    a = _r("Foo", lat=50.8467, lng=4.3525, geo_source="uber_eats")
    b = _r("Foo", lat=50.8447, lng=4.3495, geo_source="direct")
    f = matching.score_pair(a, b)
    assert f.geo_dist is not None and 300 < f.geo_dist < 460
    b2 = _r("Foo", lat=50.8447, lng=4.3495, geo_source="deliveroo")
    assert matching.score_pair(a, b2).geo_dist is None


def test_score_pair_phone_match():
    f = matching.score_pair(
        _r("Foo", phone="+32 2 123 45 67"),
        _r("Foo", phone="02 123 45 67"),
    )
    assert f.phone_match is True


def test_decide_website_plus_near_identical_name_auto_merges():
    f = _f(name_sim=0.98, website_match=True)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_decide_phone_signal_auto_merges():
    f = _f(name_sim=0.95, phone_match=True)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_decide_website_with_location_suffix_queues_not_merges():
    # shared chain domain + distinguishing location suffix (mid name_sim) → review
    f = _f(name_sim=0.93, website_match=True)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_close_geo_auto_merges():
    f = _f(name_sim=0.95, geo_dist=40.0)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_decide_name_only_auto_merges_at_threshold():
    # name_sim >= 0.97 with no conflicting signals → auto_merge (no data needed)
    f = _f(name_sim=0.97)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_decide_name_below_threshold_queues():
    f = _f(name_sim=0.95)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_geo_veto_separates_even_if_name_identical():
    f = _f(name_sim=1.0, geo_dist=900.0)
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_decide_low_name_separates():
    f = _f(name_sim=0.40)
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_decide_website_match_overrides_far_geo_is_still_veto():
    f = _f(name_sim=0.95, website_match=True, geo_dist=1200.0)
    assert matching.decide(f) == matching.Decision.SEPARATE


# ---------------------------------------------------------------------------
# Signal 1: Cuisine veto
# ---------------------------------------------------------------------------

def test_decide_cuisine_conflict_separates():
    f = _f(name_sim=0.97, cuisine_conflict=True)
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_decide_cuisine_conflict_after_geo_veto():
    # geo veto fires first even when cuisine_conflict=True
    f = _f(name_sim=0.97, geo_dist=900.0, cuisine_conflict=True)
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_decide_no_cuisine_conflict_auto_merges_at_threshold():
    f = _f(name_sim=0.97, cuisine_conflict=False)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_cuisine_conflict_both_set_different():
    assert matching._cuisine_conflict("Pizza", "Japanese") is True


def test_cuisine_conflict_both_set_same():
    assert matching._cuisine_conflict("Pizza", "Pizza") is False


def test_cuisine_conflict_one_none():
    assert matching._cuisine_conflict(None, "Pizza") is False
    assert matching._cuisine_conflict("Pizza", None) is False


def test_cuisine_conflict_substring():
    # "Asian" contains "sian" — not substring of each other; still different
    assert matching._cuisine_conflict("Asian", "Japanese") is True


def test_cuisine_no_conflict_substring_contained():
    # one is substring of the other → no conflict
    assert matching._cuisine_conflict("Asian", "Asian Fusion") is False


def test_score_pair_cuisine_conflict_detected():
    a = _r("Sushi World", cuisine="Japanese")
    b = _r("Sushi World", cuisine="Pizza")
    f = matching.score_pair(a, b)
    assert f.cuisine_conflict is True


def test_score_pair_same_cuisine_no_conflict():
    a = _r("Pizza Napoli", cuisine="Pizza")
    b = _r("Pizza Napoli", cuisine="Pizza")
    f = matching.score_pair(a, b)
    assert f.cuisine_conflict is False
    assert f.cuisine_match is True


# ---------------------------------------------------------------------------
# Signal 2: Location token veto
# ---------------------------------------------------------------------------

def test_location_tokens_ixelles():
    tokens = matching._location_tokens("Le Grill - Ixelles")
    assert "ixelles" in tokens


def test_location_tokens_etterbeek():
    tokens = matching._location_tokens("Sushi Palace Etterbeek")
    assert "etterbeek" in tokens


def test_location_tokens_empty_for_generic_name():
    tokens = matching._location_tokens("Burger King")
    assert tokens == set()


def test_location_tokens_slug_reinforces():
    tokens = matching._location_tokens("Sushi Palace", slugs=["sushi-palace-ixelles"])
    assert "ixelles" in tokens


def test_decide_location_conflict_separates():
    f = _f(name_sim=0.97, location_conflict=True)
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_score_pair_location_conflict_ixelles_vs_etterbeek():
    a = _r("Le Grill - Ixelles", id="a1")
    b = _r("Le Grill - Etterbeek", id="b1")
    f = matching.score_pair(a, b)
    assert f.location_conflict is True
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_score_pair_no_location_conflict_same_commune():
    a = _r("Le Grill - Ixelles", id="a1")
    b = _r("Le Grill Ixelles", id="b1")
    f = matching.score_pair(a, b)
    assert f.location_conflict is False


# ---------------------------------------------------------------------------
# Signal 3: Menu overlap
# ---------------------------------------------------------------------------

def test_decide_menu_overlap_veto_below_threshold():
    # name_sim fine, but almost zero menu overlap → SEPARATE
    f = _f(name_sim=0.97, menu_overlap=0.01)
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_decide_menu_overlap_confirm_auto_merges():
    # name_sim just at threshold, menu_overlap provides strong confirm
    f = _f(name_sim=0.92, menu_overlap=0.20)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_decide_menu_overlap_none_auto_merges_at_threshold():
    # None means no menu data — doesn't block auto_merge at name_sim >= 0.97
    f = _f(name_sim=0.97, menu_overlap=None)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_score_pair_menu_overlap_computed():
    a = _r("Foo", id="r1")
    b = _r("Foo", id="r2")
    menus = {
        "r1": {"margherita", "calzone", "tiramisu", "lasagna", "cannoli"},
        "r2": {"margherita", "calzone", "tiramisu", "carbonara", "risotto"},
    }
    f = matching.score_pair(a, b, menus=menus)
    # intersection={margherita,calzone,tiramisu}=3, union=7 → 3/7 ≈ 0.429
    assert f.menu_overlap is not None
    assert abs(f.menu_overlap - 3 / 7) < 0.001


def test_score_pair_menu_overlap_none_when_too_few_items():
    a = _r("Foo", id="r1")
    b = _r("Foo", id="r2")
    menus = {
        "r1": {"margherita", "calzone"},  # only 2 items — below threshold
        "r2": {"margherita", "calzone", "tiramisu"},
    }
    f = matching.score_pair(a, b, menus=menus)
    assert f.menu_overlap is None


def test_score_pair_menu_overlap_zero_disjoint():
    a = _r("Foo", id="r1")
    b = _r("Foo", id="r2")
    menus = {
        "r1": {"burger", "fries", "cola"},
        "r2": {"sushi", "miso", "edamame"},
    }
    f = matching.score_pair(a, b, menus=menus)
    assert f.menu_overlap == 0.0


# ---------------------------------------------------------------------------
# Signal 4: Soft geo veto
# ---------------------------------------------------------------------------

def test_decide_soft_geo_veto_above_threshold():
    f = _f(name_sim=0.97, soft_geo_dist=700.0)
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_decide_soft_geo_below_threshold_auto_merges():
    # soft_geo < 600m doesn't veto; name_sim >= 0.97 → auto_merge
    f = _f(name_sim=0.97, soft_geo_dist=400.0)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_score_pair_soft_geo_when_one_venue_grade():
    # a is venue-grade, b has coords but non-venue geo_source
    a = _r("Foo", id="a1", lat=50.8467, lng=4.3525, geo_source="uber_eats")
    b = _r("Foo", id="b1", lat=50.8447, lng=4.3495, geo_source="deliveroo")
    f = matching.score_pair(a, b)
    assert f.geo_dist is None         # not both venue-grade
    assert f.soft_geo_dist is not None
    assert 300 < f.soft_geo_dist < 460


def test_score_pair_no_soft_geo_when_both_venue_grade():
    # both venue-grade → geo_dist is used, soft_geo_dist stays None
    a = _r("Foo", id="a1", lat=50.8467, lng=4.3525, geo_source="uber_eats")
    b = _r("Foo", id="b1", lat=50.8447, lng=4.3495, geo_source="direct")
    f = matching.score_pair(a, b)
    assert f.geo_dist is not None
    assert f.soft_geo_dist is None


def test_score_pair_no_soft_geo_when_no_coords():
    a = _r("Foo", id="a1")
    b = _r("Foo", id="b1")
    f = matching.score_pair(a, b)
    assert f.soft_geo_dist is None


# ---------------------------------------------------------------------------
# Signal 5: Chain guard
# ---------------------------------------------------------------------------

def test_decide_chain_name_without_strong_confirm_separates():
    f = _f(name_sim=0.97, is_chain_name=True)
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_decide_chain_name_with_phone_confirm_auto_merges():
    f = _f(name_sim=0.97, is_chain_name=True, phone_match=True)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_decide_chain_name_with_close_geo_auto_merges():
    f = _f(name_sim=0.97, is_chain_name=True, geo_dist=40.0)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_decide_chain_name_with_menu_confirm_auto_merges():
    f = _f(name_sim=0.92, is_chain_name=True, menu_overlap=0.20)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_decide_non_chain_name_auto_merges_at_threshold():
    f = _f(name_sim=0.97, is_chain_name=False)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_score_pair_chain_name_detected():
    # chain_names uses significant_first_token: "Pizza Napoli" → "pizza"
    chain_names = {"pizza"}
    a = _r("Pizza Napoli", id="a1")
    b = _r("Pizza Napoli", id="b1")
    f = matching.score_pair(a, b, chain_names=chain_names)
    assert f.is_chain_name is True


def test_score_pair_non_chain_name_not_flagged():
    # "burgerking" is not the first token of "Pizza Napoli"
    chain_names = {"burgerking"}
    a = _r("Pizza Napoli", id="a1")
    b = _r("Pizza Napoli", id="b1")
    f = matching.score_pair(a, b, chain_names=chain_names)
    assert f.is_chain_name is False


# ---------------------------------------------------------------------------
# Signal 6: Slug location tokens
# ---------------------------------------------------------------------------

def test_location_tokens_from_slug_only():
    # name has no commune, but slug does
    tokens = matching._location_tokens("Sushi Palace", slugs=["sushi-palace-schaerbeek"])
    assert "schaerbeek" in tokens


def test_location_conflict_via_slug():
    # slugs encode different communes → conflict
    a = _r("Le Grill", id="a1")
    b = _r("Le Grill", id="b1")
    slugs = {"a1": ["le-grill-ixelles"], "b1": ["le-grill-etterbeek"]}
    f = matching.score_pair(a, b, slugs=slugs)
    assert f.location_conflict is True
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_no_conflict_when_slugs_share_commune():
    a = _r("Le Grill", id="a1")
    b = _r("Le Grill", id="b1")
    slugs = {"a1": ["le-grill-ixelles"], "b1": ["le-grill-ixelles-centre"]}
    f = matching.score_pair(a, b, slugs=slugs)
    assert f.location_conflict is False


# ---------------------------------------------------------------------------
# to_dict includes all new fields
# ---------------------------------------------------------------------------

def test_match_features_to_dict_has_all_fields():
    f = _f()
    d = f.to_dict()
    expected = {
        "name_sim", "website_match", "phone_match", "geo_dist",
        "cuisine_match", "cuisine_conflict", "location_conflict",
        "menu_overlap", "soft_geo_dist", "is_chain_name",
    }
    assert expected.issubset(d.keys())


def test_block_candidates_groups_by_first_token_and_domain():
    rows = [
        _r("Pizza Minute", id="1"),
        _r("PizzaMinute", id="2"),
        _r("Burger King - Ixelles", id="3"),
        _r("Sushi Shop", id="4", website="https://sushishop.be"),
        _r("Sushi Express", id="5", website="http://sushishop.be"),
    ]
    pairs = matching.block_candidates(rows)
    ids = {tuple(sorted((a["id"], b["id"]))) for a, b in pairs}
    assert ("1", "2") in ids
    assert ("4", "5") in ids
    assert ("1", "3") not in ids


def test_block_candidates_no_self_pairs():
    rows = [_r("Foo", id="1")]
    assert matching.block_candidates(rows) == []
