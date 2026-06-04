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


def test_decide_strong_signal_auto_merges():
    f = matching.MatchFeatures(name_sim=0.95, website_match=True,
                               phone_match=False, geo_dist=None, cuisine_match=False)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_decide_close_geo_auto_merges():
    f = matching.MatchFeatures(name_sim=0.95, website_match=False,
                               phone_match=False, geo_dist=40.0, cuisine_match=False)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE


def test_decide_name_only_queues():
    f = matching.MatchFeatures(name_sim=0.97, website_match=False,
                               phone_match=False, geo_dist=None, cuisine_match=False)
    assert matching.decide(f) == matching.Decision.QUEUE


def test_decide_geo_veto_separates_even_if_name_identical():
    f = matching.MatchFeatures(name_sim=1.0, website_match=False,
                               phone_match=False, geo_dist=900.0, cuisine_match=False)
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_decide_low_name_separates():
    f = matching.MatchFeatures(name_sim=0.40, website_match=False,
                               phone_match=False, geo_dist=None, cuisine_match=False)
    assert matching.decide(f) == matching.Decision.SEPARATE


def test_decide_website_match_overrides_far_geo_is_still_veto():
    f = matching.MatchFeatures(name_sim=0.95, website_match=True,
                               phone_match=False, geo_dist=1200.0, cuisine_match=False)
    assert matching.decide(f) == matching.Decision.SEPARATE


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
