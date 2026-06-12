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
DISTINCTIVE_REMAINDER_MIN = 0.84  # remainder JW below this → distinct venues
VENUE_GRADE_SOURCES = {"uber_eats", "direct", "deliveroo_venue", "takeaway"}

# --- Additive evidence model --------------------------------------------------
HARD_GEO_SEPARATE_M = 1000.0   # both venue-grade coords > 1 km apart → always SEPARATE
AUTO_BAND  = 4.5    # total >= AUTO_BAND → AUTO_MERGE (+ hard proof + identity)
QUEUE_BAND = 1.5    # total >= QUEUE_BAND → QUEUE
IDENTITY_AUTO_NAME_SIM = 0.80  # AUTO needs name agreement OR slug — see ghost-kitchen guard
COLOCATION_GATE_NAME_SIM = 0.80  # geo/address count only above this name floor (or phone/slug/addr)

WEIGHTS: dict[str, float] = {
    "name_very_high":  2.0,   # name_sim >= 0.97
    "name_high":       1.0,   # name_sim >= 0.92
    "website":         1.0,
    "phone":           3.0,
    "geo_very_close":  3.0,   # <= 25 m  (100 m deliveroo)
    "geo_close":       2.0,   # <= 75 m  (200 m deliveroo)
    "geo_near":        1.0,   # <= 200 m (500 m deliveroo)
    "menu_overlap":    1.0,
    "address_same":    2.5,
    "address_diff":   -3.0,
    "cuisine_match":   0.5,
    "cuisine_conflict":-2.0,
    "location_conflict":-3.0,
    "distinctive_conflict": -2.0,
    "slug_match":      2.0,
}

_ARTICLES = {"le", "la", "les", "l", "au", "aux", "un", "une", "de", "du",
             "des", "the", "a", "el", "il"}

# Generic cuisine/shop-type words. These are NOT brand tokens: dozens of
# independent "Pizza X" / "Snack Y" places share them, so they must never feed
# the chain-name count heuristic (else every pizzeria gets flagged is_chain).
# A real chain shares a brand first token ("quick", "panos", "carrefour").
_GENERIC_TOKENS = {
    "pizza", "pizzeria", "pizzas", "snack", "snacks", "sushi", "sushibar",
    "burger", "burgers", "pasta", "pastas", "tacos", "taco", "kebab", "durum",
    "pita", "friterie", "frituur", "pizzerie", "wok", "thai", "chinese",
    "indian", "grill", "grills", "bbq", "chicken", "poke", "bagel", "bagels",
    "sandwich", "sandwiches", "resto", "restaurant", "brasserie", "bistro",
    "cafe", "coffee", "boulangerie", "patisserie", "librairie", "night",
    "late", "food", "chez", "maison", "new", "royal", "star", "king", "house",
    "express", "city", "shop", "market", "supermarket", "traiteur", "noodle",
    "noodles", "ramen", "curry", "tandoori", "doner", "donut", "donuts",
    "waffle", "waffles", "gelato", "glacier", "creperie", "crepe",
}

_SUFFIX_RE = re.compile(r"\s+-\s+\S.*$")  # " - Ixelles"
_STREET_PREFIX_RE = re.compile(
    r"^(?:rue|avenue|av|boulevard|bvd|bd|chaussee|ch[eé]e|dr[eè]ve|place|pl|square|sq|"
    r"clos|impasse|all[eé]e|quai|passage|sentier|chemin|ch|dreve|ruelle|voie|cit[eé])\s+",
    re.IGNORECASE,
)

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


@lru_cache(maxsize=2048)
def normalize_match_key(name: str) -> str:
    """Aggressive key: canonical -> lower -> strip accents -> keep [a-z0-9] only."""
    c = _strip_accents(_canonical(name)).lower()
    return re.sub(r"[^a-z0-9]", "", c)


@lru_cache(maxsize=2048)
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


def _distinctive_tokens(name: str) -> set[str]:
    """Brand-distinctive tokens of a name: len >= 4, not generic, not a commune.

    'Pizzeria Trattoria Ai 6 angoli' → {'angoli', 'trattoria'... } minus generics
    → {'angoli'}. Used by the co-location gate: two co-located listings that
    share a distinctive token ('angoli') are plausibly the same venue even when
    full-string name similarity is dragged down by prefixes/suffixes, whereas
    pure neighbours ('Taste of Himalayan' / 'Pasta Commedia') share none.
    """
    out: set[str] = set()
    for tok in normalize_name(name).split():
        if (len(tok) >= 4 and tok not in _GENERIC_TOKENS
                and tok not in _ARTICLES and tok not in _BRUSSELS_LOCATIONS):
            out.add(tok)
    return out


