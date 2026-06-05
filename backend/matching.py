"""Pure scoring core for cross-platform restaurant matching.

No DB access — every function operates on plain values/dicts so the logic is
fully unit-testable on fixtures. DB I/O lives in db.py.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from enum import Enum
from functools import lru_cache
from itertools import combinations
from math import radians, sin, cos, asin, sqrt
from urllib.parse import urlparse

from rapidfuzz.distance import JaroWinkler

# --- Tunable thresholds -------------------------------------------------------
HIGH_NAME_SIM = 0.92       # Jaro-Winkler on normalized names
NAME_SIM_WEBSITE_AUTO = 0.97  # website-only auto-merge needs near-identical names
GEO_CONFIRM_M = 75.0       # <= confirms same venue
GEO_VETO_M = 300.0         # > vetoes merge (chain branches)
SOFT_GEO_VETO_M = 600.0    # > veto when only one side is venue-grade
MENU_OVERLAP_VETO = 0.03   # < 3% shared items → veto (different menus)
MENU_OVERLAP_CONFIRM = 0.15  # >= 15% shared items → strong confirm
VENUE_GRADE_SOURCES = {"uber_eats", "direct", "deliveroo_venue"}

_ARTICLES = {"le", "la", "les", "l", "au", "aux", "un", "une", "de", "du",
             "des", "the", "a", "el", "il"}

_SUFFIX_RE = re.compile(r"\s+-\s+\S.*$")  # " - Ixelles"

_BRUSSELS_LOCATIONS = {
    # 19 communes
    "anderlecht", "auderghem", "berchem", "etterbeek", "evere", "forest",
    "ganshoren", "ixelles", "elsene", "jette", "koekelberg", "molenbeek",
    "saintgilles", "sintgillis", "saintjosse", "schaerbeek", "schaarbeek",
    "uccle", "ukkel", "watermael", "woluwe", "laeken", "neder", "haren",
    # Major squares / neighbourhoods appearing in Brussels chain names
    "debrouckere", "bourse", "sablon", "flagey", "jourdan", "rogier",
    "schuman", "chatelain", "bascule", "ecuyer", "toison", "midi", "louise",
}


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def _canonical(name: str) -> str:
    """Strip emoji/symbols + location suffix after ' - '."""
    name = name.strip()
    name = re.sub(r"[^ -ɏḀ-ỿ\s\d'\"\-&\(\)\.!,]", "", name).strip()
    name = _SUFFIX_RE.sub("", name).strip()
    # Strip trailing city noise — not a differentiator within Brussels.
    name = re.sub(r"\s+(?:brussels|bruxelles|bxl|bsl)\s*$", "", name, flags=re.IGNORECASE).strip()
    # Strip trailing property labels — same restaurant markets as "Halal/Bio/Vegan"
    # on one platform but not another; these are not branch identifiers.
    name = re.sub(r"\s+(?:halal|bio|vegan|végétalien|casher|kosher)\s*$", "", name, flags=re.IGNORECASE).strip()
    return name


def _normalize_slug(slug: str) -> str:
    """Normalize a URL slug for cross-platform comparison.

    Strips hyphens/underscores, accents, city noise, then keeps [a-z0-9].
    'barbq-brasserie' → 'barbqbrasserie'; 'wok-up-bruxelles' → 'wokup'.
    Returns '' for slugs that collapse to nothing meaningful (< 4 chars).
    """
    s = _strip_accents(slug.lower())
    # Strip city noise embedded in slugs
    s = re.sub(r"[\-_]?(?:brussels|bruxelles|bxl|bsl)[\-_]?", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s if len(s) >= 4 else ""


@lru_cache(maxsize=None)
def normalize_match_key(name: str) -> str:
    """Aggressive key: canonical -> lower -> strip accents -> keep [a-z0-9] only."""
    c = _strip_accents(_canonical(name)).lower()
    return re.sub(r"[^a-z0-9]", "", c)


@lru_cache(maxsize=None)
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


@lru_cache(maxsize=None)
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


@lru_cache(maxsize=None)
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


def _location_tokens(raw_name: str, slugs: list[str] | None = None) -> set[str]:
    """Extract Brussels commune tokens from raw (uncanonical) name and optional slugs."""
    key = re.sub(r"[^a-z]", "", _strip_accents(raw_name).lower())
    tokens = {loc for loc in _BRUSSELS_LOCATIONS if loc in key}
    for slug in (slugs or []):
        slug_key = re.sub(r"[^a-z]", "", _strip_accents(slug).lower())
        tokens |= {loc for loc in _BRUSSELS_LOCATIONS if loc in slug_key}
    return tokens


def _cuisine_conflict(ca: str | None, cb: str | None) -> bool:
    """True if both cuisines are set AND they do not match (case-insensitive, accent-stripped).

    'Match' means equal OR one is a substring of the other. This tolerates
    "Asian" vs "Japanese" not being treated as a conflict (substring check
    handles hierarchical cuisine labels).
    """
    if not ca or not cb:
        return False
    na = re.sub(r"[^a-z0-9]", "", _strip_accents(ca).lower())
    nb = re.sub(r"[^a-z0-9]", "", _strip_accents(cb).lower())
    if na == nb:
        return False
    if na in nb or nb in na:
        return False
    return True


@dataclass
class MatchFeatures:
    name_sim: float
    website_match: bool
    phone_match: bool
    geo_dist: float | None          # metres; None unless both venue-grade
    cuisine_match: bool
    cuisine_conflict: bool          # both set and cuisines don't match
    location_conflict: bool         # commune tokens are disjoint
    menu_overlap: float | None      # Jaccard overlap; None if either side < 3 items
    soft_geo_dist: float | None     # metres; one venue-grade + one has any coords
    is_chain_name: bool             # normalized name appears 3+ times in corpus
    slug_match: bool                # normalized URL slug shared across platforms

    def to_dict(self) -> dict:
        return asdict(self)


def score_pair(
    a: dict,
    b: dict,
    *,
    menus: dict[str, set[str]] | None = None,
    chain_names: set[str] | None = None,
    slugs: dict[str, list[str]] | None = None,
) -> MatchFeatures:
    """Compute per-signal features for a candidate pair (order-independent)."""
    name_sim = JaroWinkler.similarity(normalize_name(a["name"]), normalize_name(b["name"]))

    da, dbm = domain_of(a.get("website")), domain_of(b.get("website"))
    website_match = da is not None and da == dbm

    pa, pb = phone_digits(a.get("phone")), phone_digits(b.get("phone"))
    phone_match = pa is not None and pa == pb

    # Venue-grade geo (both sides must be venue-grade)
    geo_dist: float | None = None
    if is_venue_grade(a) and is_venue_grade(b):
        geo_dist = haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])

    # Soft geo (one venue-grade + other has any coords)
    soft_geo_dist: float | None = None
    if geo_dist is None:
        a_has_coords = a.get("lat") is not None and a.get("lng") is not None
        b_has_coords = b.get("lat") is not None and b.get("lng") is not None
        if a_has_coords and b_has_coords:
            dist = haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
            soft_geo_dist = dist

    ca, cb = a.get("cuisine"), b.get("cuisine")
    cuisine_match = bool(ca) and ca == cb
    cuisine_conflict = _cuisine_conflict(ca, cb)

    # Location tokens — use raw name (before _canonical strips suffix)
    a_slugs = slugs.get(str(a["id"]), []) if slugs else []
    b_slugs = slugs.get(str(b["id"]), []) if slugs else []
    a_locs = _location_tokens(a["name"], a_slugs)
    b_locs = _location_tokens(b["name"], b_slugs)
    # Numbered branches: "Name 1" vs "Name 2" → distinct locations
    _an = re.search(r"\b(\d+)\s*$", a["name"].strip())
    _bn = re.search(r"\b(\d+)\s*$", b["name"].strip())
    numbered_branches = _an is not None and _bn is not None and _an.group(1) != _bn.group(1)
    location_conflict = numbered_branches or bool(a_locs and b_locs and a_locs.isdisjoint(b_locs))

    # Menu item overlap (Jaccard)
    ma = menus.get(str(a["id"]), set()) if menus else set()
    mb = menus.get(str(b["id"]), set()) if menus else set()
    menu_overlap: float | None = None
    if len(ma) >= 3 and len(mb) >= 3:
        intersection = len(ma & mb)
        union = len(ma | mb)
        menu_overlap = intersection / union if union > 0 else 0.0

    # Chain guard — use significant_first_token so "McDonald's Bascule" and
    # "McDonald's Bourse" both map to "mcdonalds", hitting the chain threshold.
    is_chain_name = (
        significant_first_token(a["name"]) in (chain_names or set())
        or significant_first_token(b["name"]) in (chain_names or set())
    )

    # URL slug match — shared normalized slug across different platforms means
    # the same restaurant slug was registered on both (e.g. "barbq-brasserie"
    # on Deliveroo and Takeaway, or "wokup" on UberEats and Deliveroo).
    a_slug_keys: set[str] = set()
    b_slug_keys: set[str] = set()
    for raw_slug in (slugs.get(str(a["id"]), []) if slugs else []):
        key = _normalize_slug(raw_slug)
        if key:
            a_slug_keys.add(key)
    for raw_slug in (slugs.get(str(b["id"]), []) if slugs else []):
        key = _normalize_slug(raw_slug)
        if key:
            b_slug_keys.add(key)
    slug_match = bool(a_slug_keys and b_slug_keys and a_slug_keys & b_slug_keys)

    return MatchFeatures(
        name_sim=name_sim,
        website_match=website_match,
        phone_match=phone_match,
        geo_dist=geo_dist,
        cuisine_match=cuisine_match,
        cuisine_conflict=cuisine_conflict,
        location_conflict=location_conflict,
        menu_overlap=menu_overlap,
        soft_geo_dist=soft_geo_dist,
        is_chain_name=is_chain_name,
        slug_match=slug_match,
    )


class Decision(str, Enum):
    AUTO_MERGE = "auto_merge"
    QUEUE = "queue"
    SEPARATE = "separate"


def decide(f: MatchFeatures) -> Decision:
    """Map features to a decision band.

    Order matters: geo vetos first (strongest physical evidence), then semantic
    vetos, then name threshold, then menu veto, then strong-signal auto-merge,
    then chain guard, else queue.
    """
    # Geo vetos (strongest physical evidence)
    if f.geo_dist is not None and f.geo_dist > GEO_VETO_M:
        return Decision.SEPARATE
    if f.soft_geo_dist is not None and f.soft_geo_dist > SOFT_GEO_VETO_M:
        return Decision.SEPARATE

    # Semantic vetos
    if f.location_conflict:
        return Decision.SEPARATE
    if f.cuisine_conflict:
        return Decision.SEPARATE

    # Name threshold
    if f.name_sim < HIGH_NAME_SIM:
        return Decision.SEPARATE

    # Menu veto (after name threshold so low-sim pairs don't reach here)
    if f.menu_overlap is not None and f.menu_overlap < MENU_OVERLAP_VETO:
        return Decision.SEPARATE

    # Near-identical names with no conflicting signals → same venue.
    # At ≥ 0.97 the only realistic source of divergence is punctuation/spacing
    # ("Mr Cod" / "Mr. Cod", "AlloCouscous" / "Allo Couscous"). All vetos have
    # already fired by this point so there's nothing contradicting the merge.
    if f.name_sim >= NAME_SIM_WEBSITE_AUTO and not f.is_chain_name:
        return Decision.AUTO_MERGE

    # Strong confirmation = same physical place. Phone and close geo prove it.
    # A shared website does NOT by itself — Belgian chains run every branch off
    # one corporate domain, so "Late Night Pizza Ixelles" and "...Saint-Gilles"
    # share a domain yet are distinct venues. Website only auto-confirms when the
    # names are near-identical (no distinguishing location suffix); otherwise the
    # pair goes to human review.
    strong_confirm = (
        f.phone_match
        or (f.geo_dist is not None and f.geo_dist <= GEO_CONFIRM_M)
        or (f.website_match and f.name_sim >= NAME_SIM_WEBSITE_AUTO)
        or (f.menu_overlap is not None and f.menu_overlap >= MENU_OVERLAP_CONFIRM)
        or f.slug_match  # same URL slug on different platforms = same venue
    )

    # Chain guard: don't auto-merge or queue chain branches without evidence
    if f.is_chain_name and not strong_confirm:
        return Decision.SEPARATE

    if strong_confirm:
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
