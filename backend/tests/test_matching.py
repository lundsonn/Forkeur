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
# upsert_restaurant — mocked pgpool (psycopg3) layer
#
# The DB layer was migrated off the Supabase PostgREST client onto direct
# pgpool (psycopg3) calls (self-hosted Postgres, 2026-06-11). upsert_restaurant
# now drives a 5-step escalation through pgpool.fetchone / pgpool.fetchall and
# writes updates via pgpool.execute. These tests mock pgpool and assert the
# *same matching behavior* the Supabase-era tests checked: exact → ilike →
# canonical → suffix → normalized escalation, insert-on-miss, cuisine inference
# and _found enrichment.
#
# Step → pgpool call mapping inside upsert_restaurant:
#   Step 1 (exact)     : fetchone "WHERE name = %s"
#   Step 2 (ilike)     : fetchone "name ILIKE %s", param == name
#   Step 3 (canonical) : fetchone "name ILIKE %s", param == canonical (only if canonical != name)
#   Step 4 (suffix)    : fetchone "name ILIKE %s", param endswith " -%"
#   Step 5 (candidates): fetchall "name ILIKE %s" (prefix wildcard)
#   Insert             : fetchone "INSERT INTO restaurants ..."  → {"id": ...}
#   _found update      : execute  "UPDATE restaurants SET ... WHERE id = %s"
# ---------------------------------------------------------------------------

class _FakePgpool:
    """SQL-dispatching fake for the pgpool module used by db.upsert_restaurant.

    Configure per-step hits; everything unset defaults to a miss. Captures
    every UPDATE so the _found-enrichment tests can inspect the payload.
    """
    def __init__(self, *, exact=None, ilike=None, canonical=None, suffix=None,
                 candidates=None, insert_id="new-rid"):
        self.exact = exact            # step 1 row (dict) or None
        self.ilike = ilike            # step 2 row or None
        self.canonical = canonical    # step 3 row or None
        self.suffix = suffix          # step 4 row or None
        self.candidates = candidates or []  # step 5 fetchall rows
        self.insert_id = insert_id
        self.updates: list[dict] = []  # captured UPDATE payloads (col → value)

    # --- pgpool API surface used by upsert_restaurant ---
    def fetchone(self, sql, params=None):
        params = params or []
        if "INSERT INTO" in sql:
            return {"id": self.insert_id}
        if "WHERE name = %s" in sql:
            return self.exact
        if "name ILIKE %s" in sql:
            arg = params[0] if params else ""
            if isinstance(arg, str) and arg.endswith(" -%"):
                return self.suffix
            # step 2 uses the raw name; step 3 uses the canonical form. They are
            # distinguished by which one upsert_restaurant passes; both land here
            # so we return step-2 hit first, then step-3 on the canonical arg.
            if self._is_canonical_arg(arg):
                return self.canonical
            return self.ilike
        return None

    def fetchall(self, sql, params=None):
        if "name ILIKE %s" in sql:
            return list(self.candidates)
        return []

    def execute(self, sql, params=None):
        # Reconstruct {col: value} from "UPDATE t SET a = %s, b = %s WHERE id = %s".
        params = list(params or [])
        if sql.startswith("UPDATE"):
            set_part = sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
            cols = [c.split(" = ")[0].strip() for c in set_part.split(", ")]
            payload = dict(zip(cols, params[: len(cols)]))
            self.updates.append(payload)

    def get_pool(self):  # not exercised by these tests
        raise AssertionError("get_pool should not be called in upsert tests")

    def _is_canonical_arg(self, arg):
        # Set by configure_canonical(); when canonical hit is configured we treat
        # the canonical-form arg as the step-3 query.
        return arg == self._canonical_arg if self._canonical_arg else False

    _canonical_arg = None


def _make_pgpool(**kw):
    """Build a _FakePgpool; ``canonical_arg`` marks which ILIKE arg is step 3."""
    canonical_arg = kw.pop("canonical_arg", None)
    p = _FakePgpool(**kw)
    p._canonical_arg = canonical_arg
    return p


