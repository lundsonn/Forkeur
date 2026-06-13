# Forkeur — Todo

## Backlog

<!-- Add tasks here. Format: `- [ ] Task description` -->

### Direct ordering pipeline (post website_finder, 2026-06-13)
- [x] **website_finder** — DONE. All 2010 restaurants searched; 1159 with website.
- [x] **Nominatim field fix** — DONE. Was `city_district`/`suburb`/`municipality`; Brussels returns `town`. Fixed to include `town`/`city`.
- [x] **Re-run direct scraper Phase 3** — DONE. All 2010 restaurants geocoded; 0 null neighborhoods.
- [x] **website_finder concurrency** — DONE. `_CONCURRENCY = 2` in `website_finder.py` (safe under ~1.5GB).
- [x] **Run direct_menu scraper** — N/A. 0 `url_type=ordering` listings exist; all 1079 are `website|menu` type.
- [x] **Run dom_menu scraper** — DONE. 8097 menu items scraped today (2026-06-13); all 1079 direct listings fresh.

### Scraper run optimization — option B (cheap wins, after A done)
- [x] **Staleness skip** — DONE. `db.get_stale_listing_ids()` batch-queries `last_scraped_at`; ube/del filter `saved_listings`/`saved` before Phase 2 via `asyncio.to_thread`.
- [x] **Lower dom_menu sem 8→5** — DONE. Was the batch RAM driver (8 pages overlapping ube/del menu workers → peak 6.7GB/1.1GB free). Now sem=5 frees ~1.5GB at overlap.
- [x] **Tighten scroll waits** — DONE. UberEats 1.2s→0.6s (lines 274, 432); Deliveroo 0.8s→0.6s (line 488).

Context: batch wall = slowest scraper. A (parallelize ube/del menu loop) = big win (33min→~8min). B = polish on top.

### Deliveroo Phase 0 zone scan (found during A validation)
- [x] **Parallelize the 16-zone listing scan** — DONE. `asyncio.Semaphore(ZONE_WORKERS=4)` + `asyncio.gather()` in deliveroo.py.

### Matcher improvements (2026-06-05 analysis)

- [x] **[deliveroo.py] Fix Deliveroo geo** — DONE. `deliveroo_venue` geo source implemented; venue coords extracted via JSON-LD/__NEXT_DATA__ from menu pages.
- [x] **[matching.py] Add cuisine veto** — DONE. `_cuisine_conflict()` + `cuisine_conflict` in `decide()`.
- [x] **[matching.py] Add postal code / neighborhood blocking** — DONE. `_location_tokens()` + `location_conflict` in `decide()`.
- [x] **[matching.py] Improve phone coverage** — phone sparsely populated; phone match rarely fires. Investigate enriching `restaurants.phone` from scraper data (UberEats/Deliveroo API responses often include contact info).

### Menu matching improvements

- [x] **[all scrapers + models.py] Scrape allergens** — Deliveroo only (275 items via `dietaryTags`). UberEats BE API has no `dietaryInfo` field (US-only). Takeaway DOM scraper has no dietary selectors. direct_menu APIs (sq-menu/Odoo/piki) have no allergen fields. Matching guard in `queries.ts` lines 403-406 already implemented.

---

## Profiling Fixes (50 findings — 2026-06-05)

### 🔴 HIGH — Convergent (2+ agents)

- [x] **[db.py:85-195] upsert_restaurant full-table-scan** — DONE. `_domain_cache` module-level dict, loaded once per run, invalidated on website patch.
- [x] **[matching.py:129] score_pair re-normalizes names every pair** — DONE. `@lru_cache(maxsize=None)` on `normalize_name`, `normalize_match_key`, `domain_of`, `phone_digits`; cache warmed in `run_sync`.

### 🔴 HIGH — Single-agent

- [x] **[routers/scrapers.py:44-137] TOCTOU race on `_running`** — DONE. `_state_lock` + synchronous `_running.add` before `create_task`.
- [x] **[scheduler.py:31-74] Scheduled runs invisible to stop endpoint** — DONE. `_running.add/discard` + `_tasks[platform] = asyncio.current_task()` in try/finally.
- [x] **[db.py:305-320] get_last_run_per_platform 8 sequential round-trips** — DONE. Single `.in_()` + `.limit(140)` query.
- [x] **[db.py:107-129] _found re-SELECTs already-fetched row** — DONE. `_found()` accepts optional `row` param; caller passes fetched row directly.

