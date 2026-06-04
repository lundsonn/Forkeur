# Geo + Website Scored Restaurant Matcher — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace name-only cross-platform restaurant matching with a scored matcher using name similarity + website domain + phone + venue-grade geo, auto-merging on strong signal and queuing uncertain pairs for human review.

**Architecture:** Pure scoring core in `backend/matching.py` (no DB, fixture-testable). DB I/O isolated in `db.py`. Inline `upsert_restaurant` keeps only deterministic locks (exact-normalized name, exact website domain). A re-runnable batch job (`backend/scrapers/match.py`) does fuzzy/geo scoring, writes auto-merges + a `restaurant_match_decisions` queue/log table, and supports `dry_run`. Dashboard exposes the review queue.

**Tech Stack:** Python 3.12, `uv`, `rapidfuzz` (Jaro-Winkler), Supabase (python client), pytest, FastAPI router + APScheduler, React/Vite admin dashboard.

**Spec:** `docs/superpowers/specs/2026-06-04-restaurant-matcher-design.md`

---

## File map

| File | Responsibility | Action |
|------|----------------|--------|
| `supabase/migrations/012_restaurant_matching.sql` | `restaurant_match_decisions` table + `restaurants.geo_source` column | Create |
| `backend/pyproject.toml` | add `rapidfuzz` dep | Modify |
| `backend/matching.py` | pure: normalize, keys, domain, phone, haversine, score, decide, block | Create |
| `backend/db.py` | candidate load, enqueue, merge, queue getters/resolvers; tighten `upsert_restaurant` | Modify |
| `backend/scrapers/match.py` | batch job `run(config, log_fn, *, dry_run)` | Create |
| `backend/routers/scrapers.py` | register `match` in `SCRAPERS` | Modify |
| `backend/scrapers/{ubereats,deliveroo,direct}.py` | pass `geo_source` on upsert | Modify |
| `backend/scheduler.py` | run match after fee refresh in batch | Modify |
| `backend/routers/data.py` | queue list + resolve endpoints | Modify |
| `backend/dashboard/src/` | review-queue panel | Modify |
| `backend/tests/test_matching.py` | scoring/decision/block unit tests | Create |
| `backend/tests/test_matching_db.py` | merge/enqueue/upsert-lock tests (mocked) | Create |

**Threshold constants** (defined once in `matching.py`, tunable):
- `HIGH_NAME_SIM = 0.92` — Jaro-Winkler on normalized names
- `GEO_CONFIRM_M = 75.0` — ≤ this distance confirms same venue
- `GEO_VETO_M = 300.0` — > this distance vetoes merge (chain branches)
- `VENUE_GRADE_SOURCES = {"uber_eats", "direct"}` — platforms with true venue coords

---

## Task 1: Migration + dependency

**Files:**
- Create: `supabase/migrations/012_restaurant_matching.sql`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Write the migration SQL**

Create `supabase/migrations/012_restaurant_matching.sql`:

```sql
-- Geo + website scored restaurant matcher.
-- 1) geo_source: which platform set restaurants.lat/lng, so the matcher can
--    distinguish venue-grade coords (uber_eats/direct) from Deliveroo's
--    delivery-zone centroid (geohash) and Takeaway (none).
alter table restaurants
  add column if not exists geo_source text;

-- 2) restaurant_match_decisions: doubles as review queue + audit log.
create table if not exists restaurant_match_decisions (
  id           uuid primary key default gen_random_uuid(),
  survivor_id  uuid references restaurants(id) on delete cascade,
  loser_id     uuid references restaurants(id) on delete set null,
  score        numeric,
  features     jsonb,
  status       text not null,  -- auto_merged | queued | approved | rejected | separated
  created_at   timestamptz default now(),
  resolved_at  timestamptz,
  resolved_by  text
);

-- Prevent re-queuing the same unordered pair repeatedly.
create unique index if not exists uq_match_pair
  on restaurant_match_decisions (
    least(survivor_id, loser_id),
    greatest(survivor_id, loser_id)
  );

create index if not exists idx_match_status
  on restaurant_match_decisions (status);

-- RLS on, no anon write policy (service_role bypasses RLS) — per project convention.
alter table restaurant_match_decisions enable row level security;
```

- [ ] **Step 2: Apply the migration**

Apply via Supabase MCP `apply_migration` with name `restaurant_matching` and the SQL body above (project `ltpicouyzdmamblzwcgc`).

Then verify:
```bash
# via MCP execute_sql
select column_name from information_schema.columns
where table_name='restaurants' and column_name='geo_source';
select to_regclass('public.restaurant_match_decisions');
```
Expected: one row `geo_source`; `restaurant_match_decisions` not null.

- [ ] **Step 3: Add rapidfuzz dependency**

Run from `backend/`:
```bash
cd backend && uv add rapidfuzz
```
Expected: `pyproject.toml` gains `rapidfuzz>=...` under `dependencies`, lockfile updated.

- [ ] **Step 4: Verify import**