@patch("db.invalidate_domain_cache", lambda: None)
@patch("db._domain_cache", None, create=True)
def test_junk_name_raises():
    import db
    with pytest.raises(ValueError, match="Junk entry skipped"):
        db.upsert_restaurant({"name": "Around 3", "slug": "around-3"})


def test_step1_exact_match_returns_existing_id():
    """Same scraper re-running: exact name already in DB."""
    p = _make_pgpool(exact={"id": "rid-existing", "cuisine": None, "image_url": None,
                            "lat": None, "lng": None, "geo_source": None})
    import db
    db.invalidate_domain_cache()
    with patch.object(db, "pgpool", p):
        result = db.upsert_restaurant({"name": "Burger King", "slug": "burger-king"})
    assert result == "rid-existing"


def test_step2_ilike_match_different_case():
    """'GOMU' in data matches existing 'Gomu' via case-insensitive ilike."""
    p = _make_pgpool(ilike={"id": "rid-gomu", "cuisine": None, "image_url": None,
                            "lat": None, "lng": None, "geo_source": None})
    import db
    db.invalidate_domain_cache()
    with patch.object(db, "pgpool", p):
        result = db.upsert_restaurant({"name": "GOMU", "slug": "gomu"})
    assert result == "rid-gomu"


def test_step3_canonical_matches_base_name():
    """'Burger King - Ixelles' finds existing 'Burger King' via canonical strip."""
    # canonical("Burger King - Ixelles") == "Burger King"
    p = _make_pgpool(
        ilike=None,  # step 2 (raw name) miss
        canonical={"id": "rid-bk", "cuisine": None, "image_url": None,
                   "lat": None, "lng": None, "geo_source": None},
        canonical_arg="Burger King",
    )
    import db
    db.invalidate_domain_cache()
    with patch.object(db, "pgpool", p):
        result = db.upsert_restaurant(
            {"name": "Burger King - Ixelles", "slug": "burger-king-ixelles"})
    assert result == "rid-bk"


def test_step4_suffixed_variant_matches():
    """'Burger King' finds existing 'Burger King - Ixelles' via suffix wildcard."""
    # canonical == name for "Burger King", so step 3 is skipped; step 4 ("Burger King -%") hits.
    p = _make_pgpool(
        ilike=None,  # step 2 exact-ilike miss
        suffix={"id": "rid-bk-suffix", "cuisine": None, "image_url": None,
                "lat": None, "lng": None, "geo_source": None},
    )
    import db
    db.invalidate_domain_cache()
    with patch.object(db, "pgpool", p):
        result = db.upsert_restaurant({"name": "Burger King", "slug": "burger-king"})
    assert result == "rid-bk-suffix"


def test_step5_normalized_accent_match():
    """'Cafe de Paris' (no accent) matches existing 'Café de Paris' via normalization."""
    p = _make_pgpool(
        candidates=[{"id": "rid-cafe", "name": "Café de Paris", "cuisine": None,
                     "image_url": None, "lat": None, "lng": None, "geo_source": None}],
    )
    import db
    db.invalidate_domain_cache()
    with patch.object(db, "pgpool", p):
        result = db.upsert_restaurant({"name": "Cafe de Paris", "slug": "cafe-de-paris"})
    assert result == "rid-cafe"


def test_step5_smart_quote_match():
    """Incoming name with U+2019 smart quote matches DB row stored with U+0027."""
    stored_name = "L'Atelier"   # straight apostrophe (U+0027)
    incoming_name = "L’Atelier"  # curly right-single-quote (U+2019)
    p = _make_pgpool(
        candidates=[{"id": "rid-atelier", "name": stored_name, "cuisine": None,
                     "image_url": None, "lat": None, "lng": None, "geo_source": None}],
    )
    import db
    db.invalidate_domain_cache()
    with patch.object(db, "pgpool", p):
        result = db.upsert_restaurant({"name": incoming_name, "slug": "l-atelier"})
    assert result == "rid-atelier"


