"""
Unit tests for backend/scrapers/enrich_contacts.py — PURE LOGIC ONLY.

No network, no browser, no DB. The resolver, fsq matcher, channel classifier
and phone normalization are all pure functions over plain dicts/lists.
"""
from __future__ import annotations

import pytest

from scrapers.direct import _normalize_phone
from scrapers.enrich_contacts import (
    classify_channel,
    covered_domain,
    match_fsq_place,
    name_match_score,
    resolve_contacts,
    valid_phone,
)


# ── Belgian phone validation (rejects phone-shaped garbage) ───────────────────

@pytest.mark.parametrize("raw", [
    "+32483080107",   # mobile
    "+3224659671",    # Brussels landline
    "02 465 96 71",   # raw landline
    "0488 81 59 11",  # raw mobile
])
def test_valid_phone_accepts_real_belgian(raw):
    assert valid_phone(raw) is not None


@pytest.mark.parametrize("raw", [
    "+32557714815",   # invalid prefix 55x — scraped garbage
    "+32124652751",   # invalid 12x 9-digit
    "+32770998122",   # invalid 77x
    "+32750488010",   # defunct 75x
    None,
    "",
    "12345",
])
def test_valid_phone_rejects_garbage(raw):
    assert valid_phone(raw) is None


# ── Channel classification ────────────────────────────────────────────────────

def test_channel_covered_platform_extracts_via():
    chan, via = classify_channel("https://www.ubereats.com/be/store/foo")
    assert chan == "covered_platform"
    assert via == "ubereats.com"


def test_channel_covered_deliveroo_be():
    chan, via = classify_channel("https://deliveroo.be/fr/menu/bruxelles/foo")
    assert chan == "covered_platform"
    assert via == "deliveroo.be"


def test_channel_direct_when_own_website():
    chan, via = classify_channel("https://chez-leon.be")
    assert chan == "direct"
    assert via is None


def test_channel_direct_when_phone_only():
    chan, via = classify_channel(None, phone="+3221234567")
    assert chan == "direct"
    assert via is None


def test_channel_unknown_when_nothing():
    assert classify_channel(None) == ("unknown", None)
    assert classify_channel("") == ("unknown", None)


def test_covered_domain_negative():
    assert covered_domain("https://my-restaurant.be") is None
    assert covered_domain(None) is None


# ── Phone normalization passthrough (reuse direct._normalize_phone) ───────────

@pytest.mark.parametrize("raw,expected", [
    # Mobile (0-prefix, 10 digits) normalizes.
    ("0475 12 34 56", "+32475123456"),
    ("+32475123456", "+32475123456"),
    # Brussels landline (9 digits) only normalizes with an explicit country prefix
    # — this mirrors direct._normalize_phone's real behavior (we don't alter it).
    ("+32 2 511 14 15", "+3225111415"),
    ("0032 2 511 14 15", "+3225111415"),
])
def test_phone_normalization_belgian(raw, expected):
    assert _normalize_phone(raw) == expected


def test_phone_normalization_rejects_garbage():
    assert _normalize_phone("hello") is None
    assert _normalize_phone("123") is None


# ── fsq name+geo matcher ──────────────────────────────────────────────────────

_REST = {"name": "Chez Léon", "lat": 50.8467, "lng": 4.3525}


def _fsq(name, lat, lng, tel=None, website=None):
    return {"fsq_place_id": "x", "name": name, "latitude": lat,
            "longitude": lng, "tel": tel, "website": website}


def test_fsq_matches_exact_name_close():
    cands = [_fsq("Chez Leon", 50.8467, 4.3525, tel="02 511 14 15")]
    m = match_fsq_place(_REST, cands)
    assert m is not None
    assert m["tel"] == "02 511 14 15"
    assert m["_score"] >= 85


def test_fsq_matches_near_name_within_distance():
    # ~33m away, name differs only by accent/case (normalizes equal → score 100).
    cands = [_fsq("CHEZ LEON", 50.8470, 4.3525)]
    m = match_fsq_place(_REST, cands)
    assert m is not None


def test_fsq_rejects_far_even_if_name_matches():
    # ~1km away → distance gate rejects regardless of perfect name.
    cands = [_fsq("Chez Léon", 50.8557, 4.3525)]
    assert match_fsq_place(_REST, cands) is None


def test_fsq_rejects_low_name_score_when_close():
    cands = [_fsq("Pizza Hut", 50.8467, 4.3525)]
    assert match_fsq_place(_REST, cands) is None