Run:
```bash
cd backend && uv run python -c "from rapidfuzz.distance import JaroWinkler; print(JaroWinkler.similarity('pizza minute','pizzaminute'))"
```
Expected: prints a float between 0 and 1 (no ImportError).

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/012_restaurant_matching.sql backend/pyproject.toml backend/uv.lock
git commit -m "feat(matcher): add match-decisions table, geo_source column, rapidfuzz dep"
```

---

## Task 2: matching.py — normalization & key helpers

**Files:**
- Create: `backend/matching.py`
- Test: `backend/tests/test_matching.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_matching.py`:

```python
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd backend && uv run pytest tests/test_matching.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'matching'`.

- [ ] **Step 3: Implement helpers**

Create `backend/matching.py`:

```python
"""Pure scoring core for cross-platform restaurant matching.

No DB access — every function operates on plain values/dicts so the logic is
fully unit-testable on fixtures. DB I/O lives in db.py.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
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
    """Aggressive key: canonical → lower → strip accents → keep [a-z0-9] only.

    'Pizza minute', 'PizzaMinute', 'Mr. Cod' all collapse to a comparable key.
    """
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
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd backend && uv run pytest tests/test_matching.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/matching.py backend/tests/test_matching.py
git commit -m "feat(matcher): normalization, domain, phone helpers"
```

---

## Task 3: matching.py — haversine + venue-grade geo

**Files:**
- Modify: `backend/matching.py`
- Test: `backend/tests/test_matching.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_matching.py`:

```python
def test_haversine_known_distance():
    # Grand-Place Brussels → Manneken Pis ≈ 380 m
    d = matching.haversine_m(50.8467, 4.3525, 50.8450, 4.3499)
    assert 300 < d < 460


def test_haversine_same_point_zero():
    assert matching.haversine_m(50.85, 4.35, 50.85, 4.35) == 0.0


def test_is_venue_grade():
    assert matching.is_venue_grade({"lat": 50.8, "lng": 4.3, "geo_source": "uber_eats"})
    assert matching.is_venue_grade({"lat": 50.8, "lng": 4.3, "geo_source": "direct"})
    assert not matching.is_venue_grade({"lat": 50.8, "lng": 4.3, "geo_source": "deliveroo"})
    assert not matching.is_venue_grade({"lat": 50.8, "lng": 4.3, "geo_source": None})
    assert not matching.is_venue_grade({"lat": None, "lng": None, "geo_source": "uber_eats"})
```

- [ ] **Step 2: Run, verify fail**

Run: `cd backend && uv run pytest tests/test_matching.py -k "haversine or venue_grade" -v`
Expected: FAIL — `AttributeError: module 'matching' has no attribute 'haversine_m'`.

- [ ] **Step 3: Implement**

Append to `backend/matching.py`:

```python
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
```

- [ ] **Step 4: Run, verify pass**

Run: `cd backend && uv run pytest tests/test_matching.py -v`
Expected: all passed (8 total).

- [ ] **Step 5: Commit**

```bash
git add backend/matching.py backend/tests/test_matching.py
git commit -m "feat(matcher): haversine distance + venue-grade geo check"
```

---

## Task 4: matching.py — MatchFeatures + score_pair

**Files:**
- Modify: `backend/matching.py`
- Test: `backend/tests/test_matching.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_matching.py`:

```python
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
    b = _r("Foo", lat=50.8450, lng=4.3499, geo_source="direct")
    f = matching.score_pair(a, b)
    assert f.geo_dist is not None and 300 < f.geo_dist < 460
    # Deliveroo zone coords must NOT produce a distance.
    b2 = _r("Foo", lat=50.8450, lng=4.3499, geo_source="deliveroo")
    assert matching.score_pair(a, b2).geo_dist is None


def test_score_pair_phone_match():
    f = matching.score_pair(
        _r("Foo", phone="+32 2 123 45 67"),
        _r("Foo", phone="02 123 45 67"),
    )
    assert f.phone_match is True
```

- [ ] **Step 2: Run, verify fail**

Run: `cd backend && uv run pytest tests/test_matching.py -k score_pair -v`
Expected: FAIL — `AttributeError: ... 'score_pair'`.

- [ ] **Step 3: Implement**

Append to `backend/matching.py`:

```python
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
```

- [ ] **Step 4: Run, verify pass**

Run: `cd backend && uv run pytest tests/test_matching.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/matching.py backend/tests/test_matching.py
git commit -m "feat(matcher): MatchFeatures + score_pair signal extraction"
```

---

## Task 5: matching.py — Decision + decide()

**Files:**
- Modify: `backend/matching.py`
- Test: `backend/tests/test_matching.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_matching.py`:

```python
def test_decide_strong_signal_auto_merges():
    # high name + website confirm
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
    # geo veto wins over website (two branches sharing a chain domain).
    f = matching.MatchFeatures(name_sim=0.95, website_match=True,
                               phone_match=False, geo_dist=1200.0, cuisine_match=False)
    assert matching.decide(f) == matching.Decision.SEPARATE
```

- [ ] **Step 2: Run, verify fail**

Run: `cd backend && uv run pytest tests/test_matching.py -k decide -v`
Expected: FAIL — `AttributeError: ... 'Decision'`.

- [ ] **Step 3: Implement**

Append to `backend/matching.py`:

```python
from enum import Enum


class Decision(str, Enum):
    AUTO_MERGE = "auto_merge"
    QUEUE = "queue"
    SEPARATE = "separate"


def decide(f: MatchFeatures) -> Decision:
    """Map features to a decision band.

    Order matters: geo veto first (chain guard), then strong-signal auto-merge,
    then name-only queue, else separate.
    """
    # Chain guard — venue-grade coords far apart means different branches.
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

    # High name similarity but nothing to confirm it's the same venue (could be
    # an ungeolocated chain branch) → human review.
    return Decision.QUEUE
```

- [ ] **Step 4: Run, verify pass**

Run: `cd backend && uv run pytest tests/test_matching.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/matching.py backend/tests/test_matching.py
git commit -m "feat(matcher): Decision bands with chain-branch geo veto"
```

---

## Task 6: matching.py — block_candidates

**Files:**
- Modify: `backend/matching.py`
- Test: `backend/tests/test_matching.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_matching.py`:

```python
def test_block_candidates_groups_by_first_token_and_domain():
    rows = [
        _r("Pizza Minute", id="1"),
        _r("PizzaMinute", id="2"),
        _r("Burger King - Ixelles", id="3"),
        _r("Sushi Shop", id="4", website="https://sushishop.be"),
        _r("Sushi Express", id="5", website="http://sushishop.be"),  # same domain, diff name
    ]
    pairs = matching.block_candidates(rows)
    ids = {tuple(sorted((a["id"], b["id"]))) for a, b in pairs}
    assert ("1", "2") in ids          # same first token "pizza"
    assert ("4", "5") in ids          # same website domain
    assert ("1", "3") not in ids      # different first token, no shared domain


def test_block_candidates_no_self_pairs():
    rows = [_r("Foo", id="1")]
    assert matching.block_candidates(rows) == []
```

- [ ] **Step 2: Run, verify fail**

Run: `cd backend && uv run pytest tests/test_matching.py -k block -v`
Expected: FAIL — `AttributeError: ... 'block_candidates'`.

- [ ] **Step 3: Implement**

Append to `backend/matching.py`:

```python
from itertools import combinations


def block_candidates(rows: list[dict]) -> list[tuple[dict, dict]]:
    """Generate candidate pairs cheaply via blocking keys.

    Two blocking keys union'd: significant-first-token of the name, and exact
    website domain. Avoids O(n^2) full comparison; chain branches share a name
    token so they land in the same block and are separated later by geo veto.
    """
    by_token: dict[str, list[dict]] = {}
    by_domain: dict[str, list[dict]] = {}
    for r in rows:
        tok = significant_first_token(r["name"])
        if tok:
            by_token.setdefault(tok, []).append(r)
        dom = domain_of(r.get("website"))
        if dom:
            by_domain.setdefault(dom, []).append(r)

    seen: set[tuple] = set()
    pairs: list[tuple[dict, dict]] = []
    for bucket in (*by_token.values(), *by_domain.values()):
        for a, b in combinations(bucket, 2):
            key = tuple(sorted((str(a["id"]), str(b["id"]))))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((a, b))
    return pairs
```

- [ ] **Step 4: Run, verify pass**

Run: `cd backend && uv run pytest tests/test_matching.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/matching.py backend/tests/test_matching.py
git commit -m "feat(matcher): candidate blocking by name-token + website domain"
```

---

## Task 7: db.py — candidate load + enqueue decision

**Files:**
- Modify: `backend/db.py`
- Test: `backend/tests/test_matching_db.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_matching_db.py`:

```python
from unittest.mock import MagicMock, patch


def test_load_restaurants_for_match_selects_fields():
    rows = [{"id": "1", "name": "Foo", "website": None, "phone": None,
             "lat": None, "lng": None, "geo_source": None, "cuisine": None,
             "created_at": "2026-01-01T00:00:00Z"}]
    with patch("db.get_client") as mock_get:
        client = MagicMock()
        client.table.return_value.select.return_value.execute.return_value.data = rows
        mock_get.return_value = client
        import db
        out = db.load_restaurants_for_match()
    assert out == rows
    client.table.assert_called_with("restaurants")


def test_enqueue_decision_inserts_row():
    with patch("db.get_client") as mock_get:
        client = MagicMock()
        client.table.return_value.upsert.return_value.execute.return_value.data = [{"id": "d1"}]
        mock_get.return_value = client
        import db
        out = db.enqueue_decision(
            survivor_id="a", loser_id="b", score=0.95,
            features={"name_sim": 0.95}, status="queued",
        )
    assert out == "d1"
```

- [ ] **Step 2: Run, verify fail**

Run: `cd backend && uv run pytest tests/test_matching_db.py -v`
Expected: FAIL — `AttributeError: module 'db' has no attribute 'load_restaurants_for_match'`.

- [ ] **Step 3: Implement**

Add to `backend/db.py` (after `get_last_run_per_platform`, near other selects):

```python
def load_restaurants_for_match() -> list[dict]:
    """Load all restaurants with the fields the matcher scores on."""
    client = get_client()
    res = (
        client.table("restaurants")
        .select("id, name, website, phone, lat, lng, geo_source, cuisine, created_at")
        .execute()
    )
    return res.data


def enqueue_decision(
    *, survivor_id: str, loser_id: str, score: float,
    features: dict, status: str,
) -> str:
    """Insert/replace a match decision row (queue or audit log). Returns id.

    Upsert on the unordered-pair unique index so re-runs don't duplicate.
    """
    client = get_client()
    row = {
        "survivor_id": survivor_id,
        "loser_id": loser_id,
        "score": score,
        "features": features,
        "status": status,
    }
    res = client.table("restaurant_match_decisions").upsert(row).execute()
    return res.data[0]["id"]
```

- [ ] **Step 4: Run, verify pass**

Run: `cd backend && uv run pytest tests/test_matching_db.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/db.py backend/tests/test_matching_db.py
git commit -m "feat(matcher): db candidate load + decision enqueue"
```

---

## Task 8: db.py — merge_restaurants

**Files:**
- Modify: `backend/db.py`
- Test: `backend/tests/test_matching_db.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_matching_db.py`:

```python
def test_merge_restaurants_moves_listings_and_deletes_loser():
    import db
    calls = {"updated_listings": [], "deleted_restaurant": []}

    survivor = {"id": "S", "phone": None, "website": "https://s.be",
                "lat": None, "lng": None, "geo_source": None,
                "cuisine": None, "image_url": None}
    loser = {"id": "L", "phone": "021234567", "website": "https://l.be",
             "lat": 50.8, "lng": 4.3, "geo_source": "uber_eats",
             "cuisine": "Pizza", "image_url": "http://img"}

    client = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "restaurants":
            # select survivor/loser by id
            def select(*a, **k):
                sel = MagicMock()
                def eq(col, val):
                    e = MagicMock()
                    e.limit.return_value.execute.return_value.data = (
                        [survivor] if val == "S" else [loser]
                    )
                    e.execute.return_value.data = [survivor] if val == "S" else [loser]
                    return e
                sel.eq.side_effect = eq
                return sel
            t.select.side_effect = select
            t.update.return_value.eq.return_value.execute.return_value.data = []
            t.delete.return_value.eq.side_effect = lambda c, v: (
                calls["deleted_restaurant"].append(v) or
                MagicMock(execute=lambda: MagicMock(data=[]))
            )
        elif name == "platform_listings":
            # loser has a 'deliveroo' listing; survivor has none → simple move
            sel = t.select.return_value
            sel.eq.return_value.execute.return_value.data = [
                {"id": "PL1", "platform": "deliveroo", "last_scraped_at": None}
            ]
            t.update.return_value.eq.return_value.execute.return_value.data = []
        return t

    client.table.side_effect = table
    with patch("db.get_client", return_value=client):
        db.merge_restaurants("S", "L")

    assert "L" in calls["deleted_restaurant"]
```

- [ ] **Step 2: Run, verify fail**

Run: `cd backend && uv run pytest tests/test_matching_db.py -k merge -v`
Expected: FAIL — `AttributeError: ... 'merge_restaurants'`.

- [ ] **Step 3: Implement**

Add to `backend/db.py`:

```python
def _fetch_restaurant(client, rid: str) -> dict | None:
    res = client.table("restaurants").select(
        "id, phone, website, lat, lng, geo_source, cuisine, image_url"
    ).eq("id", rid).limit(1).execute()
    return res.data[0] if res.data else None


def merge_restaurants(survivor_id: str, loser_id: str) -> None:
    """Merge loser into survivor: move listings, fill nulls, delete loser.

    Idempotent: if loser is already gone, this is a no-op. Same-platform
    listing conflicts keep the row with the newer last_scraped_at.
    """
    if survivor_id == loser_id:
        return
    client = get_client()
    survivor = _fetch_restaurant(client, survivor_id)
    loser = _fetch_restaurant(client, loser_id)
    if survivor is None or loser is None:
        return  # already merged / missing

    # 1. Listings: detect same-platform conflicts.
    surv_listings = client.table("platform_listings").select(
        "id, platform, last_scraped_at"
    ).eq("restaurant_id", survivor_id).execute().data
    lose_listings = client.table("platform_listings").select(
        "id, platform, last_scraped_at"
    ).eq("restaurant_id", loser_id).execute().data

    surv_by_platform = {l["platform"]: l for l in surv_listings}
    for ll in lose_listings:
        clash = surv_by_platform.get(ll["platform"])
        if clash is None:
            client.table("platform_listings").update(
                {"restaurant_id": survivor_id}
            ).eq("id", ll["id"]).execute()
        else:
            # Keep the newer; delete the older.
            keep_loser = (ll.get("last_scraped_at") or "") > (clash.get("last_scraped_at") or "")
            if keep_loser:
                client.table("platform_listings").delete().eq("id", clash["id"]).execute()
                client.table("platform_listings").update(
                    {"restaurant_id": survivor_id}
                ).eq("id", ll["id"]).execute()
            else:
                client.table("platform_listings").delete().eq("id", ll["id"]).execute()

    # 2. Fill survivor null fields from loser.
    fill = {}
    for k in ("phone", "website", "lat", "lng", "geo_source", "cuisine", "image_url"):
        if not survivor.get(k) and loser.get(k):
            fill[k] = loser[k]
    if fill:
        client.table("restaurants").update(fill).eq("id", survivor_id).execute()

    # 3. Delete loser.
    client.table("restaurants").delete().eq("id", loser_id).execute()
```

- [ ] **Step 4: Run, verify pass**

Run: `cd backend && uv run pytest tests/test_matching_db.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/db.py backend/tests/test_matching_db.py
git commit -m "feat(matcher): merge_restaurants with platform-conflict resolution"
```

---

## Task 9: db.py — tighten upsert_restaurant inline locks + geo_source

**Files:**
- Modify: `backend/db.py` (`upsert_restaurant`, lines ~85-169)
- Test: `backend/tests/test_matching_db.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_matching_db.py`:

```python
def test_upsert_restaurant_website_domain_lock():
    """A new name with a known website domain attaches to the existing row."""
    import db
    existing = [{"id": "R1", "name": "Old Name", "website": "https://foo.be"}]
    client = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "restaurants":
            # exact + ilike name lookups return nothing; website lookup returns R1
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
            t.select.return_value.ilike.return_value.limit.return_value.execute.return_value.data = []
            # website domain candidates
            t.select.return_value.not_.return_value.is_.return_value.execute.return_value.data = existing
            t.select.return_value.eq.return_value.execute.return_value.data = [{"cuisine": None, "image_url": None}]
            t.update.return_value.eq.return_value.execute.return_value.data = []
        return t

    client.table.side_effect = table
    with patch("db.get_client", return_value=client):
        rid = db.upsert_restaurant({"name": "Totally Different", "website": "http://www.foo.be/x"})
    assert rid == "R1"


def test_upsert_restaurant_stamps_geo_source():
    """geo_source is persisted when provided on insert."""
    import db
    captured = {}
    client = MagicMock()

    def table(name):
        t = MagicMock()
        if name == "restaurants":
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
            t.select.return_value.ilike.return_value.limit.return_value.execute.return_value.data = []
            t.select.return_value.not_.return_value.is_.return_value.execute.return_value.data = []
            def upsert(data, **k):
                captured.update(data)
                m = MagicMock()
                m.execute.return_value.data = [{"id": "NEW"}]
                return m
            t.upsert.side_effect = upsert
        return t

    client.table.side_effect = table
    with patch("db.get_client", return_value=client):
        rid = db.upsert_restaurant({"name": "Brand New", "slug": "brand-new",
                                    "lat": 50.8, "lng": 4.3, "geo_source": "uber_eats"})
    assert rid == "NEW"
    assert captured.get("geo_source") == "uber_eats"
```

- [ ] **Step 2: Run, verify fail**

Run: `cd backend && uv run pytest tests/test_matching_db.py -k upsert -v`
Expected: FAIL (website-domain lock not implemented; geo_source path may pass or fail depending — both must pass after impl).

- [ ] **Step 3: Implement**

In `backend/db.py`, add the website-domain lock to `upsert_restaurant`. Insert this block **after step 2 (case-insensitive match, line ~129)** and **before step 3 (canonical base match)**:

```python
    # 2b. Website-domain lock — strongest deterministic signal. A new listing
    #     whose website resolves to a domain we already store is the same venue.
    import matching as _m
    incoming_domain = _m.domain_of(data.get("website"))
    if incoming_domain:
        cands = (
            client.table("restaurants")
            .select("id, website")
            .not_.is_("website", "null")
            .execute()
        )
        for c in cands.data:
            if _m.domain_of(c.get("website")) == incoming_domain:
                return _found(c["id"])
```

Then ensure `geo_source` is carried on insert. The final insert already does
`client.table("restaurants").upsert(data, on_conflict="slug")` — `data` includes
`geo_source` when the caller passes it, so no change needed there. Add `geo_source`
to the `_found` updater so re-scrapes can upgrade a row's geo to venue-grade. In
`_found`, after the `lat`/`lng` loop, add:

```python
        if data.get("geo_source") in ("uber_eats", "direct"):
            # Upgrade to venue-grade coords when a better source scrapes it.
            if data.get("lat") is not None and data.get("lng") is not None:
                updates["lat"] = data["lat"]
                updates["lng"] = data["lng"]
                updates["geo_source"] = data["geo_source"]
```

- [ ] **Step 4: Run, verify pass**

Run: `cd backend && uv run pytest tests/test_matching_db.py tests/test_db.py -v`
Expected: all passed (no regression in existing test_db.py).

- [ ] **Step 5: Commit**

```bash
git add backend/db.py backend/tests/test_matching_db.py
git commit -m "feat(matcher): website-domain inline lock + geo_source persistence"
```

---

## Task 10: Scrapers pass geo_source

**Files:**
- Modify: `backend/scrapers/ubereats.py`, `backend/scrapers/deliveroo.py`, `backend/scrapers/direct.py`

- [ ] **Step 1: UberEats — stamp venue-grade source**

In `backend/scrapers/ubereats.py`, find each `db.upsert_restaurant({...})` call that sets `lat`/`lng` (around lines 129-150) and add `"geo_source": "uber_eats"` to the dict.

- [ ] **Step 2: Deliveroo — stamp zone source**

In `backend/scrapers/deliveroo.py:313-318`, change the upsert to mark the geohash coords as zone-grade:

```python
                rid = db.upsert_restaurant({
                    "name": r["name"],
                    "slug": r["slug"],
                    "image_url": r.get("image_url"),
                    **({} if coords is None else {"lat": coords[0], "lng": coords[1], "geo_source": "deliveroo"}),
                })
```

- [ ] **Step 3: Direct — stamp venue-grade source**

In `backend/scrapers/direct.py`, find the Phase 2 `db.upsert_restaurant({...})` (around line 349) that includes Maps `lat`/`lng` and add `"geo_source": "direct"`.

- [ ] **Step 4: Run scraper unit tests**

Run: `cd backend && uv run pytest tests/test_ubereats_scraper.py tests/test_deliveroo_scraper.py -v`
Expected: pass (these mock db; geo_source is an extra dict key, non-breaking). If a test asserts exact upsert payloads, update the expected dict to include `geo_source`.

- [ ] **Step 5: Commit**

```bash
git add backend/scrapers/ubereats.py backend/scrapers/deliveroo.py backend/scrapers/direct.py
git commit -m "feat(matcher): scrapers stamp geo_source on restaurant upsert"
```

---

## Task 11: Batch match job + wiring

**Files:**
- Create: `backend/scrapers/match.py`
- Modify: `backend/routers/scrapers.py`, `backend/scheduler.py`
- Test: `backend/tests/test_match_job.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_match_job.py`:

```python
from unittest.mock import patch
import matching


def _r(name, **kw):
    base = {"id": kw.get("id", name), "name": name, "website": None, "phone": None,
            "lat": None, "lng": None, "geo_source": None, "cuisine": None,
            "created_at": "2026-01-01T00:00:00Z"}
    base.update(kw)
    return base


def test_match_job_dry_run_writes_nothing():
    from scrapers import match
    rows = [_r("Pizza Minute", id="1", website="https://pz.be"),
            _r("PizzaMinute", id="2", website="http://pz.be")]
    with patch("db.load_restaurants_for_match", return_value=rows), \
         patch("db.merge_restaurants") as merge, \
         patch("db.enqueue_decision") as enq:
        result = match.run_sync(dry_run=True, log_fn=lambda m: None)
    merge.assert_not_called()
    enq.assert_not_called()
    # website domain match → auto_merge proposed
    assert result["auto_merge"] >= 1


def test_match_job_executes_merges_when_not_dry_run():
    from scrapers import match
    rows = [_r("Pizza Minute", id="1", website="https://pz.be"),
            _r("PizzaMinute", id="2", website="http://pz.be")]
    with patch("db.load_restaurants_for_match", return_value=rows), \
         patch("db.merge_restaurants") as merge, \
         patch("db.enqueue_decision") as enq:
        match.run_sync(dry_run=False, log_fn=lambda m: None)
    assert merge.call_count == 1
    assert enq.call_count == 1  # the auto_merge logged
```

- [ ] **Step 2: Run, verify fail**

Run: `cd backend && uv run pytest tests/test_match_job.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapers.match'`.

- [ ] **Step 3: Implement the job**

Create `backend/scrapers/match.py`:

```python
"""Batch restaurant matcher job.