def test_no_match_inserts_new_row():
    """All 5 steps miss → insert called, new id returned."""
    p = _make_pgpool(insert_id="brand-new")
    import db
    db.invalidate_domain_cache()
    with patch.object(db, "pgpool", p):
        result = db.upsert_restaurant({"name": "Brand New Place", "slug": "brand-new-place"})
    assert result == "brand-new"


def test_cuisine_inferred_when_absent():
    """cuisine is auto-inferred from name when not supplied (passed to the insert)."""
    p = _make_pgpool(insert_id="new-pizza")
    captured = {}
    import db
    db.invalidate_domain_cache()
    orig = db._build_insert

    def _spy(table, data, **kw):
        if table == "restaurants":
            captured.update(data)
        return orig(table, data, **kw)

    with patch.object(db, "pgpool", p), patch.object(db, "_build_insert", _spy):
        db.upsert_restaurant({"name": "Pizza Nova", "slug": "pizza-nova"})
    assert captured["cuisine"] == "Pizza"


def test_explicit_cuisine_not_overridden():
    """Caller-supplied cuisine is preserved even when name would infer differently."""
    p = _make_pgpool(insert_id="new")
    captured = {}
    import db
    db.invalidate_domain_cache()
    orig = db._build_insert

    def _spy(table, data, **kw):
        if table == "restaurants":
            captured.update(data)
        return orig(table, data, **kw)

    with patch.object(db, "pgpool", p), patch.object(db, "_build_insert", _spy):
        db.upsert_restaurant({"name": "Pizza Nova", "slug": "pizza-nova", "cuisine": "Italian"})
    assert captured["cuisine"] == "Italian"


def test_found_enriches_cuisine():
    """_found pushes inferred cuisine onto an existing row that has none."""
    p = _make_pgpool(exact={"id": "rid-123", "cuisine": None, "image_url": None,
                            "lat": None, "lng": None, "geo_source": None})
    import db
    db.invalidate_domain_cache()
    with patch.object(db, "pgpool", p):
        db.upsert_restaurant({"name": "Burger Palace", "slug": "burger-palace"})
    merged = {k: v for u in p.updates for k, v in u.items()}
    assert merged.get("cuisine") == "Burgers"


def test_found_does_not_overwrite_existing_cuisine():
    """_found leaves cuisine alone when the existing row already has one."""
    p = _make_pgpool(exact={"id": "rid-123", "cuisine": "Belgian", "image_url": None,
                            "lat": None, "lng": None, "geo_source": None})
    import db
    db.invalidate_domain_cache()
    with patch.object(db, "pgpool", p):
        db.upsert_restaurant({"name": "Burger Palace", "slug": "burger-palace"})
    for payload in p.updates:
        assert "cuisine" not in payload


def test_found_always_updates_coords():
    """lat/lng are pushed to the existing row when supplied (coords can shift)."""
    p = _make_pgpool(exact={"id": "rid-123", "cuisine": "Burgers", "image_url": None,
                            "lat": None, "lng": None, "geo_source": "uber_eats"})
    import db
    db.invalidate_domain_cache()
    with patch.object(db, "pgpool", p):
        db.upsert_restaurant({"name": "Burger King", "slug": "bk",
                              "lat": 50.85, "lng": 4.35, "geo_source": "uber_eats"})
    merged = {k: v for u in p.updates for k, v in u.items()}
    assert merged["lat"] == 50.85
    assert merged["lng"] == 4.35


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
        slug_match=False,
        distinctive_conflict=False,
        address_match=None,
    )
    defaults.update(kw)
    return matching.MatchFeatures(**defaults)


def _feat(**kw) -> matching.MatchFeatures:
    """Build MatchFeatures for evidence-score / decide() tests."""
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
        slug_match=False,
        distinctive_conflict=False,
        address_match=None,
        deliveroo_geo=False,
        name_variant="plain",
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


