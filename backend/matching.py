"""Pure scoring core for cross-platform restaurant matching.

No DB access — every function operates on plain values/dicts so the logic is
fully unit-testable on fixtures. DB I/O lives in db.py.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from enum import Enum
from itertools import combinations
from math import radians, sin, cos, asin, sqrt
from urllib.parse import urlparse

from rapidfuzz.distance import JaroWinkler

# --- Tunable thresholds -------------------------------------------------------
HIGH_NAME_SIM = 0.92       # Jaro-Winkler on normalized names
GEO_CONFIRM_M = 75.0       # <= confirms same venue
GEO_VETO_M = 300.0         # > vetoes merge (chain branches)
VENUE_GRADE_SOURCES = {"uber_eats", "direct"}

_ARTICLES = {"le", "la", "les", "l", "au", "aux", "un", "une", "de", "du",
             "des", "the", "a", "el", "il"}

_SUFFIX_RE = re.compile(r"\s+-\s+\S.*$")  # " - Ixelles"


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def _canonical(name: str) -> str:
    """Strip emoji/symbols + location suffix after ' - '."""
    name = name.strip()
    name = re.sub(r"[^ -ɏḀ-ỿ\s\d'\"\-&\(\)\.!,]", "", name).strip()
    name = _SUFFIX_RE.sub("", name).strip()
    return name


def normalize_match_key(name: str) -> str:
    """Aggressive key: canonical -> lower -> strip accents -> keep [a-z0-9] only."""
    c = _strip_accents(_canonical(name)).lower()
    return re.sub(r"[^a-z0-9]", "", c)


def normalize_name(name: str) -> str:
    """Looser normalize for fuzzy ratio: canonical, lower, accent-free, single spaces."""
    c = _strip_accents(_canonical(name)).lower()
    c = re.sub(r"[^a-z0-9\s]", " ", c)
    return re.sub(r"\s+", " ", c).strip()


def significant_first_token(name: str) -> str:
    """First non-article token of the normalized name — used for blocking."""
    for tok in normalize_name(name).split():
        if tok not in _ARTICLES:
            return tok
    toks = normalize_name(name).split()
    return toks[0] if toks else ""


def domain_of(url: str | None) -> str | None:
    """Registrable-ish domain: strip scheme + leading www. None if not a URL."""
    if not url or "." not in url:
        return None
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = (parsed.netloc or "").lower().strip()
    if not host or "." not in host or " " in host:
        return None
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])  # example.co.uk
    return ".".join(parts[-2:]) if len(parts) >= 2 else None


def phone_digits(phone: str | None) -> str | None:
    """Reduce to comparable digits: drop +32 / leading 0 country noise."""
    if not phone:
        return None
    d = re.sub(r"\D", "", phone)
    if not d:
        return None
    if d.startswith("32"):
        d = d[2:]
    d = d.lstrip("0")
    return d or None


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    r = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dp = radians(lat2 - lat1)
    dl = radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return r * 2 * asin(sqrt(a))


def is_venue_grade(r: dict) -> bool:
    """True if the row's lat/lng come from a venue-grade source."""
    return (
        r.get("lat") is not None
        and r.get("lng") is not None
        and r.get("geo_source") in VENUE_GRADE_SOURCES
    )


@dataclass
class MatchFeatures:
    name_sim: float
    website_match: bool
    phone_match: bool
    geo_dist: float | None          # metres; None unless both venue-grade
    cuisine_match: bool

    def to_dict(self) -> dict:
        return asdict(self)


def score_pair(a: dict, b: dict) -> MatchFeatures:
    """Compute per-signal features for a candidate pair (order-independent)."""
    name_sim = JaroWinkler.similarity(normalize_name(a["name"]), normalize_name(b["name"]))

    da, dbm = domain_of(a.get("website")), domain_of(b.get("website"))
    website_match = da is not None and da == dbm

    pa, pb = phone_digits(a.get("phone")), phone_digits(b.get("phone"))
    phone_match = pa is not None and pa == pb

    geo_dist: float | None = None
    if is_venue_grade(a) and is_venue_grade(b):
        geo_dist = haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])

    ca, cb = a.get("cuisine"), b.get("cuisine")
    cuisine_match = bool(ca) and ca == cb

    return MatchFeatures(name_sim, website_match, phone_match, geo_dist, cuisine_match)


class Decision(str, Enum):
    AUTO_MERGE = "auto_merge"
    QUEUE = "queue"
    SEPARATE = "separate"


def decide(f: MatchFeatures) -> Decision:
    """Map features to a decision band.

    Order matters: geo veto first (chain guard), then strong-signal auto-merge,
    then name-only queue, else separate.
    """
    # NOTE: f.cuisine_match is intentionally not used here — it is retained in
    # MatchFeatures purely for audit/debugging in the stored features jsonb.
    if f.geo_dist is not None and f.geo_dist > GEO_VETO_M:
        return Decision.SEPARATE

    if f.name_sim < HIGH_NAME_SIM:
        return Decision.SEPARATE

    confirming = (
        f.website_match
        or f.phone_match
        or (f.geo_dist is not None and f.geo_dist <= GEO_CONFIRM_M)
    )
    if confirming:
        return Decision.AUTO_MERGE

    return Decision.QUEUE


def block_candidates(rows: list[dict]) -> list[tuple[dict, dict]]:
    """Generate candidate pairs cheaply via blocking keys.

    Three blocking keys union'd: significant-first-token of the name, 4-char
    prefix of the normalized match key (catches "Pizza Minute"/"PizzaMinute"),
    and exact website domain. Avoids O(n^2) full comparison; chain branches
    share a name token so they land in the same block and are separated later
    by geo veto.
    """
    by_token: dict[str, list[dict]] = {}
    by_key_prefix: dict[str, list[dict]] = {}
    by_domain: dict[str, list[dict]] = {}
    for r in rows:
        tok = significant_first_token(r["name"])
        if tok:
            by_token.setdefault(tok, []).append(r)
        key = normalize_match_key(r["name"])
        prefix = key[:4] if len(key) >= 4 else key
        if prefix:
            by_key_prefix.setdefault(prefix, []).append(r)
        dom = domain_of(r.get("website"))
        if dom:
            by_domain.setdefault(dom, []).append(r)

    seen: set[tuple] = set()
    pairs: list[tuple[dict, dict]] = []
    for bucket in (*by_token.values(), *by_key_prefix.values(), *by_domain.values()):
        for a, b in combinations(bucket, 2):
            key = tuple(sorted((str(a["id"]), str(b["id"]))))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((a, b))
    return pairs
