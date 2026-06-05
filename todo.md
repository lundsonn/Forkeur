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