def test_decide_website_plus_near_identical_name_queues_without_proof():
    # name(2.0) + website(1.0) = 3.0 < AUTO_BAND → QUEUE (no hard proof)
    f = _f(name_sim=0.98, website_match=True)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_phone_signal_queues_below_auto_band():
    # name_high(1.0) + phone(3.0) = 4.0 < AUTO_BAND=4.5 → QUEUE
    f = _f(name_sim=0.95, phone_match=True)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_website_with_location_suffix_queues_not_merges():
    # shared chain domain + distinguishing location suffix (mid name_sim) → review
    f = _f(name_sim=0.93, website_match=True)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_close_geo_queues_below_auto_band():
    # name_high(1.0) + geo_close(2.0) = 3.0 < AUTO_BAND → QUEUE
    f = _f(name_sim=0.95, geo_dist=40.0)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_name_only_queues_not_auto_merges():
    # name_very_high(2.0) alone < AUTO_BAND=4.5 → QUEUE
    f = _f(name_sim=0.97)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_name_below_threshold_separates():
    # name_high(1.0) alone < QUEUE_BAND=1.5 → SEPARATE
    f = _f(name_sim=0.95)
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_decide_geo_veto_separates_even_if_name_identical():
    # > HARD_GEO_SEPARATE_M(1000m), no phone → SEPARATE regardless of score
    f = _f(name_sim=1.0, geo_dist=1100.0)
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


def test_decide_no_cuisine_conflict_queues_at_name_threshold():
    # name_very_high(2.0) alone < AUTO_BAND → QUEUE
    f = _f(name_sim=0.97, cuisine_conflict=False)
    assert matching.decide(f) == matching.Decision.QUEUE


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

def test_decide_menu_overlap_low_queues():
    # name_very_high(2.0) + address_diff(-3.0 if False, but None here) = 2.0 → QUEUE
    # Low menu_overlap has no negative weight in additive model (only no bonus)
    f = _f(name_sim=0.97, menu_overlap=0.01)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_menu_overlap_confirm_queues_below_auto_band():
    # name_high(1.0) + menu_overlap(1.0) = 2.0 < AUTO_BAND → QUEUE
    f = _f(name_sim=0.92, menu_overlap=0.20)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_menu_overlap_none_queues():
    # name_very_high(2.0) alone < AUTO_BAND → QUEUE
    f = _f(name_sim=0.97, menu_overlap=None)
    assert matching.decide(f) == matching.Decision.QUEUE


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

def test_decide_soft_geo_veto_above_threshold_queues():
    # soft_geo_dist not used by additive model; name_very_high(2.0) → QUEUE
    f = _f(name_sim=0.97, soft_geo_dist=700.0)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_soft_geo_below_threshold_queues():
    # soft_geo_dist has no positive weight; name_very_high(2.0) < AUTO_BAND → QUEUE
    f = _f(name_sim=0.97, soft_geo_dist=400.0)
    assert matching.decide(f) == matching.Decision.QUEUE


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

def test_decide_chain_name_without_strong_confirm_queues():
    # is_chain_name has no weight in additive model; name_very_high(2.0) → QUEUE
    f = _f(name_sim=0.97, is_chain_name=True)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_chain_name_with_phone_confirm_queues_below_auto_band():
    # name_very_high(2.0) + phone(3.0) = 5.0 >= AUTO_BAND; phone is proof → AUTO_MERGE
    f = _f(name_sim=0.97, is_chain_name=True, phone_match=True)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_decide_chain_name_with_close_geo_queues():
    # name_very_high(2.0) + geo_close(2.0) = 4.0 < AUTO_BAND → QUEUE
    f = _f(name_sim=0.97, is_chain_name=True, geo_dist=40.0)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_chain_name_with_menu_confirm_queues():
    # name_high(1.0) + menu_overlap(1.0) = 2.0 < AUTO_BAND → QUEUE
    f = _f(name_sim=0.92, is_chain_name=True, menu_overlap=0.20)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_non_chain_name_queues_at_name_threshold():
    # name_very_high(2.0) alone < AUTO_BAND → QUEUE
    f = _f(name_sim=0.97, is_chain_name=False)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_score_pair_chain_name_detected():
    # chain_names uses significant_first_token: "Pizza Napoli" → "pizza"
    chain_names = {"pizza"}
    a = _r("Pizza Napoli", id="a1")
    b = _r("Pizza Napoli", id="b1")
    f = matching.score_pair(a, b, chain_names=chain_names)
    assert f.is_chain_name is True


