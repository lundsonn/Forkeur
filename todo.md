# Forkeur — Todo

## Backlog

<!-- Add tasks here. Format: `- [ ] Task description` -->

### Scraper run optimization — option B (cheap wins, after A done)
- [ ] **Staleness skip** — skip restaurants whose menus updated <12-24h ago (cuts 2nd daily batch to near-zero re-scrape)
- [ ] **Lower dom_menu sem 8→5** — kills the load-12 CPU spike during overlap, frees CPU for ube/del menu loops
- [ ] **Tighten scroll waits** — ube/del menu scroll sleep 1.2s→0.6s, fewer iterations (~15-20% per restaurant; watch missed lazy cards)

Context: batch wall = slowest scraper. A (parallelize ube/del menu loop) = big win (33min→~8min). B = polish on top.