### 🟡 MED — UberEats

- [x] **[ubereats.py:692-721] `import re` inside parse fns** — DONE. Moved to module top.

### 🟡 MED — Deliveroo


### 🟡 MED — base.py

### 🟡 MED — dom_menu / direct_menu

- [x] **[generic.py:195] Unconditional `sleep(2)` per site** — DONE. `wait_for_load_state("networkidle", timeout=5000)` + 0.3s fallback.
- [x] **[generic.py:191] `block_media=False`** — DONE. Flipped to True. Heuristic is text-based DOM traversal (no bounding-box calls); comment was misleading.
- [x] **[direct_menu.py:438-474] Entire `run()` synchronous serial httpx** — DONE. Async + `Semaphore(10)` + `asyncio.to_thread` per listing.

### 🟡 MED — matching / db (matcher path)

- [x] **[matching.py:196-216] Repeated `_canonical`/`_strip_accents` + per-pair tuple alloc** — DONE. lru_cache on normalize_name covers this.
- [x] **[db.py:198-213] upsert_listing SELECT-then-UPDATE/INSERT** — DONE. Atomic `.upsert(on_conflict="restaurant_id,platform")`.
- [x] **[db.py:580-605] enqueue_decision read-modify-write per pair** — DONE. Atomic PostgREST upsert with `.or_()` for unordered-pair matching.
- [x] **[match.py:61-75] Auto-merge 200×(5-9) = 1000-1800 round-trips** — DONE. Decisions batched before merge loop; single pass per pair.

### 🟡 MED — routers / scheduler / main

- [x] **[routers/scrapers.py:125-133] open+write+close per log line** — DONE. `_log_fh` opened once, `flush()` per write, closed in finally.
- [x] **[routers/scrapers.py:149-151] `inspect.signature` per invocation in retry loop** — DONE. Precomputed before loop.
- [x] **[routers/scrapers.py:213-226] /health 3 sequential get_last_successful_run** — DONE. `get_last_successful_run_batch()` single query.
- [x] **[routers/data.py:24-26] /match-queue unbounded, sync on event loop** — DONE. limit/offset params + `asyncio.to_thread()` applied.
- [x] **[scheduler.py:259-260] shutdown(wait=False) orphans Playwright procs** — DONE. `wait=True`.
- [x] **[db.py:400-420] get_restaurants no order() + get_menu_items no limit** — DONE. `order("id")` + `.limit(2000)`.
- [x] **[main.py:24-41] AuthMiddleware sync `verify_token` per request** — Confirmed CPU-only (HMAC-SHA256 via PyJWT, <1ms). No change needed.

### 🟢 LOW — Quick wins / cleanup

- [x] **[ubereats.py:727-809] `_parse_ue_menu` dead code** — DONE. Deleted.
- [x] **[ubereats.py:94-107] feed_pages accumulates 4-10MB raw JSON** — DONE. Extracts only feedItems in `on_response`.
- [x] **[base.py:148-158] `_move_mouse_human` up to 1575 CDP round-trips** — DONE. Uses `page.mouse.move(x,y,steps=N)`.
- [x] **[base.py:215-266] `_browser_lock` lazy-init race** — DONE. `asyncio.Lock()` at module level.
- [x] **[db.py vs matching.py] `_canonical` duplicated with divergence** — DONE. db.py `_canonical` now matches matching.py: strips city noise + halal/bio/vegan labels; uses compiled `_SUFFIX_RE`.
- [x] **[ubereats.py] Polling `asyncio.sleep(0.1)`** — DONE. All 3 sleep-poll loops (`feed_pages`, `store_raw`, `retry_buf`) replaced with `asyncio.Event` + `await event.wait()`.
- [x] **Dead piki host 15s timeout** — DONE. `httpx.Timeout(connect=3.0, read=8.0)` fast-fails on dead DNS.
- [x] **Unused Odoo `image_128` base64 payload** — DONE. Removed from `_ODOO_PRODUCT_PAYLOAD` fields list.
- [x] **Hardcoded Brussels constant** — Already extracted: `DEFAULT_ADDRESS` in `constants.py`; `ScraperConfig` defaults to it.