def test_score_pair_is_chain_db_flag_sets_chain_name():
    # Persisted restaurants.is_chain=true flags the pair as chain even when the
    # count heuristic (chain_names) would not.
    a = _r("Quick Burger", id="a1")
    a["is_chain"] = True
    b = _r("Quick Burger", id="b1")
    f = matching.score_pair(a, b, chain_names=set())
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
        "menu_overlap", "soft_geo_dist", "is_chain_name", "slug_match",
        "distinctive_conflict",
    }
    assert expected.issubset(d.keys())


def test_distinctive_conflict_separates_shared_prefix():
    # "Pizza Vito" / "Pizza Mio" — generic prefix, different remainder.
    a = _r("Pizza Vito", id="a1")
    b = _r("Pizza Mio", id="b1")
    f = matching.score_pair(a, b)
    assert f.distinctive_conflict is True
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_distinctive_conflict_not_set_for_same_remainder():
    # "Pizza Bella" / "Pizza Bela" — typo, same venue → no conflict.
    a = _r("Pizza Bella", id="a1")
    b = _r("Pizza Bela", id="b1")
    f = matching.score_pair(a, b)
    assert f.distinctive_conflict is False


def test_distinctive_conflict_with_slug_separates():
    # name_high(1.0) + slug_match(2.0) + distinctive_conflict(-2.0) = 1.0 < QUEUE_BAND → SEPARATE
    f = _f(name_sim=0.93, distinctive_conflict=True, slug_match=True)
    assert matching.decide(f) == matching.Decision.SEPARATE


# ---------------------------------------------------------------------------
# Slug match signal
# ---------------------------------------------------------------------------

def test_slug_match_fires_on_shared_normalized_slug():
    a = _r("Bar BQ Brasserie", id="a1")
    b = _r("Barbq Brasserie", id="b1")
    slugs = {"a1": ["barbq-brasserie"], "b1": ["barbq-brasserie"]}
    f = matching.score_pair(a, b, slugs=slugs)
    assert f.slug_match is True


def test_slug_match_strips_brussels_suffix():
    a = _r("Wok Up", id="a1")
    b = _r("WokUp", id="b1")
    slugs = {"a1": ["wok-up-bruxelles"], "b1": ["wokup"]}
    f = matching.score_pair(a, b, slugs=slugs)
    assert f.slug_match is True


def test_slug_match_false_for_different_slugs():
    a = _r("Pizza Roma", id="a1")
    b = _r("Pizza Napoli", id="b1")
    slugs = {"a1": ["pizza-roma"], "b1": ["pizza-napoli"]}
    f = matching.score_pair(a, b, slugs=slugs)
    assert f.slug_match is False


def test_slug_match_queues_below_auto_band():
    # name_high(1.0) + slug_match(2.0) = 3.0 < AUTO_BAND → QUEUE
    f = _f(name_sim=0.96, slug_match=True, is_chain_name=False)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_halal_suffix_stripped_from_canonical():
    # "Express Pizza Halal" → "Express Pizza" after canonical
    import matching as m
    assert m.normalize_name("Express Pizza Halal") == m.normalize_name("Express Pizza")


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