Loads all restaurants, blocks candidates, scores, and either executes merges
(auto-merge band) + enqueues review rows (queue band), or — in dry-run — just
counts and logs proposed actions without writing.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import db
import matching
from models import ScraperConfig, ScraperResult


def _survivor_loser(a: dict, b: dict) -> tuple[dict, dict]:
    """Oldest created_at survives; tiebreak by most non-null fields."""
    def score(r: dict) -> tuple:
        non_null = sum(1 for k in ("phone", "website", "lat", "cuisine", "image_url") if r.get(k))
        return (r.get("created_at") or "", -non_null)
    return (a, b) if score(a) <= score(b) else (b, a)


def run_sync(*, dry_run: bool, log_fn) -> dict:
    rows = db.load_restaurants_for_match()
    log_fn(f"Loaded {len(rows)} restaurants")
    pairs = matching.block_candidates(rows)
    log_fn(f"{len(pairs)} candidate pairs after blocking")

    counts = {"auto_merge": 0, "queue": 0, "separate": 0}
    proposals: list[dict] = []
    merged_ids: set[str] = set()

    for a, b in pairs:
        if a["id"] in merged_ids or b["id"] in merged_ids:
            continue
        features = matching.score_pair(a, b)
        decision = matching.decide(features)
        counts[decision.value] += 1
        if decision == matching.Decision.SEPARATE:
            continue

        survivor, loser = _survivor_loser(a, b)
        proposals.append({
            "survivor_id": survivor["id"], "survivor_name": survivor["name"],
            "loser_id": loser["id"], "loser_name": loser["name"],
            "decision": decision.value, "features": features.to_dict(),
        })

        if dry_run:
            continue

        if decision == matching.Decision.AUTO_MERGE:
            db.merge_restaurants(survivor["id"], loser["id"])
            merged_ids.add(loser["id"])
            db.enqueue_decision(
                survivor_id=survivor["id"], loser_id=loser["id"],
                score=float(features.name_sim), features=features.to_dict(),
                status="auto_merged",
            )
        else:  # QUEUE
            db.enqueue_decision(
                survivor_id=survivor["id"], loser_id=loser["id"],
                score=float(features.name_sim), features=features.to_dict(),
                status="queued",
            )

    log_fn(f"auto_merge={counts['auto_merge']} queue={counts['queue']} separate={counts['separate']}")

    if dry_run:
        out_dir = os.path.join(os.path.dirname(__file__), "..", "match_output")
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = os.path.join(out_dir, f"dry-run-{stamp}.json")
        with open(path, "w") as f:
            json.dump({"counts": counts, "proposals": proposals}, f, indent=2, ensure_ascii=False)
        log_fn(f"DRY RUN — wrote {len(proposals)} proposals to {path}")

    return {**counts, "proposals": len(proposals)}


