"""Unit tests for the presence-probe decision function.

Pure logic, no DB / network. Distances use a Brussels base point; latitude
offsets are converted at ~111320 m/deg so the metres in each test name are
realistic (haversine, lat-only offset).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from presence_probe import Candidate, classify_presence  # noqa: E402

BASE_LAT = 50.8466
BASE_LNG = 4.3528
_M_PER_DEG_LAT = 111_320.0


def _at(metres_north: float) -> tuple[float, float]:
    """Coordinates ``metres_north`` due north of the base point."""
    return BASE_LAT + metres_north / _M_PER_DEG_LAT, BASE_LNG


def _cand(name, *, metres=None, cuisine=None, url="https://x/menu/slug"):
    if metres is None:
        lat = lng = None
    else:
        lat, lng = _at(metres)
    return Candidate(name=name, url=url, lat=lat, lng=lng, cuisine=cuisine)


# --- present ---------------------------------------------------------------

def test_present_proximity_plus_name():
    # ~80 m away, clearly the same name -> present (normal band, not colocation).
    res = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine=None, name="Pizza Roma",
        candidates=[_cand("Pizza Roma", metres=80)], missing_platform="uber_eats",
    )
    assert res.outcome == "present"
    assert res.matched_url == "https://x/menu/slug"
    assert 50 < res.candidate_distance_m < 120


def test_present_proximity_plus_cuisine_when_names_differ():
    # Renamed across platforms: names differ, but same cuisine + close -> present.
    res = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine="pizza", name="Pizza Roma",
        candidates=[_cand("Bella Napoli", metres=80, cuisine="pizza")],
        missing_platform="uber_eats",
    )
    assert res.outcome == "present"
    assert res.candidate_name == "Bella Napoli"


# --- absent ----------------------------------------------------------------

def test_absent_far_dissimilar_candidate():
    # A candidate exists ~5 km away with an unrelated name -> not a corroborator.
    res = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine="pizza", name="Pizza Roma",
        candidates=[_cand("Sushi World", metres=5000, cuisine="sushi")],
        missing_platform="uber_eats",
    )
    assert res.outcome == "absent"
    assert res.matched_url is None
    assert res.candidate_distance_m is None


def test_absent_no_candidates():
    res = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine="pizza", name="Pizza Roma",
        candidates=[], missing_platform="takeaway",
    )
    assert res.outcome == "absent"


# --- uncertain: blocked ----------------------------------------------------

def test_blocked_returns_uncertain_even_with_perfect_candidate():
    # The blocked check wins over an otherwise-perfect on-pin candidate.
    res = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine="pizza", name="Pizza Roma",
        candidates=[_cand("Pizza Roma", metres=5, cuisine="pizza")],
        missing_platform="deliveroo", blocked=True, block_reason="captcha",
    )
    assert res.outcome == "uncertain"
    assert res.block_reason == "captcha"
    assert res.matched_url is None


# --- ghost kitchen ---------------------------------------------------------

def test_ghost_kitchen_no_corroboration_is_uncertain():
    # Two unrelated brands at the same address (~10 m), neither corroborating.
    res = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine="pizza", name="Pizza Roma",
        candidates=[_cand("Wok Express", metres=10), _cand("Burger Hub", metres=12)],
        missing_platform="uber_eats",
    )
    assert res.outcome == "uncertain"
    assert res.block_reason == "colocated_no_corroboration"


def test_ghost_kitchen_disambiguated_by_cuisine_is_present():
    # Same shared address, but one colocated brand matches cuisine -> present,
    # and it is chosen regardless of being slightly farther / later in the list.
    res = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine="pizza", name="Pizza Roma",
        candidates=[_cand("Burger Hub", metres=10), _cand("Napoli Slice", metres=15, cuisine="pizza")],
        missing_platform="uber_eats",
    )
    assert res.outcome == "present"
    assert res.candidate_name == "Napoli Slice"


# --- deliveroo widened band ------------------------------------------------

def test_deliveroo_band_widens_vs_ubereats():
    # The SAME ~300 m candidate corroborated by cuisine (dissimilar name):
    # present on deliveroo (zone-centroid coords -> 300 m is inside its present
    # band), uncertain on uber_eats (venue-grade; 300 m is past the 120 m band,
    # and the dissimilar name does not clear the strong-name gate).
    cand = _cand("Trattoria Verde", metres=300, cuisine="pizza")
    deliv = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine="pizza", name="Pizza Roma",
        candidates=[cand], missing_platform="deliveroo",
    )
    uber = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine="pizza", name="Pizza Roma",
        candidates=[cand], missing_platform="uber_eats",
    )
    assert deliv.outcome == "present"
    assert uber.outcome == "uncertain"
    assert uber.block_reason == "weak_corroboration"


# --- coords-missing (name-only) --------------------------------------------

def test_coords_missing_strong_name_is_present():
    res = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine=None, name="Pizza Roma",
        candidates=[_cand("Pizza Roma", metres=None)], missing_platform="takeaway",
    )
    assert res.outcome == "present"
    assert res.candidate_distance_m is None


def test_coords_missing_dissimilar_name_is_absent():
    res = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine=None, name="Pizza Roma",
        candidates=[_cand("Sushi World", metres=None)], missing_platform="takeaway",
    )
    assert res.outcome == "absent"


# --- proximity-only mid-band -----------------------------------------------

def test_proximity_only_without_corroboration_is_uncertain():
    # ~100 m away, name unrelated and no cuisine -> proximity alone is not enough.
    res = classify_presence(
        lat=BASE_LAT, lng=BASE_LNG, cuisine=None, name="Pizza Roma",
        candidates=[_cand("Dragon Wok", metres=100)], missing_platform="uber_eats",
    )
    assert res.outcome == "uncertain"
    assert res.block_reason == "proximity_only"