def test_block_candidates_geo_proximity_pairs_unrelated_names():
    a = _r("Totally Different", id="g1", lat=50.8500, lng=4.3500, geo_source="uber_eats")
    b = _r("Other Name Entirely", id="g2", lat=50.8501, lng=4.3501, geo_source="takeaway")
    far = _r("Third Place", id="g3", lat=50.9000, lng=4.4000, geo_source="takeaway")
    pairs = matching.block_candidates([a, b, far])
    ids = {tuple(sorted((str(x["id"]), str(y["id"])))) for x, y in pairs}
    assert ("g1", "g2") in ids
    assert tuple(sorted(("g1", "g3"))) not in ids


# ---------------------------------------------------------------------------
# Proof-gate: AUTO_MERGE requires hard same-venue evidence
# ---------------------------------------------------------------------------

def test_auto_requires_hard_proof_else_queue():
    # 2-branch unflagged chain: name + near geo + website + menu pile to >= AUTO
    # band but carry no same-venue proof -> queue, never silent auto-merge
    f = _feat(name_sim=0.99, geo_dist=150.0, website_match=True, menu_overlap=0.5)
    total, _ = matching.evidence_score(f)
    assert total >= matching.AUTO_BAND
    assert matching.decide(f) == matching.Decision.QUEUE


def test_auto_proof_via_address():
    f = _feat(name_sim=0.99, geo_dist=150.0, website_match=True, menu_overlap=0.5,
              address_match=True)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_auto_proof_via_very_close_geo():
    f = _feat(name_sim=0.99, geo_dist=10.0, website_match=True)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_ghost_kitchen_shared_phone_address_different_name_queues():
    # Cloud kitchen: two distinct virtual brands at one address share a phone.
    # Physical proof piles past AUTO_BAND, but dissimilar names fail the
    # identity gate -> QUEUE for human review, never silent AUTO_MERGE.
    f = _feat(name_sim=0.30, phone_match=True, geo_dist=5.0, address_match=True)
    total, _ = matching.evidence_score(f)
    assert total >= matching.AUTO_BAND
    assert matching.decide(f) == matching.Decision.QUEUE


def test_identity_via_slug_still_auto_merges():
    f = _feat(name_sim=0.30, slug_match=True, geo_dist=5.0)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_identity_via_name_still_auto_merges():
    f = _feat(name_sim=0.99, phone_match=True, geo_dist=5.0)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_colocation_gate_blocks_geo_without_identity():
    # Food-court neighbours: 30m apart, different names, no shared phone/slug.
    # Proximity must NOT count toward a merge -> below QUEUE band -> SEPARATE.
    f = _feat(name_sim=0.30, geo_dist=30.0)
    total, contrib = matching.evidence_score(f)
    assert "geo_very_close" not in contrib
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_colocation_gate_opens_with_phone():
    # Ghost kitchen: shared phone opens the gate, geo counts -> queues (identity
    # gate still blocks AUTO since names differ).
    f = _feat(name_sim=0.30, geo_dist=30.0, phone_match=True)
    _, contrib = matching.evidence_score(f)
    assert "geo_close" in contrib
    assert matching.decide(f) == matching.Decision.QUEUE


def test_shares_distinctive_token_helper():
    # distinctive brand token shared despite generic prefix + commune suffix
    assert matching.shares_distinctive_token(
        "Ai 6 Angoli Saint-Gilles", "Pizzeria Trattoria Ai 6 angoli")
    # pure neighbours: no shared distinctive token
    assert not matching.shares_distinctive_token("Taste of Himalayan", "Pasta Commedia")
    # shared token is generic only ("wok") → not distinctive identity
    assert not matching.shares_distinctive_token("Wok & Go", "China Wok")


def test_colocation_gate_opens_on_shared_token():
    # "Ai 6 Angoli" pair: full-name JW < 0.80, no phone, but shared "angoli"
    # opens the gate so 9m geo counts → not silently separated.
    f = _feat(name_sim=0.70, geo_dist=9.0, shares_token=True)
    _, contrib = matching.evidence_score(f)
    assert "geo_very_close" in contrib
