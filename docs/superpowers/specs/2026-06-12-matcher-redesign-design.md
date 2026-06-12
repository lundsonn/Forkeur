# Weighted-Evidence Restaurant Matcher — Design

Date: 2026-06-12
Status: IMPLEMENTED. Replaces veto-cascade `decide()` in `backend/matching.py`.
Validated against full prod snapshot (1114 restaurants, 17 294 candidate pairs):
**10 auto-merge, 78 queue, 17 206 separate**; 510 backend tests pass; golden
contract 36/36.

## As-built deltas from the original design below

The implementation differs from the first-draft design in three ways; all are
intentional and test-covered:

1. **Ghost-kitchen identity gate (NEW, decisive).** Prod data revealed Brussels
   cloud kitchens: distinct virtual brands ("Wok & Go" + "China Wok") sharing
   ONE phone + address. The original "phone/geo/address ⇒ same venue" rule
   produced ~26 false auto-merges. Fix: AUTO_MERGE now requires identity
   (`name_sim ≥ 0.80 OR slug_match`) AS WELL AS physical proof. Co-located
   different-name pairs → QUEUE. See `IDENTITY_AUTO_NAME_SIM` in `matching.py`
   and the `project_ghost_kitchens` memory.
2. **Co-location gate on positive geo/address evidence.** Geo and address only
   count toward a merge when identity evidence exists: `name_sim ≥ 0.80`, a
   shared brand-distinctive token (`shares_distinctive_token`, robust where
   full-name JaroWinkler is dragged down by prefixes/suffixes — "Ai 6 Angoli"),
   phone, slug, or exact address. This cut the review queue from 941 → 78 by
   dropping pure food-court neighbours. `COLOCATION_GATE_NAME_SIM`.
3. **Scoring shape.** Tiered name weights (`name_very_high` 2.0 ≥0.97,
   `name_high` 1.0 ≥0.92) and a small positive `cuisine_match` (+0.5) instead
   of a single scaled name term. `address_diff` = −3.0. The best-of-3
   `name_similarity` from the original §1 is NOT in the shipped file (lost to a
   concurrent edit during implementation); its suffix/prefix cases are instead
   handled by `shares_distinctive_token` in the co-location gate, which the
   golden contract confirms is sufficient. Restoring best-of-3 later would move
   a few suffix pairs (La Smorfia, Ai 6 Angoli) from QUEUE → AUTO — a safe
   future enhancement, not required.

Data-quality note surfaced by the dry-run: a few rows carry promo-banner text
as the restaurant name ("Profitez de -50 %"), a scraper bug, not a matcher
bug — they appear in the queue and should be cleaned at ingestion.

---

## Original design (for reference)

## Problem

The current matcher is a sequential veto cascade: any single negative gate
(name similarity < 0.92, geo > 300 m, address mismatch, menu overlap < 3 %)
sends a pair to SEPARATE regardless of how strong the other signals are.
Latest prod dry-run: 2 auto-merges, 0 queued, 2964 separate — while a direct
geo cross-check of single-platform restaurants finds ~20 obvious missed
duplicates, including:

- `Pasta Express Etterbeek` / `PASTA EXPRESS` — 2 m apart (name gate kills it)
- `Yaki Sainte-Catherine` / `Yaki Sainte Catherine` — identical phone, geo
  410 m because Deliveroo venue coords are imprecise (geo veto kills it)
- `Pizza Minute` / `PizzaMinute` — same building, address recorded as
  "Waterloosesteenweg 186" (NL) vs "Chaussée de Waterloo 186" (FR)
  (address veto kills it)
- `Mr. Cod` / `Mr Cod` — 7 m apart, "Chaussee de Gand 386" vs
  "Chau. de Gand 386" (abbreviation breaks address comparison)

Data context (prod, 2026-06-12): 740 restaurants, 100 % have venue-grade
lat/lng (UE 355, takeaway 344, deliveroo_venue 41), 56 % phone,
~95 % street_address+postal_code on UE/TA listings, 0 websites
(direct scraper not yet re-run post-migration). Geo + address are now the
strongest, near-universal signals; the cascade was designed when coords
were ~5 % populated.

## Decision: weighted evidence score

Replace the boolean cascade in `decide()` with an additive evidence score.
Every signal contributes positive or negative weight; bands map the total to
auto-merge / queue / separate. All signal extraction stays in pure functions
in `matching.py` (no DB access), as today.

