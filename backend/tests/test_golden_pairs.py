"""Golden-pair contract: labeled real pairs from prod (2026-06-12).

`same`      → must score >= QUEUE band (never SEPARATE)
`different` → must never AUTO_MERGE (SEPARATE or QUEUE both fine)
`ambiguous` → skipped until the user confirms labels
"""
import json
import os

import pytest

import matching

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "golden_pairs.json")
with open(_FIXTURE) as f:
    _GOLDEN = json.load(f)


def _to_row(d: dict, idx: int) -> dict:
    return {
        "id": f"golden-{idx}",
        "name": d["name"],
        "phone": d.get("phone"),
        "cuisine": d.get("cuisine"),
        "lat": d.get("lat"),
        "lng": d.get("lng"),
        "geo_source": d.get("geo_source"),
        "is_chain": d.get("is_chain", False),
        "website": d.get("website"),
        "street_address": d.get("street_address"),
        "postal_code": d.get("postal_code"),
    }


def _decide(pair: dict) -> matching.Decision:
    a, b = _to_row(pair["a"], 0), _to_row(pair["b"], 1)
    slugs = {"golden-0": pair["a"].get("slugs", []), "golden-1": pair["b"].get("slugs", [])}
    feats = matching.score_pair(a, b, menus={}, chain_names=set(), slugs=slugs)
    return matching.decide(feats)


def _label(pair):
    return f"{pair['a']['name']} / {pair['b']['name']}"


@pytest.mark.parametrize("pair", _GOLDEN["same"], ids=_label)
def test_same_pairs_never_separate(pair):
    decision = _decide(pair)
    assert decision in (matching.Decision.AUTO_MERGE, matching.Decision.QUEUE), (
        f"known-same pair classified SEPARATE: {_label(pair)}"
    )


@pytest.mark.parametrize("pair", _GOLDEN["different"], ids=_label)
def test_different_pairs_never_auto_merge(pair):
    decision = _decide(pair)
    assert decision in (matching.Decision.SEPARATE, matching.Decision.QUEUE), (
        f"known-different pair AUTO_MERGED: {_label(pair)}"
    )
