"""Presence-probe decision logic.

Pure classifier that answers, for one single-platform restaurant against one
platform it is *missing* from: is it actually present (and deliverable to a pin
set at the restaurant's own address), genuinely absent, or uncertain?

The outcome is deliberately three-way and must never collapse to a binary:

  present   - a candidate confidently matches the venue -> recoverable
  absent    - search succeeded, no candidate corroborates -> genuine exclusive
  uncertain - a candidate was found but proximity/cuisine/name did not
              corroborate confidently, OR the search itself was blocked/captcha'd

Matching is on *location first* (the pin sits at the restaurant's own address),
with cuisine and name as corroborators only — restaurants are renamed across
platforms, so a name-equality gate would over-report exclusives. Proximity alone
cannot disambiguate shared-coordinate buildings (ghost kitchens: many brands at
one address), so at very short range we *require* name or cuisine corroboration.

Distance thresholds are derived from the matcher's geo bands (matching.geo_band)
but applied differently: here the geometry is pin(own-address) -> candidate, the
*expected* location, not the matcher's coincidental venue<->venue case. Deliveroo
result coordinates are zone-centroids (not venue-accurate), so its bands widen.

Reuses matching.haversine_m / normalize_name / _cuisine_conflict and the same
Jaro-Winkler name similarity the matcher uses.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz.distance import JaroWinkler

from matching import haversine_m, normalize_name, _cuisine_conflict

# Pin(own-address) -> candidate distance thresholds, in metres.
PRESENT_M = 120.0          # non-deliveroo: confident same address/building
UNCERTAIN_MAX_M = 400.0    # beyond this a candidate corroborates only via a strong name
PRESENT_M_DELIV = 700.0    # deliveroo coords are zone-centroids -> widened ('near' band)
UNCERTAIN_MAX_DELIV = 1500.0  # deliveroo upper window
COLOCATION_M = 35.0        # <= this => shared-coordinate building (ghost kitchen)

WEAK_NAME_SIM = 0.80       # >= weakly corroborates (matcher's co-location/identity gate)
STRONG_NAME_SIM = 0.92     # >= lets a far / coords-missing candidate still confirm


@dataclass
class Candidate:
    """A single search-result card from the missing platform (no menu data)."""

    name: str
    url: str
    lat: float | None
    lng: float | None
    cuisine: str | None


@dataclass
class ProbeResult:
    outcome: str  # 'present' | 'absent' | 'uncertain'
    matched_url: str | None
    candidate_distance_m: float | None
    candidate_name: str | None
    block_reason: str | None


def _name_sim(a: str, b: str) -> float:
    return JaroWinkler.similarity(normalize_name(a), normalize_name(b))


def _corroborates(name: str, cuisine: str | None, c: Candidate) -> bool:
    """Name OR cuisine weakly corroborates that ``c`` is the same venue."""
    if _name_sim(name, c.name) >= WEAK_NAME_SIM:
        return True
    return bool(cuisine) and bool(c.cuisine) and not _cuisine_conflict(cuisine, c.cuisine)


def classify_presence(
    *,
    lat: float,
    lng: float,
    cuisine: str | None,
    name: str,
    candidates: list[Candidate],
    missing_platform: str,
    blocked: bool = False,
    block_reason: str | None = None,
) -> ProbeResult:
    """Classify whether ``name`` (at lat/lng) is present on ``missing_platform``.

    ``candidates`` are the result cards returned by that platform's search with
    the delivery pin set at the restaurant's own address.
    """
    # 1. A blocked/captcha'd search can never prove a negative -> always uncertain.
    #    This check is first so a block never masquerades as present/absent.
    if blocked:
        return ProbeResult("uncertain", None, None, None, block_reason or "blocked")

    deliveroo = missing_platform == "deliveroo"
    present_m = PRESENT_M_DELIV if deliveroo else PRESENT_M
    max_m = UNCERTAIN_MAX_DELIV if deliveroo else UNCERTAIN_MAX_M

    # 2. Build the eligible candidate set. Candidates without coordinates can only
    #    corroborate by name (distance treated as infinite). A coords-bearing
    #    candidate that is both too far AND not strongly named is not a
    #    corroborator at all and is dropped.
    eligible: list[tuple[float, Candidate]] = []
    for c in candidates:
        if c.lat is None or c.lng is None:
            if _name_sim(name, c.name) >= WEAK_NAME_SIM:
                eligible.append((float("inf"), c))
            continue
        d = haversine_m(lat, lng, c.lat, c.lng)
        if d > max_m and _name_sim(name, c.name) < STRONG_NAME_SIM:
            continue
        eligible.append((d, c))

    # 3. Nothing corroborable -> genuine absence.
    if not eligible:
        return ProbeResult("absent", None, None, None, None)

    eligible.sort(key=lambda dc: dc[0])
    best_dist, best = eligible[0]

    # Ghost-kitchen disambiguation: when the nearest candidate sits in a
    # shared-coordinate building, prefer a corroborating brand at that address
    # over an arbitrary nearest neighbour, regardless of card order.
    if best_dist <= COLOCATION_M:
        cluster_corrob = [dc for dc in eligible if dc[0] <= COLOCATION_M and _corroborates(name, cuisine, dc[1])]
        if cluster_corrob:
            best_dist, best = cluster_corrob[0]

    name_strong = _name_sim(name, best.name) >= STRONG_NAME_SIM
    corroborated = _corroborates(name, cuisine, best)
    dist_out = None if best_dist == float("inf") else best_dist

    # 4a. Ghost-kitchen guard: at a shared-coordinate building proximity is
    #     meaningless. Require name OR cuisine; otherwise uncertain.
    if dist_out is not None and dist_out <= COLOCATION_M:
        if corroborated:
            return ProbeResult("present", best.url, dist_out, best.name, None)
        return ProbeResult("uncertain", best.url, dist_out, best.name, "colocated_no_corroboration")

    # 4b. Normal present band (pin is the venue's own address).
    if dist_out is not None and dist_out <= present_m:
        if corroborated:
            return ProbeResult("present", best.url, dist_out, best.name, None)
        return ProbeResult("uncertain", best.url, dist_out, best.name, "proximity_only")

    # 4c. Beyond the present band, or coords-missing: only a strong name confirms.
    if name_strong:
        return ProbeResult("present", best.url, dist_out, best.name, None)
    return ProbeResult("uncertain", best.url, dist_out, best.name, "weak_corroboration")
