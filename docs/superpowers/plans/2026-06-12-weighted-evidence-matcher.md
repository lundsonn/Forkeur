# Weighted-Evidence Matcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the veto-cascade `decide()` in `backend/matching.py` with an additive weighted-evidence score so strong signals (geo, phone, address) can rescue pairs that a single weak signal currently kills.

**Architecture:** All signal extraction stays in pure functions in `backend/matching.py` (no DB access). `score_pair` keeps returning `MatchFeatures` (two new fields). A new `evidence_score()` maps features → (total, per-signal contributions); `decide()` maps the total to AUTO_MERGE / QUEUE / SEPARATE bands with one hard geo rule. `backend/scrapers/match.py` gains a geo blocking key and richer dry-run output. A golden fixture of 36+ labeled prod pairs (`backend/tests/fixtures/golden_pairs.json`, already committed to the working tree) is the regression contract.

**Tech Stack:** Python 3.12, `uv run pytest`, rapidfuzz (JaroWinkler + fuzz.token_set_ratio).

**Spec:** `docs/superpowers/specs/2026-06-12-matcher-redesign-design.md`

**IMPORTANT — no git commits.** The user commits manually. Wherever a normal TDD flow would commit, just stop after tests pass. Never run `git commit`.

**Run tests from `backend/`:** `cd backend && uv run pytest tests/test_matching.py -x -q`

---

### Task 1: Address normalizer v2 (bilingual Brussels)

**Files:**
- Modify: `backend/matching.py` (replace `_normalize_address` + `_match_address`, lines ~203–228; extend `_STREET_PREFIX_RE`)
- Test: `backend/tests/test_matching.py` (append new tests)

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_matching.py`:

```python
# --- Address normalizer v2 -------------------------------------------------

def test_house_number_trailing():
    assert matching.house_number("Chaussee de Gand 386") == "386"

def test_house_number_leading():
    assert matching.house_number("65 Rue Ropsy Chaudron") == "65"

def test_house_number_letter_suffix_stripped():
    assert matching.house_number("Rue des Poissoniers 6B") == "6"

def test_house_number_skips_postal_code():
    # Deliveroo embeds city+postal: first number is the house number, the
    # trailing 1040 equals the postal code and must be skipped as candidate
    assert matching.house_number("140 rue Philippe Baucq, Brussels, 1040", postal_code="1040") == "140"

def test_house_number_none_when_only_postal():
    assert matching.house_number("Rue Sans Numero, 1040", postal_code="1040") is None

def test_street_core_fr_prefix():
    assert matching.street_core("Chaussée de Waterloo 186") == "waterloo"

def test_street_core_nl_suffix():
    assert matching.street_core("Waterloosesteenweg 186") == "waterloose"

def test_street_core_abbreviation():
    assert matching.street_core("Chau. de Gand 386") == "gand"
    assert matching.street_core("Chaussee de Gand 386") == "gand"

def test_street_core_nl_laan():
    assert matching.street_core("Anspachlaan 21") == "anspach"
    assert matching.street_core("15 Boulevard Anspach") == "anspach"

def test_street_core_strips_city_tail():
    assert matching.street_core("140 rue Philippe Baucq, Brussels, 1040") == "philippebaucq"

def _addr(street, pc):
    return {"street_address": street, "postal_code": pc}

def test_match_address_bilingual_same():
    assert matching._match_address(
        _addr("Waterloosesteenweg 186", "1060"),
        _addr("Chaussée de Waterloo 186", "1060")) is True

def test_match_address_abbreviation_same():
    assert matching._match_address(
        _addr("Chaussee de Gand 386", "1080"),
        _addr("Chau. de Gand 386", "1080")) is True

def test_match_address_house_letter_same():
    assert matching._match_address(
        _addr("Rue des Poissoniers 6B, Brussels, 1000", "1000"),
        _addr("Rue des Poissonniers 6", "1000")) is True

def test_match_address_number_conflict():
    # Two Carrefour City on Anspach: 15 vs 21 → different venues
    assert matching._match_address(
        _addr("Anspachlaan 21", "1000"),
        _addr("15 Boulevard Anspach", "1000")) is False

def test_match_address_postal_and_street_conflict():
    assert matching._match_address(
        _addr("279 Rue Saint-Denis", "1190"),
        _addr("27 Chaussée d'Ixelles", "1050")) is False