def test_fsq_picks_best_of_several():
    cands = [
        _fsq("Chez Le", 50.8467, 4.3526),          # weaker name
        _fsq("Chez Léon", 50.8467, 4.3525, tel="02 511 14 15"),  # best
    ]
    m = match_fsq_place(_REST, cands)
    assert m["tel"] == "02 511 14 15"


def test_fsq_no_geo_returns_none():
    assert match_fsq_place({"name": "X", "lat": None, "lng": None}, []) is None


def test_name_match_score_bounds():
    assert name_match_score("Chez Léon", "Chez Leon") >= 85
    assert name_match_score("Foo", "Completely Different") < 50
    assert name_match_score(None, "X") == 0


# ── Resolver: tiers, tiebreak, channel, never-overwrite ───────────────────────

def _cand(source, phone=None, website=None, channel="unknown", via=None):
    return {"source": source, "phone_e164": phone, "website": website,
            "order_channel": channel, "covered_via": via}


def test_resolver_two_sources_agree_high():
    r = {"name": "X", "phone": None}
    cands = [
        _cand("google_maps", "+3221234567"),
        _cand("fsq", "+3221234567"),
    ]
    res = resolve_contacts(r, cands)
    assert res["phone"] == "+3221234567"
    assert res["phone_confidence"] == "high"
    assert res["phone_source"] == "fsq+google_maps"
    assert res["set_phone"] is True


def test_resolver_single_google_maps_medium():
    res = resolve_contacts({"name": "X", "phone": None},
                           [_cand("google_maps", "+3221234567")])
    assert res["phone_confidence"] == "medium"
    assert res["phone_source"] == "google_maps"


def test_resolver_single_website_medium():
    res = resolve_contacts({"name": "X", "phone": None},
                           [_cand("website", "+3221234567")])
    assert res["phone_confidence"] == "medium"


def test_resolver_fsq_only_low():
    res = resolve_contacts({"name": "X", "phone": None},
                           [_cand("fsq", "+3221234567")])
    assert res["phone_confidence"] == "low"


def test_resolver_no_phone_no_confidence():
    res = resolve_contacts({"name": "X", "phone": None},
                           [_cand("google_maps", None, website="https://x.be",
                                  channel="direct")])
    assert res["phone"] is None
    assert res["phone_confidence"] is None
    assert res["order_channel"] == "direct"
    assert res["set_phone"] is False


def test_resolver_winning_phone_most_corroborated():
    # phone A from 1 source, phone B from 2 → B wins.
    cands = [
        _cand("google_maps", "+3220000001"),
        _cand("website", "+3220000002"),
        _cand("fsq", "+3220000002"),
    ]
    res = resolve_contacts({"name": "X", "phone": None}, cands)
    assert res["phone"] == "+3220000002"
    assert res["phone_confidence"] == "high"
    assert res["phone_source"] == "fsq+website"


def test_resolver_tiebreak_source_priority():
    # Two different single-source phones tie on count(1) → website beats fsq.
    cands = [
        _cand("fsq", "+3220000001"),
        _cand("website", "+3220000002"),
    ]
    res = resolve_contacts({"name": "X", "phone": None}, cands)
    assert res["phone"] == "+3220000002"  # website priority > fsq
    assert res["phone_source"] == "website"


def test_resolver_channel_direct_wins_over_covered():
    cands = [
        _cand("google_maps", website="https://ubereats.com/x",
              channel="covered_platform", via="ubereats.com"),
        _cand("website", website="https://own-site.be", channel="direct"),
    ]
    res = resolve_contacts({"name": "X", "phone": None}, cands)
    assert res["order_channel"] == "direct"


def test_resolver_channel_covered_when_no_direct():
    cands = [_cand("google_maps", website="https://ubereats.com/x",
                   channel="covered_platform", via="ubereats.com")]
    res = resolve_contacts({"name": "X", "phone": None}, cands)
    assert res["order_channel"] == "covered_platform"


def test_resolver_never_overwrites_existing_phone():
    r = {"name": "X", "phone": "+3229999999"}  # already has a phone
    cands = [
        _cand("google_maps", "+3221234567"),
        _cand("website", "+3221234567"),
    ]
    res = resolve_contacts(r, cands)
    assert res["phone"] == "+3221234567"        # winning still computed
    assert res["phone_confidence"] == "high"    # confidence still recorded
    assert res["set_phone"] is False            # but won't be written


def test_resolver_existing_blank_phone_is_writable():
    r = {"name": "X", "phone": "   "}  # whitespace == empty
    res = resolve_contacts(r, [_cand("website", "+3221234567")])
    assert res["set_phone"] is True