async def run(config: ScraperConfig, log_fn, **kwargs) -> ScraperResult:
    """Async adapter for the scraper router. dry_run via config.target == 'dry-run'."""
    import asyncio
    dry = (config.target or "").lower() == "dry-run"
    result = await asyncio.to_thread(run_sync, dry_run=dry, log_fn=log_fn)
    return ScraperResult(records_saved=result["auto_merge"])
```

- [ ] **Step 4: Run, verify pass**

Run: `cd backend && uv run pytest tests/test_match_job.py -v`
Expected: 2 passed.

- [ ] **Step 5: Wire into router**

In `backend/routers/scrapers.py`: add the import and registry entry.

At the imports (line ~8):
```python
from scrapers import ubereats, deliveroo, takeaway, fees, direct, direct_menu, match
```

In the `SCRAPERS` dict (line ~36):
```python
    "match":       match.run,
```

Add a timeout entry in `_TIMEOUTS` (line ~22):
```python
    "match":       15 * 60,
```

- [ ] **Step 6: Wire into scheduler**

In `backend/scheduler.py`, inside `_run_batch_all`, after `await _run_fee_refresh()` (line ~165) append:

```python
    # Reconcile cross-platform duplicates after all data is fresh.
    await _run_match()
```

And add the helper after `_run_fee_refresh` (after line ~181):

```python
async def _run_match() -> None:
    from scrapers import match as _match
    run_id = db.create_run("match")
    try:
        result = await asyncio.to_thread(_match.run_sync, dry_run=False, log_fn=_noop)
        db.finish_run(run_id, "success", records_saved=result["auto_merge"])
    except Exception as e:
        db.finish_run(run_id, "failed", error_msg=str(e))
        import alerting; alerting.send_failure_alert("match", str(e), run_id)