def test_match_address_missing_data_unknown():
    assert matching._match_address(_addr(None, None), _addr("Rue X 1", "1000")) is None
    assert matching._match_address(_addr(None, "1000"), _addr(None, "1000")) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_matching.py -q -k "house_number or street_core or match_address"`
Expected: FAIL — `AttributeError: module 'matching' has no attribute 'house_number'`

- [ ] **Step 3: Implement**

In `backend/matching.py`, replace the existing `_STREET_PREFIX_RE`, `_normalize_address`, and `_match_address` block with:

```python
_STREET_PREFIX_RE = re.compile(
    r"^(?:rue|avenue|av|boulevard|bvd|bd|chaussee|chau|ch[eé]e|ch|dr[eè]ve|dreve|"
    r"place|pl|square|sq|clos|impasse|all[eé]e|quai|passage|sentier|chemin|"
    r"ruelle|voie|cit[eé]|galerie|parvis|rond[\s-]?point)\.?\s+",
    re.IGNORECASE,
)
_NL_STREET_SUFFIX_RE = re.compile(
    r"(steenweg|straat|laan|plein|baan|dreef|weg|kaai|gang|markt)$"
)
_ADDR_PARTICLES = {"de", "du", "des", "d", "la", "le", "les", "l",
                   "van", "der", "den", "ten", "ter", "aux", "au"}
ADDR_STREET_SAME_JW = 0.85
ADDR_STREET_CONFLICT_JW = 0.60


def house_number(addr: str | None, postal_code: str | None = None) -> str | None:
    """First standalone number token that isn't the postal code.

    Leading ('65 Rue Ropsy Chaudron') or trailing ('Chaussee de Gand 386');
    letter suffixes dropped ('6B' → '6')."""
    if not addr:
        return None
    pc = (postal_code or "").strip()
    for m in re.finditer(r"\b(\d+)[a-zA-Z]?\b", addr):
        num = m.group(1)
        if pc and num == pc:
            continue
        return num
    return None