def shares_distinctive_token(a_name: str, b_name: str) -> bool:
    """True if two names share at least one brand-distinctive token."""
    return bool(_distinctive_tokens(a_name) & _distinctive_tokens(b_name))


def _distinctive_remainder(name: str) -> tuple[str, bool]:
    """Strip leading generic/article tokens; return (remainder, had_generic_prefix).

    'Pizza Vito' → ('vito', True); 'Snack Tarik' → ('tarik', True);
    'Quick' → ('quick', False). Used to compare the distinguishing part of two
    names that share a generic prefix ("Pizza X" vs "Pizza Y").
    """
    toks = normalize_name(name).split()
    had_generic = False
    i = 0
    while i < len(toks) and (toks[i] in _GENERIC_TOKENS or toks[i] in _ARTICLES):
        if toks[i] in _GENERIC_TOKENS:
            had_generic = True
        i += 1
    return " ".join(toks[i:]), had_generic


@lru_cache(maxsize=2048)
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


@lru_cache(maxsize=2048)
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


def _normalize_address(addr: str | None) -> str:
    """Lowercase, strip accents, strip common street prefixes, keep [a-z0-9] only."""
    if not addr:
        return ""
    s = _strip_accents(addr.strip().lower())
    s = _STREET_PREFIX_RE.sub("", s)
    return re.sub(r"[^a-z0-9]", "", s)


_HOUSE_NUM_LEAD_RE = re.compile(r"^\s*(\d+)\s*[a-zA-Z]?\b")
_HOUSE_NUM_TRAIL_RE = re.compile(r"\b(\d+)\s*[a-zA-Z]?\s*$")


def _house_number(addr: str | None) -> str | None:
    """Extract the house number from a raw street address.

    Brussels addresses put the number either before ("135 Chaussée de Haecht")
    or after ("Chaussée de Haecht 135") the street. We try the trailing form
    first (the common NL/FR layout), then the leading form. A trailing letter
    box suffix ("46B") is dropped so "46B" and "46" compare equal.
    """
    if not addr:
        return None
    s = addr.strip()
    m = _HOUSE_NUM_TRAIL_RE.search(s)
    if m:
        return m.group(1)
    m = _HOUSE_NUM_LEAD_RE.search(s)
    if m:
        return m.group(1)
    return None


def _match_address(a: dict, b: dict) -> bool | None:
    """Compare address signals. True=confirmed same, False=conflict, None=insufficient data.

    A raw string mismatch is NOT enough to declare a conflict: Brussels streets
    are bilingual (FR "Chaussée de Gand" == NL "Gentsesteenweg") and the house
    number floats to either end of the string. So when the normalized blobs
    differ we only return False (the hard -3.0 veto) if the *house numbers*
    differ; equal-or-missing numbers fall through to None and let geo/name
    decide, since the street tokens alone can't disprove the same address.
    """
    pca = (a.get("postal_code") or "").strip()
    pcb = (b.get("postal_code") or "").strip()
    if not pca or not pcb:
        return None
    if pca != pcb:
        # Bilingual boundary streets (e.g. NL "Gulden-Vlieslaan" == FR "Avenue
        # de la Toison d'Or") straddle two communes, so platforms record
        # different postal codes for one physical address. A matching house
        # number signals a boundary artifact rather than two branches → drop to
        # None (insufficient) instead of a hard veto; differing numbers stay a
        # genuine conflict.
        na = _house_number(a.get("street_address"))
        nb = _house_number(b.get("street_address"))
        if na is not None and nb is not None and na == nb:
            return None
        return False
    sa = _normalize_address(a.get("street_address"))
    sb = _normalize_address(b.get("street_address"))
    if not sa or not sb:
        return None  # postal codes match but no streets to confirm or deny
    if sa == sb:
        return True
    if len(sa) >= 4 and len(sb) >= 4:
        na = _house_number(a.get("street_address"))
        nb = _house_number(b.get("street_address"))
        if na is not None and nb is not None and na != nb:
            return False  # same postal, different house number → distinct address
        return None  # bilingual/word-order variant of the same street; geo decides
    return None


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
    distinctive_conflict: bool      # shared generic prefix but distinct remainder
    address_match: bool | None      # postal+street match; None if data missing
    deliveroo_geo: bool = False     # True when one side uses Deliveroo zone centroid
    name_variant: str = "plain"     # "plain" | "abbrev" | "location_suffix"
    shares_token: bool = False      # names share a brand-distinctive token

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
    # Deliveroo coords are zone centroids, not venue points → widen geo bands.
    deliveroo_geo = a.get("geo_source") == "deliveroo_venue" or b.get("geo_source") == "deliveroo_venue"

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

    # Chain guard — two sources, OR'd:
    #  1. Persisted restaurants.is_chain flag (authoritative; admin/scraper set).
    #  2. Count heuristic via significant_first_token so "McDonald's Bascule" and
    #     "McDonald's Bourse" both map to "mcdonalds", hitting the chain threshold.
    # The flag catches chains with < 3 scraped branches the count would miss.
    is_chain_name = (
        bool(a.get("is_chain"))
        or bool(b.get("is_chain"))
        or significant_first_token(a["name"]) in (chain_names or set())
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

    # Distinctive-remainder veto. JaroWinkler over-weights a shared prefix, so
    # "Pizza Vito"/"Pizza Mio" and "Snack Tetik"/"Snack Tarik" score high despite
    # being different venues. When both names share a generic prefix, compare the
    # remainder: a low remainder similarity means the distinguishing word differs.
    a_rem, a_gen = _distinctive_remainder(a["name"])
    b_rem, b_gen = _distinctive_remainder(b["name"])
    distinctive_conflict = (
        a_gen and b_gen and bool(a_rem) and bool(b_rem)
        and JaroWinkler.similarity(a_rem, b_rem) < DISTINCTIVE_REMAINDER_MIN
    )

    address_match = _match_address(a, b)
    shares_token = shares_distinctive_token(a["name"], b["name"])

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
        distinctive_conflict=distinctive_conflict,
        address_match=address_match,
        deliveroo_geo=deliveroo_geo,
        shares_token=shares_token,
    )


