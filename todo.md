# Forkeur — Todo

## Backlog

<!-- Add tasks here. Format: `- [ ] Task description` -->

### Scraper run optimization — option B (cheap wins, after A done)
- [ ] **Staleness skip** — skip restaurants whose menus updated <12-24h ago (cuts 2nd daily batch to near-zero re-scrape)
- [x] **Lower dom_menu sem 8→5** — DONE. Was the batch RAM driver (8 pages overlapping ube/del menu workers → peak 6.7GB/1.1GB free). Now sem=5 frees ~1.5GB at overlap.
- [ ] **Tighten scroll waits** — ube/del menu scroll sleep 1.2s→0.6s, fewer iterations (~15-20% per restaurant; watch missed lazy cards)

Context: batch wall = slowest scraper. A (parallelize ube/del menu loop) = big win (33min→~8min). B = polish on top.

### Deliveroo Phase 0 zone scan (found during A validation)
- [ ] **Parallelize the 16-zone listing scan** — currently sequential (`for zone_address in zones` in deliveroo.run, ~7min before menus even start). Each zone is independent (own page, dedup by slug after). Run N zones concurrently like the menu workers → ~7min → ~2min. Now the dominant deliveroo cost since menus are parallel.

### Matcher improvements (2026-06-05 analysis)

- [ ] **[deliveroo.py] Fix Deliveroo geo** — scraper stores zone centroid, not venue coords → `geo_source='deliveroo'` excluded from geo scoring → ~40% of listings can't confirm/veto via distance. Investigate if Deliveroo API response contains venue lat/lng; store it + set `geo_source='deliveroo_venue'`. Biggest single matcher improvement.
- [ ] **[matching.py] Add cuisine veto** — cuisine stored in features JSONB but never used in `decide()`. "Sushi Palace" (sushi) vs "Sushi Palace" (pizza) → false merge. Add: if both have cuisine and cuisines don't overlap → SEPARATE.
- [ ] **[matching.py] Add postal code / neighborhood blocking** — common names like "Le Grill" can appear across Brussels. Block or veto by arrondissement/postal code to cut false positives.
- [ ] **[matching.py] Improve phone coverage** — phone sparsely populated; phone match rarely fires. Investigate enriching `restaurants.phone` from scraper data (UberEats/Deliveroo API responses often include contact info).

---

## Profiling Fixes (50 findings — 2026-06-05)

### 🔴 HIGH — Convergent (2+ agents)

- [ ] **[db.py:85-195] upsert_restaurant full-table-scan** — Step 2b fetches all non-null-website restaurants, Python domain-compares. 500 restaurants × 7 round-trips = 3500/run. Fix: Postgres generated domain column + unique index; batch-load into in-memory dict once per run. [Agents C+D]
- [ ] **[ubereats/deliveroo/direct_menu/db.py] N+1 DB writes** — serial upsert per restaurant (600+ trips/200 rest); `prune_stale_menu_items` N+1 delete loop blocks event loop (201 trips); `merge_restaurants` one UPDATE per listing. Fix: bulk `.upsert(list)` / single `.in_()` delete; wrap sync DB in `asyncio.to_thread`. [Agents A,B,D]
- [ ] **[matching.py:129] score_pair re-normalizes names every pair** — 50 pairs = 50× wasted normalization. Fix: precompute `_norm_name`/`domain_of`/`phone_digits` in `block_candidates`. [Agent C]

### 🔴 HIGH — Single-agent

- [ ] **[routers/scrapers.py:44-137] TOCTOU race on `_running`** — 409 guard checks `_running` but `.add` happens inside task body across `await` → double-launch possible. Fix: `_running.add` synchronously in handler before `create_task`.
- [ ] **[scheduler.py:31-74] Scheduled runs invisible to stop endpoint** — `_run_scraper` never calls `_running.add/discard` → status shows "idle". Fix: add/discard in try/finally; store task in `_tasks`.
- [ ] **[db.py:305-320] get_last_run_per_platform 8 sequential round-trips** — 160-400ms per `/status` poll. Fix: single `GROUP BY MAX` or `.in_()` + reduce.
- [ ] **[odoo_pos.py:67-84] on_response race** — fires per sub-resource; `done.is_set()` race before json decode. Fix: re-check before decode.
- [ ] **[db.py:107-129] _found re-SELECTs already-fetched row** — up to 6 extra trips. Fix: reuse fetched row.

### 🟡 MED — UberEats

- [ ] **[ubereats.py:300-311] 3 separate writes/restaurant** — no cross-worker batch. Fix: composite batched helper.
- [ ] **[ubereats.py:692-721] `import re` inside parse fns** — per-call `sys.modules` lookup. Fix: move to module top.
- [ ] **[ubereats.py:211-246] scroll loop 18s/restaurant** — card already in DOM from prior worker. Fix: full scroll once on worker open/recycle.