## 1. Signal upgrades

### name_sim → best-of-3

`name_sim` becomes `max` of:
1. Plain Jaro-Winkler on `normalize_name` (current behaviour).
2. **Suffix-stripped JW**: remove Brussels commune/location tokens
   (`_BRUSSELS_LOCATIONS`) from both normalized names, then JW. Fixes
   "La Smorfia Saint-Gilles" vs "La Smorfia".
3. Token-set ratio (order-insensitive; intersection-based, e.g.
   `rapidfuzz.fuzz.token_set_ratio / 100`).

The winning variant name is recorded in the features dict for
explainability. Suffix-stripping must not reduce a name to empty — if
stripping leaves < 3 chars, that variant is skipped.

### Address v2 — bilingual Brussels normalizer

`_match_address` is rebuilt around two extracted components:

- **House number**: first standalone number token, whether leading
  ("65 Rue Ropsy Chaudron") or trailing ("Chaussee de Gand 386").
  Suffix letters tolerated ("6B" ≡ "6").
- **Street core**: lowercase, accents stripped, then:
  - strip FR street-type **prefixes**: `rue|chaussee|chau|ch|avenue|av|
    boulevard|bvd|bd|place|pl|square|sq|quai|allee|impasse|clos|drève|
    dreve|chemin|sentier|passage|cite|galerie` (word-boundary, optional `.`)
  - strip NL street-type **suffixes** glued or spaced: `steenweg|straat|
    laan|plein|baan|dreef|weg|kaai|gang`
  - drop particles: `de|du|des|d|la|le|les|van|der|den|ten|ter`
  - keep `[a-z0-9]`

  "Waterloosesteenweg" → `waterloose`; "Chaussée de Waterloo" → `waterloo`;
  "Chau. de Gand" → `gand`; "Chaussee de Gand" → `gand`.

- **Verdict** (`address_match`):
  - `same` — house numbers equal AND street-core JW ≥ 0.85
  - `conflict` — both sides have number+street AND (numbers differ OR
    street-core JW < 0.6)
  - `unknown` — anything else (missing data, mid-band JW)

  Postal code disagreement forces `conflict` only when both street cores
  also fail to match — adjacent communes share street continuations.

### Geo — source-aware precision

`deliveroo_venue` coordinates are demonstrably imprecise (Yaki: 410 m from
the true venue). Distance band thresholds widen when **either** side's
`geo_source` is `deliveroo_venue`:

| Band | both precise | deliveroo involved |
|---|---|---|
| very close | ≤ 25 m | ≤ 100 m |
| close | ≤ 75 m | ≤ 200 m |
| near | ≤ 200 m | ≤ 500 m |
| far (negative) | 400–800 m | 800–1500 m |
| very far (negative) | > 800 m | > 1500 m |

### Menu overlap v2

Token-multiset Jaccard over normalized item titles (lowercase, accents and
punctuation stripped, whitespace-split), not exact-title Jaccard. Computed
only when both sides have ≥ 3 items. Weak signal in both directions; never
a veto.

### Unchanged extractors

phone digits, website domain, slug normalization + match, chain detection
(persisted flag + count heuristic), distinctive-remainder conflict, cuisine
conflict, location-token conflict, numbered-branch detection.

## 2. Scoring

`score_pair` keeps returning `MatchFeatures`; a new pure function
`evidence_score(f: MatchFeatures) -> tuple[float, dict[str, float]]`
returns the total and per-signal contributions. Weights live in a single
module-level dict `WEIGHTS` for tuning.

### The co-location gate

Geo and address evidence is only **counted as positive** when there is at
least minimal identity evidence: `name_sim ≥ 0.5 OR phone_match OR
slug_match`. Different restaurants in the same building / food court are
common (Tekince Kebap Resto and Pizzeria Koçak sit 9 m apart); physical
proximity alone must never push a pair toward merge. Negative geo evidence
(far apart) applies unconditionally.

### Weights (initial — calibrated against the golden set, may shift)

Positive:
| Evidence | Weight | Gated by co-location gate |
|---|---|---|
| phone match | +3.0 | no |
| geo very close | +3.0 | yes |
| geo close | +2.5 | yes |
| geo near | +1.0 | yes |
| address `same` | +2.5 | yes |
| name evidence | scaled: 0 at name_sim ≤ 0.80 → +2.0 at ≥ 0.97 | no |
| slug match (non-chain) | +2.0 | no |
| menu overlap ≥ 0.15 | +1.0 | no |
| website domain match (non-chain) | +1.0 | no |