def street_core(addr: str | None) -> str:
    """Language-neutral street identifier for fuzzy comparison.

    Lowercase, accent-free; city/postal tail after the first comma dropped;
    digits dropped; FR street types stripped as a leading prefix; NL street
    types stripped as glued suffixes; FR/NL particles dropped."""
    if not addr:
        return ""
    s = _strip_accents(addr.split(",")[0].strip().lower())
    s = re.sub(r"\d+[a-z]?", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = _STREET_PREFIX_RE.sub("", s)
    toks = []
    for tok in re.split(r"[\s\-'.]+", s):
        if not tok or tok in _ADDR_PARTICLES:
            continue
        toks.append(_NL_STREET_SUFFIX_RE.sub("", tok))
    return re.sub(r"[^a-z0-9]", "", "".join(toks))


def _match_address(a: dict, b: dict) -> bool | None:
    """True = same venue address, False = conflict, None = insufficient data."""
    sa, sb = street_core(a.get("street_address")), street_core(b.get("street_address"))
    pca = (a.get("postal_code") or "").strip()
    pcb = (b.get("postal_code") or "").strip()
    na = house_number(a.get("street_address"), pca)
    nb = house_number(b.get("street_address"), pcb)
    if not sa or not sb:
        return None
    jw = JaroWinkler.similarity(sa, sb)
    if na and nb and na == nb and jw >= ADDR_STREET_SAME_JW:
        return True
    if na and nb and (na != nb or jw < ADDR_STREET_CONFLICT_JW):
        return False
    # Postal disagreement only conflicts when streets also fail to match —
    # adjacent communes share street continuations.
    if pca and pcb and pca != pcb and jw < ADDR_STREET_SAME_JW:
        return False
    if jw >= ADDR_STREET_SAME_JW and pca and pcb and pca == pcb:
        return True
    return None
```

Note: `street_core` strips trailing NL suffix per token, so "Waterloosesteenweg" → token "waterloosesteenweg" → suffix-strip → "waterloose". The old `_normalize_address` function is deleted; nothing else referenced it.

- [ ] **Step 4: Run new tests**

Run: `cd backend && uv run pytest tests/test_matching.py -q -k "house_number or street_core or match_address"`
Expected: PASS (all new tests). Some pre-existing address tests may now fail — note them; they are rewritten in Task 7, do not fix here unless trivially compatible.

---

### Task 2: Name similarity best-of-3

**Files:**
- Modify: `backend/matching.py` (new `name_similarity`, `_strip_location_tokens`; extend `_BRUSSELS_LOCATIONS`; wire into `score_pair`; add `name_variant` to `MatchFeatures`)
- Test: `backend/tests/test_matching.py`

- [ ] **Step 1: Write failing tests**

```python
# --- Name similarity best-of-3 ----------------------------------------------

def test_name_similarity_plain_jw_wins_for_identical():
    sim, variant = matching.name_similarity("Mr. Cod", "Mr Cod")
    assert sim >= 0.97

def test_name_similarity_suffix_stripped_rescues_commune():
    # plain JW("la smorfia saintgilles", "la smorfia") < 0.92, but stripping
    # commune tokens makes them identical
    sim, variant = matching.name_similarity("La Smorfia Saint-Gilles", "La Smorfia")
    assert sim >= 0.97
    assert variant in ("suffix_stripped", "token_set")

def test_name_similarity_token_set_rescues_subset():
    sim, _ = matching.name_similarity("Tsuki Sushi I Sushi Bar", "Tsuki Sushi")
    assert sim >= 0.95

def test_name_similarity_different_names_stay_low():
    sim, _ = matching.name_similarity("Starbucks Rogier", "Pasta Bar Rogier")
    assert sim < 0.80

def test_name_similarity_strip_never_empties():
    # both names are pure location tokens after stripping → suffix variant skipped
    sim, _ = matching.name_similarity("Ixelles", "Uccle")
    assert sim < 0.80

def test_strip_location_tokens_two_word_commune():
    assert matching._strip_location_tokens("la smorfia saint gilles") == "la smorfia"
    assert matching._strip_location_tokens("thai wok express toison d or") == "thai wok express d or" or \
           matching._strip_location_tokens("thai wok express toison d or") == "thai wok express"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_matching.py -q -k name_similarity`
Expected: FAIL — no attribute `name_similarity`

- [ ] **Step 3: Implement**

In `backend/matching.py`:

1. Add to imports: `from rapidfuzz import fuzz`
2. Extend `_BRUSSELS_LOCATIONS` with: `"saintdenis", "saintecatherine", "anspach", "vorst", "etterbeekse", "stockel", "merode", "montgomery", "meiser", "dansaert", "saintboniface", "lemonnier", "clemenceau", "ribaucourt", "tomberg"`
3. Add:

```python
def _strip_location_tokens(norm: str) -> str:
    """Remove Brussels commune/landmark tokens (single or two-word) from a
    normalized name. 'la smorfia saint gilles' → 'la smorfia'."""
    toks = norm.split()
    out: list[str] = []
    i = 0
    while i < len(toks):
        pair = (toks[i] + toks[i + 1]) if i + 1 < len(toks) else None
        if pair and pair in _BRUSSELS_LOCATIONS:
            i += 2
            continue
        if toks[i] in _BRUSSELS_LOCATIONS:
            i += 1
            continue
        out.append(toks[i])
        i += 1
    return " ".join(out)


def name_similarity(a_name: str, b_name: str) -> tuple[float, str]:
    """Best-of-3 name similarity: plain JW, commune-suffix-stripped JW,
    token-set ratio. Returns (similarity, winning_variant)."""
    na, nb = normalize_name(a_name), normalize_name(b_name)
    best = (JaroWinkler.similarity(na, nb), "plain")
    sa, sb = _strip_location_tokens(na), _strip_location_tokens(nb)
    if len(sa) >= 3 and len(sb) >= 3:
        v = JaroWinkler.similarity(sa, sb)
        if v > best[0]:
            best = (v, "suffix_stripped")
    if na and nb:
        v = fuzz.token_set_ratio(na, nb) / 100.0
        if v > best[0]:
            best = (v, "token_set")
    return best
```

4. In `MatchFeatures`, add field `name_variant: str` (after `name_sim`).
5. In `score_pair`, replace the `name_sim = JaroWinkler.similarity(...)` line with:

```python
    name_sim, name_variant = name_similarity(a["name"], b["name"])
```

and pass `name_variant=name_variant` in the returned `MatchFeatures`.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_matching.py -q -k "name_similarity or strip_location"`
Expected: PASS. (Construction of `MatchFeatures` elsewhere in tests will fail until `name_variant` is supplied — Task 7 fixes those; for now give `name_variant` a default: `name_variant: str = "plain"`.)

---

### Task 3: Source-aware geo bands + deliveroo flag

**Files:**
- Modify: `backend/matching.py` (new `geo_band`; `deliveroo_geo` field on `MatchFeatures`; set it in `score_pair`)
- Test: `backend/tests/test_matching.py`

- [ ] **Step 1: Write failing tests**

```python
# --- Source-aware geo bands ---------------------------------------------------

def test_geo_band_precise():
    assert matching.geo_band(20, False) == "very_close"
    assert matching.geo_band(60, False) == "close"
    assert matching.geo_band(150, False) == "near"
    assert matching.geo_band(300, False) is None
    assert matching.geo_band(600, False) == "far"
    assert matching.geo_band(900, False) == "very_far"

def test_geo_band_deliveroo_widened():
    assert matching.geo_band(90, True) == "very_close"
    assert matching.geo_band(180, True) == "close"
    assert matching.geo_band(450, True) == "near"
    assert matching.geo_band(700, True) is None
    assert matching.geo_band(1200, True) == "far"
    assert matching.geo_band(2000, True) == "very_far"

def test_geo_band_none():
    assert matching.geo_band(None, False) is None

def test_score_pair_sets_deliveroo_geo_flag():
    a = _r("X", lat=50.85, lng=4.35, geo_source="deliveroo_venue")
    b = _r("X", lat=50.85, lng=4.35, geo_source="uber_eats")
    assert matching.score_pair(a, b).deliveroo_geo is True
    c = _r("X", lat=50.85, lng=4.35, geo_source="uber_eats")
    assert matching.score_pair(b, c).deliveroo_geo is False
```

(`_r` is the existing test-helper factory in `test_matching.py` — check its signature near the top of the file and adapt the calls to it.)

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_matching.py -q -k geo_band`
Expected: FAIL — no attribute `geo_band`

- [ ] **Step 3: Implement**

```python
# Geo distance bands. deliveroo_venue coords are zone-imprecise (observed
# ~400m off true venue), so bands widen when either side is deliveroo-sourced.
_GEO_BANDS_PRECISE = ((25.0, "very_close"), (75.0, "close"), (200.0, "near"),
                      (400.0, None), (800.0, "far"), (float("inf"), "very_far"))
_GEO_BANDS_DELIVEROO = ((100.0, "very_close"), (200.0, "close"), (500.0, "near"),
                        (800.0, None), (1500.0, "far"), (float("inf"), "very_far"))


def geo_band(dist_m: float | None, deliveroo_involved: bool) -> str | None:
    if dist_m is None:
        return None
    bands = _GEO_BANDS_DELIVEROO if deliveroo_involved else _GEO_BANDS_PRECISE
    for limit, label in bands:
        if dist_m <= limit:
            return label
    return None
```

On `MatchFeatures` add `deliveroo_geo: bool = False`. In `score_pair`, after the geo computation, add:

```python
    deliveroo_geo = a.get("geo_source") == "deliveroo_venue" or b.get("geo_source") == "deliveroo_venue"
```

and pass it in the returned `MatchFeatures`.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_matching.py -q -k "geo_band or deliveroo_geo"`
Expected: PASS

---

### Task 4: Menu token overlap v2

**Files:**
- Modify: `backend/matching.py` (new `menu_token_overlap`; use in `score_pair`)
- Test: `backend/tests/test_matching.py`

- [ ] **Step 1: Write failing tests**

```python
# --- Menu token overlap -------------------------------------------------------

def test_menu_token_overlap_cross_platform_formatting():
    # exact-title Jaccard would be 0 here; token overlap is high
    a = {"pizza margherita", "pizza quattro stagioni", "tiramisu maison"}
    b = {"margherita", "quattro stagioni", "tiramisu"}
    assert matching.menu_token_overlap(a, b) > 0.5

def test_menu_token_overlap_disjoint():
    a = {"sushi saumon", "maki avocat", "ramen tonkotsu"}
    b = {"pizza margherita", "pasta carbonara", "tiramisu"}
    assert matching.menu_token_overlap(a, b) == 0.0

def test_menu_token_overlap_requires_three_items():
    assert matching.menu_token_overlap({"a b"}, {"a b", "c d", "e f"}) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_matching.py -q -k menu_token`
Expected: FAIL

- [ ] **Step 3: Implement**

```python
def menu_token_overlap(titles_a: set[str], titles_b: set[str]) -> float | None:
    """Token-set Jaccard over menu titles. Same restaurant formats titles
    differently per platform, so exact-title overlap under-counts; word-level
    overlap is robust to prefixes/reordering. None if either side < 3 items."""
    if len(titles_a) < 3 or len(titles_b) < 3:
        return None
    ta = {tok for t in titles_a for tok in t.split() if len(tok) >= 3}
    tb = {tok for t in titles_b for tok in t.split() if len(tok) >= 3}
    if not ta or not tb:
        return None
    union = len(ta | tb)
    return len(ta & tb) / union if union else 0.0
```

In `score_pair`, replace the exact-title Jaccard block (the `menu_overlap` computation) with:

```python
    ma = menus.get(str(a["id"]), set()) if menus else set()
    mb = menus.get(str(b["id"]), set()) if menus else set()
    menu_overlap = menu_token_overlap(ma, mb)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_matching.py -q -k menu_token`
Expected: PASS. Existing menu-overlap tests asserting exact-title semantics will fail — they are rewritten in Task 7. Note: token-level Jaccard runs higher than exact-title Jaccard; the confirm threshold moves from 0.15 to 0.30 in Task 5's weights.

---

### Task 5: Evidence score + new decide()

**Files:**
- Modify: `backend/matching.py` (add `WEIGHTS`, `evidence_score`, rewrite `decide`; delete dead threshold constants)
- Test: `backend/tests/test_matching.py`

- [ ] **Step 1: Write failing tests**

```python
# --- Evidence score -----------------------------------------------------------

def _feat(**kw):
    base = dict(name_sim=0.0, name_variant="plain", website_match=False,
                phone_match=False, geo_dist=None, cuisine_match=False,
                cuisine_conflict=False, location_conflict=False,
                menu_overlap=None, soft_geo_dist=None, is_chain_name=False,
                slug_match=False, distinctive_conflict=False,
                address_match=None, deliveroo_geo=False)
    base.update(kw)
    return matching.MatchFeatures(**base)

def test_evidence_phone_plus_name_auto_merges():
    f = _feat(phone_match=True, name_sim=0.99)
    total, contrib = matching.evidence_score(f)
    assert contrib["phone_match"] == 3.0
    assert total >= matching.AUTO_BAND
    assert matching.decide(f) == matching.Decision.AUTO_MERGE

def test_evidence_colocation_gate_blocks_geo_for_unrelated_names():
    # Tekince Kebap / Pizzeria Koçak: 9m apart, totally different names
    f = _feat(name_sim=0.40, geo_dist=9.0, address_match=True)
    total, contrib = matching.evidence_score(f)
    assert "geo_very_close" not in contrib
    assert "address_same" not in contrib
    assert matching.decide(f) == matching.Decision.SEPARATE

def test_evidence_geo_negative_applies_without_gate():
    f = _feat(name_sim=0.40, geo_dist=900.0)
    _, contrib = matching.evidence_score(f)
    assert contrib["geo_very_far"] == -3.0

def test_evidence_suffix_name_plus_close_geo_auto_merges():
    # La Smorfia Saint-Gilles / La Smorfia: name rescued by best-of-3, 10m
    f = _feat(name_sim=0.99, geo_dist=10.0, address_match=True)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE

def test_evidence_deliveroo_far_geo_not_vetoed_with_phone():
    # Yaki: identical phone, 410m apart with deliveroo coords
    f = _feat(phone_match=True, name_sim=0.99, geo_dist=410.0,
              deliveroo_geo=True, address_match=True)
    assert matching.decide(f) == matching.Decision.AUTO_MERGE

def test_evidence_hard_rule_far_precise_geo_separates():
    # Krusty branches: 2.2km, both precise sources, names near-identical
    f = _feat(name_sim=0.98, geo_dist=2200.0, menu_overlap=0.5,
              website_match=True)
    assert matching.decide(f) == matching.Decision.SEPARATE

def test_evidence_hard_rule_spares_phone_match():
    f = _feat(name_sim=0.98, geo_dist=2200.0, phone_match=True)
    # phone match exempts from the hard rule; score decides (geo_very_far -3,
    # phone +3, name +2 → 2.0 → QUEUE)
    assert matching.decide(f) == matching.Decision.QUEUE

def test_evidence_chain_needs_overwhelming_proof():
    # chain flag + close geo + same name: queue at most, never silent auto
    f = _feat(name_sim=0.99, geo_dist=20.0, is_chain_name=True)
    assert matching.decide(f) in (matching.Decision.QUEUE, matching.Decision.AUTO_MERGE)
    # chain flag + name only → separate
    f2 = _feat(name_sim=0.99, is_chain_name=True)
    assert matching.decide(f2) == matching.Decision.SEPARATE

def test_evidence_address_conflict_beats_close_geo():
    # Panos+Delhaize vs Panos: 18m (bad coords) but address postal conflict
    f = _feat(name_sim=1.0, geo_dist=18.0, address_match=False,
              is_chain_name=True)
    assert matching.decide(f) != matching.Decision.AUTO_MERGE

def test_evidence_name_scaling():
    assert matching.evidence_score(_feat(name_sim=0.97))[1]["name"] == 2.0
    assert matching.evidence_score(_feat(name_sim=0.80))[1].get("name", 0.0) == 0.0
    mid = matching.evidence_score(_feat(name_sim=0.885))[1]["name"]
    assert 0.9 < mid < 1.1
    assert matching.evidence_score(_feat(name_sim=0.60))[1]["name_low"] == -2.0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_matching.py -q -k evidence`
Expected: FAIL — no attribute `evidence_score`

- [ ] **Step 3: Implement**

In `backend/matching.py`, delete the now-dead threshold constants `HIGH_NAME_SIM`, `NAME_SIM_WEBSITE_AUTO`, `GEO_CONFIRM_M`, `GEO_VETO_M`, `SOFT_GEO_VETO_M`, `MENU_OVERLAP_VETO`, `MENU_OVERLAP_CONFIRM`. Keep `DISTINCTIVE_REMAINDER_MIN` (still used by the distinctive-remainder feature extractor). Add:

```python
# --- Evidence weights -----------------------------------------------------------
WEIGHTS: dict[str, float] = {
    "phone_match": 3.0,
    "geo_very_close": 3.0,
    "geo_close": 2.5,
    "geo_near": 1.0,
    "address_same": 2.5,
    "name_max": 2.0,            # scaled 0 at name_sim<=0.80 → max at >=0.97
    "slug_match": 2.0,
    "menu_overlap": 1.0,        # token-level overlap >= MENU_TOKEN_CONFIRM
    "website_match": 1.0,
    "geo_far": -1.5,
    "geo_very_far": -3.0,
    "address_conflict": -2.0,
    "distinctive_conflict": -2.5,
    "name_low": -2.0,           # name_sim < 0.70
    "chain": -2.0,
    "location_conflict": -2.0,
    "cuisine_conflict": -1.0,
}
AUTO_BAND = 4.5
QUEUE_BAND = 1.5
MENU_TOKEN_CONFIRM = 0.30
IDENTITY_GATE_NAME_SIM = 0.5   # co-location gate: min name evidence for geo/addr positives
HARD_GEO_SEPARATE_M = 1000.0


def evidence_score(f: MatchFeatures) -> tuple[float, dict[str, float]]:
    """Additive evidence. Returns (total, per-signal contributions)."""
    c: dict[str, float] = {}
    # Co-location gate: physical proximity only counts FOR a merge when there
    # is minimal identity evidence — food courts put distinct restaurants
    # metres apart. Negative geo evidence applies unconditionally.
    identity = f.name_sim >= IDENTITY_GATE_NAME_SIM or f.phone_match or f.slug_match

    if f.phone_match:
        c["phone_match"] = WEIGHTS["phone_match"]

    dist = f.geo_dist if f.geo_dist is not None else f.soft_geo_dist
    band = geo_band(dist, f.deliveroo_geo)
    if band in ("very_close", "close", "near"):
        # positive geo requires both-venue-grade coords (geo_dist) + identity
        if identity and f.geo_dist is not None:
            c[f"geo_{band}"] = WEIGHTS[f"geo_{band}"]
    elif band in ("far", "very_far"):
        c[f"geo_{band}"] = WEIGHTS[f"geo_{band}"]

    if f.address_match is True and identity:
        c["address_same"] = WEIGHTS["address_same"]
    elif f.address_match is False:
        c["address_conflict"] = WEIGHTS["address_conflict"]

    if f.name_sim >= 0.97:
        c["name"] = WEIGHTS["name_max"]
    elif f.name_sim > 0.80:
        c["name"] = WEIGHTS["name_max"] * (f.name_sim - 0.80) / 0.17
    if f.name_sim < 0.70:
        c["name_low"] = WEIGHTS["name_low"]

    if f.slug_match and not f.is_chain_name:
        c["slug_match"] = WEIGHTS["slug_match"]
    if f.menu_overlap is not None and f.menu_overlap >= MENU_TOKEN_CONFIRM:
        c["menu_overlap"] = WEIGHTS["menu_overlap"]
    if f.website_match and not f.is_chain_name:
        c["website_match"] = WEIGHTS["website_match"]

    if f.distinctive_conflict and not (f.phone_match or f.slug_match):
        c["distinctive_conflict"] = WEIGHTS["distinctive_conflict"]
    if f.is_chain_name:
        c["chain"] = WEIGHTS["chain"]
    if f.location_conflict:
        c["location_conflict"] = WEIGHTS["location_conflict"]
    if f.cuisine_conflict:
        c["cuisine_conflict"] = WEIGHTS["cuisine_conflict"]

    return sum(c.values()), c


def decide(f: MatchFeatures) -> Decision:
    """Map evidence total to a decision band.

    One hard rule first: both-venue-grade precise (non-deliveroo) coords more
    than 1 km apart with no phone match can never merge — chain branches share
    name/menu/website and additive evidence must not pile past the bands."""
    if (f.geo_dist is not None and not f.deliveroo_geo
            and f.geo_dist > HARD_GEO_SEPARATE_M and not f.phone_match):
        return Decision.SEPARATE
    total, _ = evidence_score(f)
    if total >= AUTO_BAND:
        return Decision.AUTO_MERGE
    if total >= QUEUE_BAND:
        return Decision.QUEUE
    return Decision.SEPARATE
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_matching.py -q -k evidence`
Expected: PASS. Old `decide()`-cascade tests now fail — Task 7.

---

### Task 6: Golden-pair contract tests

**Files:**
- Already present: `backend/tests/fixtures/golden_pairs.json` (36 pairs from prod, 2026-06-12; sections `same` / `different` / `ambiguous`)
- Create: `backend/tests/test_golden_pairs.py`

- [ ] **Step 1: Write the contract test**

```python
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
```

Note: `chain_names=set()` — the golden rows carry the persisted `is_chain` flag from prod, which `score_pair` reads directly; the corpus-count heuristic needs the full corpus and is out of scope here.

- [ ] **Step 2: Run the contract**

Run: `cd backend && uv run pytest tests/test_golden_pairs.py -q`
Expected: PASS for every pair. **If any pair fails, do NOT change the fixture or relax the contract** — adjust `WEIGHTS`/bands/extractors in `matching.py` (most likely the address normalizer missing a street-type variant), rerun `tests/test_matching.py` to confirm no regression, and iterate. If a pair seems genuinely mislabeled, stop and surface it to the user — never relabel unilaterally.

---

### Task 7: Rewrite legacy cascade tests

**Files:**
- Modify: `backend/tests/test_matching.py` (tests asserting old cascade vetos)
- Modify: `backend/tests/test_match_job.py` (if it asserts decision internals)

- [ ] **Step 1: Run full matching suite, list failures**

Run: `cd backend && uv run pytest tests/test_matching.py tests/test_match_job.py -q 2>&1 | tail -30`

- [ ] **Step 2: Rewrite each failing test to band semantics**

Mapping rules (keep each test's scenario, update the expectation):
- Tests asserting a single veto (`geo > 300 → SEPARATE`, `cuisine_conflict → SEPARATE`, `menu_overlap < 0.03 → SEPARATE`, `name_sim < 0.92 → SEPARATE`) now assert the *band outcome* of the same feature set. Compute the expected contributions by hand from `WEIGHTS` and assert the resulting `Decision`. Where one weak negative no longer separates an otherwise-strong pair, the new expected decision is QUEUE or AUTO_MERGE — that is the intended behaviour change; update the assertion and the test name/docstring to describe the band logic.
- Tests of pure extractors (normalizers, `phone_digits`, `domain_of`, blocking, chain detection, distinctive remainder) should still pass untouched. If an address-normalizer test fails it asserts old `_normalize_address` behaviour — rewrite against `street_core`/`house_number` semantics from Task 1.
- `MatchFeatures(...)` constructions missing the new fields: add `name_variant="plain", deliveroo_geo=False` or rely on the defaults.
- In `test_match_job.py`, `enqueue_decision` is now called with `score=` the evidence total (a float that can exceed 1.0) — update any assertion pinning it to `name_sim`.

- [ ] **Step 3: Full backend suite green**

Run: `cd backend && uv run pytest -q 2>&1 | tail -5`
Expected: all pass (direct_menu/dom_menu/scraper suites unaffected).

---

### Task 8: Pipeline integration (geo blocking + scored dry-run)

**Files:**
- Modify: `backend/matching.py` (`block_candidates` — add geo key)
- Modify: `backend/scrapers/match.py` (dry-run output, enqueue score)
- Test: `backend/tests/test_matching.py`, `backend/tests/test_match_job.py`

- [ ] **Step 1: Write failing test for geo blocking**

```python
def test_block_candidates_geo_proximity_pairs_unrelated_names():
    a = _r("Totally Different", lat=50.8500, lng=4.3500, geo_source="uber_eats")
    b = _r("Other Name Entirely", lat=50.8501, lng=4.3501, geo_source="takeaway")
    far = _r("Third Place", lat=50.9000, lng=4.4000, geo_source="takeaway")
    pairs = matching.block_candidates([a, b, far])
    ids = {tuple(sorted((str(x["id"]), str(y["id"])))) for x, y in pairs}
    assert tuple(sorted((str(a["id"]), str(b["id"])))) in ids
    assert tuple(sorted((str(a["id"]), str(far["id"])))) not in ids
```

(Adapt `_r` usage to the existing helper; rows need distinct `id` values.)

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_matching.py -q -k geo_proximity`
Expected: FAIL — names share no token/prefix/domain so no pair is generated

- [ ] **Step 3: Implement geo blocking**

In `block_candidates`, add a fourth blocking index after `by_domain`:

```python
    # Geo grid blocking: ~150m cells; each restaurant lands in its cell and
    # pairs are drawn within a cell and its 8 neighbours, then distance-checked.
    GEO_BLOCK_M = 150.0
    cell_deg = 0.0015  # ~167m lat; lng slightly less at 50.8°N — close enough
    by_cell: dict[tuple[int, int], list[dict]] = {}
    for r in rows:
        if r.get("lat") is None or r.get("lng") is None:
            continue
        cx, cy = int(r["lat"] / cell_deg), int(r["lng"] / cell_deg)
        by_cell.setdefault((cx, cy), []).append(r)

    geo_pairs: list[tuple[dict, dict]] = []
    for (cx, cy), bucket in by_cell.items():
        neighbourhood = list(bucket)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == dy == 0:
                    continue
                neighbourhood.extend(by_cell.get((cx + dx, cy + dy), []))
        for a in bucket:
            for b in neighbourhood:
                if str(a["id"]) >= str(b["id"]):
                    continue
                if haversine_m(a["lat"], a["lng"], b["lat"], b["lng"]) <= GEO_BLOCK_M:
                    geo_pairs.append((a, b))
```

and include the geo pairs in the dedup loop by iterating `(*by_token.values(), *by_key_prefix.values(), *by_domain.values())` as before, then appending a final loop over `geo_pairs` that applies the same `seen` dedup.

- [ ] **Step 4: Scored dry-run output + enqueue score**

In `backend/scrapers/match.py` `run_sync`:

1. In the main pair loop, compute `total, contributions = matching.evidence_score(features)` right after `score_pair`, and:
   - append `"score": round(total, 2), "contributions": {k: round(v, 2) for k, v in contributions.items()}` to each proposal dict;
   - change both `db.enqueue_decision(... score=float(features.name_sim) ...)` calls (main loop) and the two in the re-score pass to `score=float(total)` (re-score pass computes its own `total` the same way).
2. Before writing the dry-run JSON, sort: `proposals.sort(key=lambda p: p["score"], reverse=True)`.
3. Add a near-miss capture for calibration — in the main loop, when `decision == Decision.SEPARATE` and `0.5 <= total < QUEUE_BAND`, append to a `near_misses` list (same shape as proposals, capped at 50); include `"near_misses": near_misses` in the dry-run JSON payload.

- [ ] **Step 5: Full suite green**

Run: `cd backend && uv run pytest -q 2>&1 | tail -5`
Expected: all pass

---

### Task 9: Prod dry-run + calibration report

**Files:** none modified (operational step)

- [ ] **Step 1: Deploy to server (no commit needed for dry-run? — NO: deploy requires git)**

This step needs the code on the server. **Stop and ask the user to review + commit first** (user commits manually), then:

```bash
ssh -i ~/.ssh/id_ed25519_forkeur root@178.104.57.72 "cd /opt/forkeur && git pull && systemctl restart forkeur-backend"
```

- [ ] **Step 2: Trigger dry-run**

Authenticate and trigger via API (ADMIN_PASSWORD in `/opt/forkeur/backend/.env` on the server):

```bash
ssh -i ~/.ssh/id_ed25519_forkeur root@178.104.57.72 '
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H "Content-Type: application/json" -d "{\"password\":\"$(grep ^ADMIN_PASSWORD /opt/forkeur/backend/.env | cut -d= -f2)\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)[\"token\"])")
curl -s -X POST localhost:8000/api/scrapers/match/run -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"target\":\"dry-run\"}"'
```

Wait for completion (check `/opt/forkeur/backend/match_output/` for the newest `dry-run-*.json`).

- [ ] **Step 3: Present full proposal list to the user**

Fetch the newest dry-run JSON, format every auto_merge + queue proposal (+ near-misses) with names, score, and top contributions. **Do not execute a live run without explicit user confirmation of the list.**

---

## Verification checklist

- [ ] `cd backend && uv run pytest -q` — fully green
- [ ] Golden contract: every `same` ≥ QUEUE, every `different` never AUTO
- [ ] Prod dry-run proposals reviewed by user before any live merge