class Decision(str, Enum):
    AUTO_MERGE = "auto_merge"
    QUEUE = "queue"
    SEPARATE = "separate"


def geo_band(geo_dist: float | None, deliveroo_geo: bool) -> str | None:
    """Map distance to a named band.

    Deliveroo coords are zone centroids, not venue coords → wider bands.
    Returns None when geo_dist is None.
    """
    if geo_dist is None:
        return None
    if deliveroo_geo:
        if geo_dist <= 100:   return "very_close"
        if geo_dist <= 300:   return "close"
        if geo_dist <= 700:   return "near"
        if geo_dist <= 1500:  return "far"
        return "very_far"
    else:
        if geo_dist <= 25:    return "very_close"
        if geo_dist <= 75:    return "close"
        if geo_dist <= 200:   return "near"
        if geo_dist <= 500:   return "far"
        return "very_far"


def evidence_score(f: MatchFeatures) -> tuple[float, dict[str, float]]:
    """Additive evidence model: sum weighted signals, return (total, breakdown)."""
    W = WEIGHTS
    breakdown: dict[str, float] = {}

    def add(key: str, val: float) -> None:
        breakdown[key] = val

    # Name similarity
    if f.name_sim >= 0.97:
        add("name_very_high", W["name_very_high"])
    elif f.name_sim >= HIGH_NAME_SIM:
        add("name_high", W["name_high"])

    if f.website_match:
        add("website", W["website"])
    if f.phone_match:
        add("phone", W["phone"])
    if f.slug_match:
        add("slug_match", W["slug_match"])

    # Co-location gate: physical proximity (geo) only counts FOR a merge when
    # there is identity evidence. Brussels streets pack distinct restaurants
    # metres apart (food courts, shared buildings) and JaroWinkler hands
    # unrelated short names a coincidental 0.5–0.7, so a low name floor would
    # flood the queue with neighbours. The gate opens on:
    #   - a real name match (>= COLOCATION_GATE_NAME_SIM; genuine same-venue
    #     pairs score >= 0.89 even after suffix-stripping), OR
    #   - a shared phone or slug, OR
    #   - an exact street+number address match.
    # Phone/address openers are what keep ghost kitchens (shared phone+address,
    # different name) in the QUEUE for review rather than silently dropped.
    identity = (
        f.name_sim >= COLOCATION_GATE_NAME_SIM
        or f.shares_token
        or f.phone_match
        or f.slug_match
        or f.address_match is True
    )

    # Geo signal via geo_band — positive bands gated; negative bands are a
    # hard veto handled in decide(), so they need no contribution here.
    band = geo_band(f.geo_dist, f.deliveroo_geo)
    if identity:
        if band == "very_close":
            add("geo_very_close", W["geo_very_close"])
        elif band == "close":
            add("geo_close", W["geo_close"])
        elif band == "near":
            add("geo_near", W["geo_near"])

    # Menu overlap
    if f.menu_overlap is not None and f.menu_overlap >= MENU_OVERLAP_CONFIRM:
        add("menu_overlap", W["menu_overlap"])

    # Address — positive match gated by identity (same co-location reasoning);
    # a conflict is unconditional negative evidence.
    if f.address_match is True and identity:
        add("address_same", W["address_same"])
    elif f.address_match is False:
        add("address_diff", W["address_diff"])

    # Cuisine
    if f.cuisine_match:
        add("cuisine_match", W["cuisine_match"])
    if f.cuisine_conflict:
        add("cuisine_conflict", W["cuisine_conflict"])

    # Conflict signals
    if f.location_conflict:
        add("location_conflict", W["location_conflict"])
    if f.distinctive_conflict:
        add("distinctive_conflict", W["distinctive_conflict"])

    total = sum(breakdown.values())
    return total, breakdown