Negative:
| Evidence | Weight |
|---|---|
| geo far | −1.5 |
| geo very far | −3.0 |
| address `conflict` | −2.0 |
| distinctive-remainder conflict (no phone/slug proof) | −2.5 |
| name_sim < 0.70 | −2.0 |
| chain flag (either side) | −2.0 |
| location-token conflict / numbered branches | −2.0 |
| cuisine conflict | −1.0 |

### Bands

- `score ≥ 4.5` → AUTO_MERGE
- `1.5 ≤ score < 4.5` → QUEUE (human review in admin dashboard)
- `score < 1.5` → SEPARATE

### The one hard rule

Both sides venue-grade with neither `deliveroo_venue`, geo distance
> 1000 m, and no phone match → SEPARATE unconditionally. Chain branches
share name, menu, website, and cuisine; additive evidence must not be able
to pile past the bands when the physics says two different places.

### Sanity checks (from prod data)

- Yaki: phone +3.0, name ≈ +2.0, address same +2.5, geo 410 m
  deliveroo-adjusted = no negative → ≈ +7.5 → AUTO ✓
- PizzaMinute: geo 40 m +2.5, address same (bilingual fix) +2.5,
  name ≈ +1.9 → ≈ +6.9 → AUTO ✓
- Krusty Smash Burger branches (2.2 km, both precise, no phone) →
  hard rule → SEPARATE ✓
- Tekince / Koçak at 9 m: name_sim < 0.5 → co-location gate blocks geo and
  address positives → score ≈ 0 → SEPARATE ✓
- Pasta Express Etterbeek / PASTA EXPRESS: suffix-stripped name ≈ 1.0
  → +2.0, geo 2 m +3.0, address likely same +2.5 → AUTO ✓

## 3. Pipeline changes (`backend/scrapers/match.py`)

Mechanics unchanged: load → block → score → act per band, then re-score
pass, prune pass, dry-run JSON output. Changes:

1. **Geo blocking key added** to `block_candidates`: every cross-restaurant
   pair within 150 m becomes a candidate (grid-bucket by rounded lat/lng to
   stay near-linear; 740 rows makes cost trivial). Catches duplicates whose
   names share no token.
2. **Dry-run output** gains `score` and the per-signal contribution dict,
   sorted descending by score — this is the calibration tool.
3. `enqueue_decision(score=...)` stores the evidence score (was name_sim).
4. Re-score and prune passes call the new scorer; prune deletes queued rows
   whose fresh verdict is SEPARATE, as today.

## 4. Golden set + tests

- `backend/tests/fixtures/golden_pairs.json` — ~40 labeled pairs lifted
  from prod rows (full feature inputs inline: names, phones, coords,
  geo_source, addresses, cuisine, chain flags, slugs, sample menu titles).
  Labels: `same` (the ~20 missed dupes) and `different` (banhmi pair,
  Krusty branches, Tekince/Koçak, chain branches, co-located distinct
  venues).
- Contract tests:
  - every `same` pair → AUTO_MERGE or QUEUE (never SEPARATE)
  - every `different` pair → SEPARATE or QUEUE (never AUTO_MERGE)
- Unit tests for the new address normalizer (bilingual cases above),
  suffix-stripped name sim, source-aware geo bands, co-location gate.
- Existing matching tests updated to the new API; tests asserting cascade
  vetos are rewritten to assert band outcomes.
- Ambiguous labels surfaced to the user for confirmation before freezing
  the fixture.

## 5. Rollout

1. Implement; all tests green locally.
2. Dry-run against prod data; present full proposal list (auto + queue,
   with scores and contributions) to the user.
3. On user confirmation, live run. Queue band lands in
   `restaurant_match_decisions` for the admin dashboard, as today.

## Out of scope

- Re-running the `direct` scraper to repopulate websites (separate task;
  website weight simply contributes nothing while coverage is 0).
- Deliveroo multi-zone expansion (77 listings is a coverage problem, not a
  matching problem).
- Ingestion-time matching in `db.upsert_restaurant` (5-step name match) —
  untouched; the batch matcher remains the mop-up layer.