### 🟡 MED — Deliveroo

- [ ] **[deliveroo.py:371-384] Triple sequential nav waits** — ~90s worst-case/restaurant. Fix: single `wait_for_selector('div.notranslate')`.
- [ ] **[deliveroo.py:403-413] Two sequential scroll loops** — ~60s/restaurant. Fix: unify, event-driven.
- [ ] **[deliveroo.py:539-622] 3 separate full DOM walks** — items, fee×2, promos = 3 CDP round-trips. Fix: merge into one `page.evaluate()` returning `{items, fee_text, promo_texts}`.

### 🟡 MED — base.py

- [ ] **[base.py:100-122] new_page creates new browser context per call** — cookie jar + V8 isolate + stealth scripts; 30+ creations/Deliveroo run. Fix: one context per worker, multiple pages.
- [ ] **[base.py:113-121] media-block route = Python lambda per resource** — Fix: `--blink-settings=imagesEnabled=false` flag or explicit-extension route.

### 🟡 MED — dom_menu / direct_menu

- [ ] **[generic.py:195] Unconditional `sleep(2)` per site** — 894s across 447 sites. Fix: `wait_for_load_state("networkidle", 5000)`.
- [ ] **[generic.py:191] `block_media=False`** — loads unused images. Fix: flip True.
- [ ] **[direct_menu.py:438-474] Entire `run()` synchronous serial httpx** — Odoo 35s timeout blocks thread. Fix: async + AsyncClient + Semaphore(10).
- [ ] **[odoo_pos.py:86-91] 12s unconditional wait on dead SPA** — remove/replace with networkidle.

### 🟡 MED — matching / db (matcher path)

- [ ] **[matching.py:196-216] Repeated `_canonical`/`_strip_accents` + per-pair tuple alloc** — precompute.
- [ ] **[db.py:198-213] upsert_listing SELECT-then-UPDATE/INSERT** — Fix: `.upsert(on_conflict=...)`.
- [ ] **[db.py:580-605] enqueue_decision read-modify-write per pair** — Fix: batch.
- [ ] **[match.py:61-75] Auto-merge 200×(5-9) = 1000-1800 round-trips** — Fix: bulk operation.

### 🟡 MED — routers / scheduler / main

- [ ] **[routers/scrapers.py:125-133] open+write+close per log line** — 500 lines = 1500 syscalls; /tmp logs accumulate. Fix: open once, close in finally.
- [ ] **[routers/scrapers.py:149-151] `inspect.signature` per invocation in retry loop** — Fix: precompute.
- [ ] **[routers/scrapers.py:213-226] /health 3 sequential get_last_successful_run** — Fix: single `.in_()`.
- [ ] **[routers/data.py:24-26] /match-queue unbounded, sync on event loop** — Fix: limit/offset + `to_thread`.
- [ ] **[scheduler.py:259-260] shutdown(wait=False) orphans Playwright procs** — stuck `status="running"` rows. Fix: `wait=True` or cancel `_tasks` first.
- [ ] **[db.py:400-420] get_restaurants no order() + get_menu_items no limit** — non-deterministic pagination; 60KB+ payloads.
- [ ] **[db.py:9-18] Supabase singleton httpx pool never closed, not thread-safe init** — Fix: `db.close()` in lifespan.
- [ ] **[main.py:24-41] AuthMiddleware sync `verify_token` per request** — Fix: confirm CPU-only or move to `to_thread`.

### 🟢 LOW — Quick wins / cleanup

- [ ] **[ubereats.py:727-809] `_parse_ue_menu` dead code** — ~80 lines; live path is `_parse_menu_items`. Delete.
- [ ] **[ubereats.py:94-107] feed_pages accumulates 4-10MB raw JSON** — Fix: parse in `on_response`, discard.
- [ ] **[base.py:148-158] `_move_mouse_human` up to 1575 CDP round-trips** — Fix: built-in `page.mouse.move(x,y,steps=N)`.
- [ ] **[base.py:215-266] `_browser_lock` lazy-init race** — Fix: init `asyncio.Lock()` at import.
- [ ] **[db.py vs matching.py] `_canonical` duplicated with divergence** — db normalizes apostrophes, matching doesn't → correctness risk. Fix: shared module.
- [ ] **[ubereats:66-68,284,451] Polling `asyncio.sleep(0.5)` + deprecated `get_event_loop().time()`** — Fix: `asyncio.Event` + `wait_for`.
- [ ] **Dead piki host 15s timeout** — replace with fast-fail.
- [ ] **Unused Odoo `image_128` base64 payload** — drop from parse.
- [ ] **Hardcoded Brussels constant [scheduler:77-84]** — extract to config.