```

Add `"match"` to the platform tuple in `db.get_last_run_per_platform` (db.py line ~283):
```python
    for platform in ("ubereats", "deliveroo", "takeaway", "fees", "direct", "direct_menu", "dom_menu", "match"):
```

- [ ] **Step 7: Run full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: all pass (no regressions).

- [ ] **Step 8: Add match_output to gitignore**

Append to `backend/.gitignore` (create if absent):
```
match_output/
```

- [ ] **Step 9: Commit**

```bash
git add backend/scrapers/match.py backend/routers/scrapers.py backend/scheduler.py backend/db.py backend/tests/test_match_job.py backend/.gitignore
git commit -m "feat(matcher): batch match job wired to router + scheduler"
```

---

## Task 12: Dashboard review queue

**Files:**
- Modify: `backend/db.py` (queue getters/resolvers), `backend/routers/data.py` (endpoints), `backend/dashboard/src/` (panel)
- Test: `backend/tests/test_matching_db.py`

- [ ] **Step 1: Add failing db tests**

Append to `backend/tests/test_matching_db.py`:

```python
def test_get_queued_decisions_filters_status():
    rows = [{"id": "d1", "status": "queued"}]
    with patch("db.get_client") as mock_get:
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = rows
        mock_get.return_value = client
        import db
        out = db.get_queued_decisions()
    assert out == rows


