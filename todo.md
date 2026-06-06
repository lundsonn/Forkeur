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

- [x] **[deliveroo.py] Fix Deliveroo geo** — DONE. `deliveroo_venue` geo source implemented; venue coords extracted via JSON-LD/__NEXT_DATA__ from menu pages.
- [x] **[matching.py] Add cuisine veto** — DONE. `_cuisine_conflict()` + `cuisine_conflict` in `decide()`.
- [x] **[matching.py] Add postal code / neighborhood blocking** — DONE. `_location_tokens()` + `location_conflict` in `decide()`.
- [ ] **[matching.py] Improve phone coverage** — phone sparsely populated; phone match rarely fires. Investigate enriching `restaurants.phone` from scraper data (UberEats/Deliveroo API responses often include contact info).

---

## Profiling Fixes (50 findings — 2026-06-05)

### 🔴 HIGH — Convergent (2+ agents)

- [x] **[db.py:85-195] upsert_restaurant full-table-scan** — DONE. `_domain_cache` module-level dict, loaded once per run, invalidated on website patch.
- [ ] **[ubereats/deliveroo/direct_menu/db.py] N+1 DB writes** — `prune_stale_menu_items` N+1 delete loop still pending. `upsert_listing` fixed (atomic upsert). `merge_restaurants` RPC. Still: bulk prune + wrap sync DB in `asyncio.to_thread`.
- [x] **[matching.py:129] score_pair re-normalizes names every pair** — DONE. `@lru_cache(maxsize=None)` on `normalize_name`, `normalize_match_key`, `domain_of`, `phone_digits`; cache warmed in `run_sync`.

### 🔴 HIGH — Single-agent

- [x] **[routers/scrapers.py:44-137] TOCTOU race on `_running`** — DONE. `_state_lock` + synchronous `_running.add` before `create_task`.
- [x] **[scheduler.py:31-74] Scheduled runs invisible to stop endpoint** — DONE. `_running.add/discard` + `_tasks[platform] = asyncio.current_task()` in try/finally.
- [x] **[db.py:305-320] get_last_run_per_platform 8 sequential round-trips** — DONE. Single `.in_()` + `.limit(140)` query.
- [ ] **[odoo_pos.py:67-84] on_response race** — fires per sub-resource; `done.is_set()` race before json decode. Fix: re-check before decode.
- [ ] **[db.py:107-129] _found re-SELECTs already-fetched row** — up to 6 extra trips. Fix: reuse fetched row.

### 🟡 MED — UberEats

- [ ] **[ubereats.py:300-311] 3 separate writes/restaurant** — no cross-worker batch. Fix: composite batched helper.
- [x] **[ubereats.py:692-721] `import re` inside parse fns** — DONE. Moved to module top.
- [ ] **[ubereats.py:211-246] scroll loop 18s/restaurant** — card already in DOM from prior worker. Fix: full scroll once on worker open/recycle.

### 🟡 MED — Deliveroo

- [ ] **[deliveroo.py:371-384] Triple sequential nav waits** — ~90s worst-case/restaurant. Fix: single `wait_for_selector('div.notranslate')`.
- [ ] **[deliveroo.py:403-413] Two sequential scroll loops** — ~60s/restaurant. Fix: unify, event-driven.
- [ ] **[deliveroo.py:539-622] 3 separate full DOM walks** — items, fee×2, promos = 3 CDP round-trips. Fix: merge into one `page.evaluate()` returning `{items, fee_text, promo_texts}`.

### 🟡 MED — base.py

- [ ] **[base.py:100-122] new_page creates new browser context per call** — cookie jar + V8 isolate + stealth scripts; 30+ creations/Deliveroo run. Fix: one context per worker, multiple pages.
- [ ] **[base.py:113-121] media-block route = Python lambda per resource** — Fix: `--blink-settings=imagesEnabled=false` flag or explicit-extension route.

### 🟡 MED — dom_menu / direct_menu

- [x] **[generic.py:195] Unconditional `sleep(2)` per site** — DONE. `wait_for_load_state("networkidle", timeout=5000)` + 0.3s fallback.
- [ ] **[generic.py:191] `block_media=False`** — loads unused images. Fix: flip True. (Kept due to layout comment — verify safe.)
- [x] **[direct_menu.py:438-474] Entire `run()` synchronous serial httpx** — DONE. Async + `Semaphore(10)` + `asyncio.to_thread` per listing.
- [ ] **[odoo_pos.py:86-91] 12s unconditional wait on dead SPA** — remove/replace with networkidle.

### 🟡 MED — matching / db (matcher path)

- [x] **[matching.py:196-216] Repeated `_canonical`/`_strip_accents` + per-pair tuple alloc** — DONE. lru_cache on normalize_name covers this.
- [x] **[db.py:198-213] upsert_listing SELECT-then-UPDATE/INSERT** — DONE. Atomic `.upsert(on_conflict="restaurant_id,platform")`.
- [ ] **[db.py:580-605] enqueue_decision read-modify-write per pair** — Fix: batch.
- [ ] **[match.py:61-75] Auto-merge 200×(5-9) = 1000-1800 round-trips** — Fix: bulk operation.

### 🟡 MED — routers / scheduler / main

- [x] **[routers/scrapers.py:125-133] open+write+close per log line** — DONE. `_log_fh` opened once, `flush()` per write, closed in finally.
- [x] **[routers/scrapers.py:149-151] `inspect.signature` per invocation in retry loop** — DONE. Precomputed before loop.
- [x] **[routers/scrapers.py:213-226] /health 3 sequential get_last_successful_run** — DONE. `get_last_successful_run_batch()` single query.
- [ ] **[routers/data.py:24-26] /match-queue unbounded, sync on event loop** — Fix: limit/offset + `to_thread`.
- [x] **[scheduler.py:259-260] shutdown(wait=False) orphans Playwright procs** — DONE. `wait=True`.
- [x] **[db.py:400-420] get_restaurants no order() + get_menu_items no limit** — DONE. `order("id")` + `.limit(2000)`.
- [ ] **[db.py:9-18] Supabase singleton httpx pool never closed, not thread-safe init** — Fix: `db.close()` in lifespan.
- [ ] **[main.py:24-41] AuthMiddleware sync `verify_token` per request** — Fix: confirm CPU-only or move to `to_thread`.

### 🟢 LOW — Quick wins / cleanup

- [x] **[ubereats.py:727-809] `_parse_ue_menu` dead code** — DONE. Deleted.
- [x] **[ubereats.py:94-107] feed_pages accumulates 4-10MB raw JSON** — DONE. Extracts only feedItems in `on_response`.
- [x] **[base.py:148-158] `_move_mouse_human` up to 1575 CDP round-trips** — DONE. Uses `page.mouse.move(x,y,steps=N)`.
- [x] **[base.py:215-266] `_browser_lock` lazy-init race** — DONE. `asyncio.Lock()` at module level.
- [ ] **[db.py vs matching.py] `_canonical` duplicated with divergence** — db normalizes apostrophes, matching doesn't → correctness risk. Fix: shared module.
- [ ] **[ubereats:66-68,284,451] Polling `asyncio.sleep(0.5)` + deprecated `get_event_loop().time()`** — Fix: `asyncio.Event` + `wait_for`.
- [ ] **Dead piki host 15s timeout** — replace with fast-fail.
- [ ] **Unused Odoo `image_128` base64 payload** — drop from parse.
- [ ] **Hardcoded Brussels constant [scheduler:77-84]** — extract to config.

