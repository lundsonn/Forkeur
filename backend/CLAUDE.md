# Forkeur Backend

FastAPI scraper manager: trigger/schedule Playwright scrapers, stream logs via WebSocket, persist to PostgreSQL.

## Stack

- **FastAPI** + **APScheduler** — HTTP API + cron scheduling
- **Playwright** — headless Chromium scrapers (stealth mode via `base.py`)
- **PostgreSQL 16** — storage via psycopg3 sync pool (`pgpool.py`); PgBouncer transaction mode on :5432
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
├── main.py           ← FastAPI app, lifespan, AuthMiddleware, routes wired
├── auth.py           ← JWT token create/verify (HS256, 30-day expiry)
├── scheduler.py      ← APScheduler setup
├── ws.py             ← WebSocket log streaming
├── db.py             ← DB helpers (upsert_restaurant, upsert_listing, patch_listing, …)
├── pgpool.py         ← psycopg3 sync connection pool (fetchall/fetchone/execute)
├── models.py         ← Pydantic models
├── scrapers/
│   ├── base.py       ← BaseScraper (stealth, browser lifecycle)
│   ├── ubereats.py
│   ├── deliveroo.py
│   ├── takeaway.py
│   ├── fees.py       ← refresh delivery_fee + min_order for existing listings
│   ├── promos.py     ← shared promotion-parsing utilities (classify/dedup)
│   └── direct.py     ← direct ordering: enrich websites + Google Maps discovery
├── routers/
│   ├── auth_router.py ← POST /api/auth/login
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

See `.env.example`. Required: `DATABASE_URL`, `JWT_SECRET`, `ADMIN_PASSWORD`.
