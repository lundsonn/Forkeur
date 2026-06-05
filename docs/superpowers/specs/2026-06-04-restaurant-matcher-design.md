# Geo + Website Scored Restaurant Matcher — Design

**Date:** 2026-06-04
**Status:** Approved (design); pending implementation plan

## Problem

Cross-platform restaurant matching is **name-only**. `db.upsert_restaurant`
([backend/db.py:85](../../../backend/db.py)) runs 5 escalating string steps
(exact → case-insensitive → canonical → suffixed → normalized). It uses no geo,
website, phone, or address even though those columns exist.

Two failure modes name-only cannot solve:

1. **False splits** — same venue, punctuation / whitespace / word-order drift.
   Measured: **26 colliding keys / 52 rows** that aggressive normalization merges
   but the live matcher missed (`Pizza minute` ≠ `PizzaMinute`, `Mr Cod` ≠
   `Mr. Cod`, `Pizza & Go` ≠ `Pizza&Go`). Each split renders a restaurant as two
   cards → breaks the core price-compare feature.
2. **False merges** — chains. `Burger King - Ixelles` vs `Burger King - Jette`
   are two real venues under one name; canonical-base matching (step 3/4) would
   wrongly merge them.

Current state: 1347 restaurants — 727 single-platform (54%), 444 two, 134 three,
42 four. Many singletons are genuine (direct-only Maps discoveries); an unknown
slice are missed cross-platform matches.

## Signal availability (measured, not assumed)

| Platform | Venue-grade geo? | Evidence |
|----------|------------------|----------|
| UberEats | **Yes** | 597 geo / 516 distinct points (~1.15/pt) — true per-venue |
| Direct (Maps) | **Yes** | Google Maps venue coords |
| Deliveroo | **No** | 412 geo / **124 distinct points** (~3.3/pt) — URL geohash is the *delivery-zone centroid*, not the venue |
| Takeaway | **No** | scraper captures name/slug/image only |

Column fill across all 1347: `lat` 868, `website` 498, `phone` 53.

**Consequence:** geo is a *confirming/vetoing* signal only when **both** sides are
venue-grade (UberEats/Direct). It can never be a blocking requirement, and
Deliveroo/Takeaway coords must be ignored for matching.

## Decisions (locked during brainstorming)

- **Uncertain handling:** hybrid — strong confirming signal → auto-merge;
  name-only / mid-confidence → review queue; geo-conflict / weak → keep separate.
  Every decision is logged. Never guess live.
- **When matching runs:** hybrid — inline keeps only *deterministic* safe locks
  (exact-normalized name, exact website domain) so the live site stays coherent
  with no parallel-scraper race; all fuzzy/geo scoring moves to a re-runnable
  **batch job**.
- **Backfill:** dry-run first. First batch pass over all 1347 runs report-only,
  output reviewed, then executed. Dry-run is a permanent flag for future tuning.

## Architecture

```
SCRAPE TIME (inline — fast, deterministic only)
  upsert_restaurant:
    exact-normalized-name lock  OR  exact-website-domain lock  (no geo veto)
      hit  → attach listing to existing restaurant
      miss → insert new row   (NO fuzzy guessing inline)

BATCH (`match` job — after scrape cycle or on-demand, re-runnable)
  for each restaurant R:
    candidates = block(name-prefix ∪ normalized-key ∪ geo-cell)
    for each candidate C: score(R, C) → decision
       deterministic lock / strong signal → auto-merge   (log)
       name-only / mid                      → review queue (log)
       weak / geo-veto                      → separate     (log)
  --dry-run: write proposed merges + queue rows to file; ZERO DB writes
```

Scoring core = **pure functions**, no DB, fixture-testable. DB I/O isolated in
`db.py`.

## Scoring model

For a pair (A = existing, B = candidate):

| Signal | Effect | Caveat |
|--------|--------|--------|
| **name_sim** | strip-all-punct + token-sort normalize → Jaro-Winkler / Levenshtein ratio | catches the 26 splits + typos/word-order |
| **website domain** exact | strong + (lock) | registrable domain only (e.g. `bk.be`) |
| **phone** digits exact | strong + | normalize to digits; strip `+32`/leading 0 |
| **venue-geo < 75 m** | strong + | UberEats + Direct only |
| **venue-geo > 300 m** | **strong − (veto)** | chain-branch guard; both sides venue-grade |
| cuisine match | weak tiebreak | — |

Distance: haversine on lat/lng. Thresholds 75 m / 300 m are starting values,
tunable via the dry-run loop.