def test_resolve_decision_approve_merges():
    with patch("db.get_client") as mock_get, patch("db.merge_restaurants") as merge:
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "d1", "survivor_id": "S", "loser_id": "L", "status": "queued"}
        ]
        client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []
        mock_get.return_value = client
        import db
        db.resolve_decision("d1", approve=True, resolved_by="admin")
    merge.assert_called_once_with("S", "L")


def test_resolve_decision_reject_no_merge():
    with patch("db.get_client") as mock_get, patch("db.merge_restaurants") as merge:
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "d1", "survivor_id": "S", "loser_id": "L", "status": "queued"}
        ]
        client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []
        mock_get.return_value = client
        import db
        db.resolve_decision("d1", approve=False, resolved_by="admin")
    merge.assert_not_called()
```

- [ ] **Step 2: Run, verify fail**

Run: `cd backend && uv run pytest tests/test_matching_db.py -k "queued or resolve" -v`
Expected: FAIL — `AttributeError: ... 'get_queued_decisions'`.

- [ ] **Step 3: Implement db helpers**

Add to `backend/db.py`:

```python
def get_queued_decisions() -> list[dict]:
    """Pending review-queue rows, newest first, with both restaurant names."""
    client = get_client()
    res = (
        client.table("restaurant_match_decisions")
        .select("*")
        .eq("status", "queued")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


def resolve_decision(decision_id: str, *, approve: bool, resolved_by: str) -> None:
    """Approve (→ merge) or reject a queued decision."""
    from datetime import datetime, timezone
    client = get_client()
    row = (
        client.table("restaurant_match_decisions")
        .select("id, survivor_id, loser_id, status")
        .eq("id", decision_id)
        .limit(1)
        .execute()
    )
    if not row.data:
        return
    d = row.data[0]
    if approve:
        merge_restaurants(d["survivor_id"], d["loser_id"])
    client.table("restaurant_match_decisions").update({
        "status": "approved" if approve else "rejected",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "resolved_by": resolved_by,
    }).eq("id", decision_id).execute()
```

- [ ] **Step 4: Run, verify pass**

Run: `cd backend && uv run pytest tests/test_matching_db.py -v`
Expected: all passed.

- [ ] **Step 5: Add router endpoints**

In `backend/routers/data.py`, add (match existing route style in that file):

```python
@router.get("/match-queue")
async def match_queue():
    return db.get_queued_decisions()


@router.post("/match-queue/{decision_id}/resolve")
async def resolve_match(decision_id: str, body: dict):
    db.resolve_decision(
        decision_id,
        approve=bool(body.get("approve")),
        resolved_by=body.get("resolved_by", "admin"),
    )
    return {"status": "ok"}
```

Verify `db` is imported at the top of `data.py` (add `import db` if missing). Confirm the router prefix so the full path is known (e.g. `/api/data/match-queue`).

- [ ] **Step 6: Add dashboard panel**

In `backend/dashboard/src/`, add a `MatchQueue` view following the existing claims/inquiries panel pattern (find it with `grep -rl "claim" backend/dashboard/src`). It must:
- `GET {API}/data/match-queue` on mount, render a table: survivor name, loser name, `score`, and `features` (name_sim, website_match, phone_match, geo_dist).
- Two buttons per row → `POST {API}/data/match-queue/{id}/resolve` with `{"approve": true|false}` (Bearer token from existing auth context), then refetch.
- Register it in the dashboard nav alongside the existing admin panels.

Mirror the exact fetch/auth/styling helpers the claims panel uses — do not invent new ones.

- [ ] **Step 7: Build dashboard**

Run:
```bash
cd backend/dashboard && npm run build
```
Expected: build succeeds, no type errors.

- [ ] **Step 8: Commit**

```bash
git add backend/db.py backend/routers/data.py backend/dashboard/ backend/tests/test_matching_db.py
git commit -m "feat(matcher): review-queue endpoints + dashboard panel"
```

---

## Task 13: Backfill — stamp geo_source, dry-run, execute

**Files:** none (operational, run against remote Supabase + prod backend)

- [ ] **Step 1: Backfill geo_source for existing rows (SQL via MCP)**

Stamp existing coords by best-known source so the matcher can use geo immediately.
Run via Supabase MCP `execute_sql`:

```sql
-- Venue-grade if the restaurant has an uber_eats or direct listing.
update restaurants r set geo_source = 'uber_eats'
where r.lat is not null and r.geo_source is null
  and exists (select 1 from platform_listings pl
              where pl.restaurant_id = r.id and pl.platform = 'uber_eats');

update restaurants r set geo_source = 'direct'
where r.lat is not null and r.geo_source is null
  and exists (select 1 from platform_listings pl
              where pl.restaurant_id = r.id and pl.platform = 'direct');

-- Remaining coords came from Deliveroo geohash (zone centroid) → mark non-venue.
update restaurants r set geo_source = 'deliveroo'
where r.lat is not null and r.geo_source is null;
```

Verify:
```sql
select geo_source, count(*) from restaurants where lat is not null group by geo_source;
```
Expected: rows for `uber_eats`, `direct`, `deliveroo`; none null-with-coords.

- [ ] **Step 2: Deploy code to prod**

```bash
ssh -i ~/.ssh/id_ed25519_forkeur root@178.104.57.72 "cd /opt/forkeur && git pull && /root/.local/bin/uv sync --project backend && systemctl restart forkeur-backend"
```
Expected: service active. (Apply migration 012 to remote first if not already — Step in Task 1 applied it via MCP, which targets the remote project, so it is already live.)

- [ ] **Step 3: Trigger dry-run**

Get a Bearer token, then:
```bash
curl -s -X POST http://localhost:8000/api/scrapers/match/run \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"target":"dry-run"}'
```
Then read the newest file in `backend/match_output/` on the server (or scp it back). Inspect: do the `auto_merge` proposals look correct? Spot-check 10. Confirm the 26 known splits appear as auto_merge or queue, and no chain branches are in auto_merge.

- [ ] **Step 4: Tune if needed**

If auto-merges look wrong, adjust `HIGH_NAME_SIM` / `GEO_CONFIRM_M` / `GEO_VETO_M` in `matching.py`, commit, redeploy, re-dry-run. Repeat until the proposal file is clean.

- [ ] **Step 5: Execute the real backfill**

```bash
curl -s -X POST http://localhost:8000/api/scrapers/match/run \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}'
```
Expected: run completes; `scraper_runs` shows a `match` success row.

- [ ] **Step 6: Verify results**

```sql
-- Fewer single-platform restaurants than the 727 baseline.
with pl as (select restaurant_id, count(distinct platform) n
            from platform_listings group by restaurant_id)
select n, count(*) from pl group by n order by n;

select status, count(*) from restaurant_match_decisions group by status;
```
Expected: 2/3/4-platform counts up, single-platform down; `auto_merged` + `queued` rows present.

- [ ] **Step 7: Resolve the queue**

Open the dashboard MatchQueue panel; approve/reject each `queued` pair.

- [ ] **Step 8: Confirm scheduler wiring**

Verify the nightly batch now ends with a `match` run (check `scraper_runs` after the next scheduled cycle, or confirm `_run_match()` is called in `_run_batch_all`).

---

## Self-review notes

- **Spec coverage:** inline locks (T9) · batch scoring core (T2-6) · auto/queue/separate bands incl. chain veto (T5) · `restaurant_match_decisions` schema (T1) · merge w/ platform-conflict (T8) · dry-run (T11) · dashboard queue (T12) · backfill + tuning loop (T13) · geo_source distinction (T1, T9, T10, T13). All covered.
- **Type consistency:** `Decision` enum values (`auto_merge`/`queue`/`separate`) vs DB `status` strings (`auto_merged`/`queued`/`approved`/`rejected`/`separated`) are intentionally different namespaces — the job maps Decision→status explicitly in T11. `MatchFeatures.to_dict()` used by job + db consistently. `run_sync(dry_run, log_fn)` signature consistent across T11 tests, job, scheduler.
- **No placeholders:** every code step has full code; dashboard panel (T12 S6) references the existing claims panel as the concrete pattern to mirror rather than inventing UI.
```