def decide(f: MatchFeatures) -> Decision:
    """Map evidence total to a decision band.

    One hard rule first: both-venue-grade precise (non-deliveroo) coords more
    than 1 km apart with no phone match can never merge — chain branches share
    name/menu/website and additive evidence must not pile past the bands.

    AUTO_MERGE additionally requires BOTH:
      1. a hard physical proof — phone_match, slug_match, address_match is
         True, or geo band == "very_close"; AND
      2. identity agreement — name_sim >= IDENTITY_AUTO_NAME_SIM OR slug_match.

    The identity gate guards against Brussels cloud/ghost kitchens: several
    distinct virtual brands ("Wok & Go" + "China Wok") run from ONE kitchen,
    sharing a single phone and address. Physical proof alone would silently
    merge them; requiring name/slug agreement sends co-located different-name
    pairs to QUEUE for human review instead. Weak positives can pile past
    AUTO_BAND, so without proof OR without identity the pair queues.
    """
    if (f.geo_dist is not None and not f.deliveroo_geo
            and f.geo_dist > HARD_GEO_SEPARATE_M and not f.phone_match):
        return Decision.SEPARATE
    total, _ = evidence_score(f)
    if total >= AUTO_BAND:
        proof = (f.phone_match or f.slug_match or f.address_match is True
                 or geo_band(f.geo_dist, f.deliveroo_geo) == "very_close")
        identity = f.name_sim >= IDENTITY_AUTO_NAME_SIM or f.slug_match
        return Decision.AUTO_MERGE if (proof and identity) else Decision.QUEUE
    if total >= QUEUE_BAND:
        return Decision.QUEUE
    return Decision.SEPARATE


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

    # Geo grid blocking: ~150m cells. Every restaurant lands in its cell; pairs
    # are drawn within a cell and its 8 neighbours, then distance-filtered. All
    # rows now carry venue-grade coords, so this catches duplicates whose names
    # share no token (e.g. "Pasta Express Etterbeek" / "PASTA EXPRESS").
    GEO_BLOCK_M = 150.0
    cell_deg = 0.0015  # ~167m latitude per cell at Brussels' 50.8°N
    by_cell: dict[tuple[int, int], list[dict]] = {}
    for r in rows:
        if r.get("lat") is None or r.get("lng") is None:
            continue
        by_cell.setdefault((int(r["lat"] / cell_deg), int(r["lng"] / cell_deg)), []).append(r)

    geo_pairs: list[tuple[dict, dict]] = []
    for (cx, cy), bucket in by_cell.items():
        neighbourhood: list[dict] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbourhood.extend(by_cell.get((cx + dx, cy + dy), []))
        for a in bucket:
            for b in neighbourhood:
                if str(a["id"]) >= str(b["id"]):
                    continue
                if haversine_m(a["lat"], a["lng"], b["lat"], b["lng"]) <= GEO_BLOCK_M:
                    geo_pairs.append((a, b))

    seen: set[tuple] = set()
    pairs: list[tuple[dict, dict]] = []
    for bucket in (*by_token.values(), *by_key_prefix.values(), *by_domain.values()):
        for a, b in combinations(bucket, 2):
            key = tuple(sorted((str(a["id"]), str(b["id"]))))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((a, b))
    for a, b in geo_pairs:
        key = tuple(sorted((str(a["id"]), str(b["id"]))))
        if key in seen:
            continue
        seen.add(key)
        pairs.append((a, b))
    return pairs