### Decision bands

1. **Deterministic lock** (inline + batch): exact-normalized name OR exact
   website domain, AND no geo veto → **auto-merge**.
2. **Auto-merge** (batch): name_sim ≥ HIGH **AND** ≥1 confirming signal
   (website / phone / venue-geo < 75 m), no veto.
3. **Review queue**: name_sim ≥ HIGH but **no** confirming signal (name-only).
   Never auto-merged — could be an ungeolocated chain branch.
4. **Separate**: name_sim < HIGH, or geo veto present.

`HIGH` is a tuned constant (start ~0.92 on normalized Jaro-Winkler).

### Chain guard (false-merge prevention)

- Both sides venue-grade and > 300 m apart → veto, force separate even if names
  identical (`Burger King` Ixelles vs Jette).
- Geo absent on a side (Deliveroo zone-centroid treated as absent; Takeaway none)
  → name-only never auto-merges; routes to queue for human disambiguation.

## Schema

Single table — serves as both review queue and audit log:

```sql
create table restaurant_match_decisions (
  id           uuid primary key default gen_random_uuid(),
  survivor_id  uuid references restaurants(id) on delete cascade,
  loser_id     uuid references restaurants(id) on delete set null,
  score        numeric,
  features     jsonb,          -- per-signal breakdown for audit/tuning
  status       text not null,  -- auto_merged | queued | approved | rejected | separated
  created_at   timestamptz default now(),
  resolved_at  timestamptz,
  resolved_by  text
);
-- RLS on, no anon write policy (service_role bypasses RLS) — per project convention
```

`status` lifecycle: batch writes `auto_merged` (already executed), `queued`
(awaiting human), or `separated` (recorded non-match, suppresses re-queue of the
same pair). Dashboard transitions `queued` → `approved` (triggers merge) or
`rejected`.

## Merge operation (`db.merge_restaurants(survivor_id, loser_id)`)

1. **Survivor selection:** oldest row, tiebreak by most non-null fields.
2. **Move listings:** `platform_listings.restaurant_id` loser → survivor.
   **Conflict** (both have same `platform`): keep the row with newer
   `last_scraped_at`, delete the other. (`menu_items` FK → listing, so they ride
   along untouched.)
3. **Fill nulls:** copy loser → survivor for any null `phone`, `website`, `lat`,
   `lng`, `cuisine`, `image_url`.
4. **Delete loser** row; write/settle the `restaurant_match_decisions` record.

Operation is idempotent-safe: re-running on an already-merged pair is a no-op
(loser already gone).

## Components

1. **Migration** — `restaurant_match_decisions` table (`supabase/migrations/`).
2. **`backend/matching.py`** — pure: `normalize_match_key`, `domain_of`,
   `phone_digits`, `haversine`, `block_candidates`, `score_pair`, `decide`.
3. **`db.py`** — `get_match_candidates`, `merge_restaurants`, `enqueue_decision`;
   tighten `upsert_restaurant` to deterministic locks only.
4. **Batch job** — `backend/scrapers/match.py` (job module) + router
   `POST /api/scrapers/match/run` (`dry_run` param) + scheduler entry.
5. **Dashboard** — review-queue panel: list `queued`, show feature breakdown,
   approve (→ merge) / reject. Minimal.

## Tests (pytest)

- **Scoring unit** with fixture pairs:
  - the 26 real splits → must reach merge/queue (depending on signal).
  - chain branches with geo > 300 m → must veto (separate).
  - name-only no-signal → must queue.
  - typo / word-order variants → high name_sim.
- **Merge integration** including the same-platform-listing conflict edge.
- **Inline lock** test: exact website domain attaches, no fuzzy inline.

## Rollout

1. Migration applied (remote Supabase).
2. Dry-run over all 1347 → review output file.
3. Tune thresholds if needed; re-dry-run.
4. Execute backfill → one-time review-queue spike, resolve in dashboard.
5. Wire scheduler to run `match` after the nightly scrape cycle.

## Frontend impact

Near-zero. `forkeur-app/lib/queries.ts` already groups listings by
`restaurant_id` for the compare view; merges fix cross-platform comparison
automatically. Only new UI is the dashboard review queue (admin, not consumer).

## YAGNI / out of scope

- No ML / embedding similarity — string + geo + exact-id signals suffice for
  Brussels-scale (~1.3k rows).
- No address-string parsing/matching — phone/website/geo cover confirmation.
- No automatic chain-branch *naming* normalization beyond canonical suffix strip.
- Consumer-facing UI unchanged.
