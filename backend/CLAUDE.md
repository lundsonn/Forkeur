# Forkeur Backend

FastAPI scraper manager: trigger/schedule Playwright scrapers, stream logs via WebSocket, persist to Supabase.

## Stack

- **FastAPI** + **APScheduler** — HTTP API + cron scheduling
- **Playwright** — headless Chromium scrapers (stealth mode via `base.py`)
- **Supabase** — storage (python-supabase client)
- **uv** — package manager

## Commands

```bash
# All from backend/ directory
uv sync                            # install deps
uv run uvicorn main:app --reload   # dev server :8000
uv run pytest                      # tests
uv run playwright install chromium # first-time browser install
```

## Structure

```
backend/
├── main.py           ← FastAPI app, lifespan, routes wired
├── scheduler.py      ← APScheduler setup
├── ws.py             ← WebSocket log streaming
├── db.py             ← Supabase client + DB helpers
├── models.py         ← Pydantic models
├── scrapers/
│   ├── base.py       ← BaseScraper (stealth, browser lifecycle)
│   ├── ubereats.py
│   ├── deliveroo.py
│   └── takeaway.py
├── routers/
│   ├── scrapers.py   ← GET/POST /api/scrapers
│   ├── runs.py       ← GET /api/runs
│   ├── schedule.py   ← cron schedule endpoints
│   └── data.py       ← query scraped data
├── dashboard/        ← React+Vite admin UI (served as static in prod)
└── tests/
```

## Scraper pattern

Each scraper extends `BaseScraper`. Override `scrape(address, coords)` → returns list of restaurant dicts. Base handles browser launch, stealth, and cleanup.

## Env vars

See `.env.example`. Required: `SUPABASE_URL`, `SUPABASE_KEY`.
