# Forkeur Scraper Manager — Design Spec
_2026-05-31_

## Overview

Local Python backend + React dashboard to manage the 3 Forkeur food delivery scrapers (UberEats, Deliveroo, Takeaway). Runs entirely on the developer's machine alongside ProtonVPN. Supabase is used only as a remote database — no compute hosted there.

---

## Constraints

- Runs locally (Mac, ProtonVPN BE required for scrapers)
- No remote hosting — no Docker, no cloud deployment
- Supabase free tier as DB only (restaurants, platform_listings, menu_items, scraper_runs)
- Scrapers rewritten in Python (Playwright async) — no Node.js subprocess calls

---

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn (asyncio) |
| Scheduler | APScheduler `AsyncIOScheduler` |
| Scrapers | Playwright (async Python) |
| DB client | supabase-py |
| Dashboard | React + TypeScript + Tailwind (Vite) |
| Env/deps | uv (Python), npm (dashboard) |
| Dev/build | Makefile |

---

## Repo Structure

```
food-price-compare/
├── backend/
│   ├── main.py              # FastAPI app, mounts routers, serves dashboard in prod
│   ├── scheduler.py         # AsyncIOScheduler, loads cron config from DB on startup
│   ├── db.py                # supabase-py client, upsert helpers (slug+platform dedup)
│   ├── models.py            # Pydantic: ScraperRun, ScheduleConfig, RestaurantOut, MenuItemOut
│   ├── ws.py                # WebSocket /ws/{run_id} — streams logs to dashboard
│   ├── scrapers/
│   │   ├── base.py          # shared Playwright setup, CloudflareBlockedError
│   │   ├── ubereats.py      # async def run(config, log_fn) → ScraperResult
│   │   ├── deliveroo.py
│   │   └── takeaway.py
│   ├── routers/
│   │   ├── scrapers.py      # POST /scrapers/{platform}/run, GET /scrapers/status
│   │   ├── runs.py          # GET /runs, GET /runs/{id}
│   │   ├── schedule.py      # GET/POST/DELETE /schedules
│   │   └── data.py          # GET /restaurants, GET /menu-items
│   └── dashboard/           # Vite React app
│       └── src/
│           ├── pages/
│           │   ├── Dashboard.tsx   # stats overview
│           │   ├── Scrapers.tsx    # scraper cards + log drawer
│           │   ├── History.tsx     # run history table
│           │   ├── Schedule.tsx    # cron config per platform
│           │   └── Data.tsx        # restaurant/menu browser
│           └── components/
│               ├── Sidebar.tsx
│               ├── ScraperCard.tsx
│               └── LogDrawer.tsx   # WebSocket consumer, bottom drawer
├── forkeur-app/             # existing Next.js public frontend (unchanged)
└── supabase/
    └── migrations/
        ├── 001_initial_schema.sql
        └── 002_scraper_runs.sql    # new table
```

---

## New DB Table: `scraper_runs`

```sql
create table scraper_runs (
  id           uuid primary key default gen_random_uuid(),
  platform     text not null check (platform in ('ubereats', 'deliveroo', 'takeaway')),
  status       text not null check (status in ('running', 'success', 'failed', 'blocked', 'partial')),
  started_at   timestamptz default now(),
  finished_at  timestamptz,
  records_saved integer default 0,
  error_msg    text
);
```

---

## Data Flow

1. User clicks **Run now** → `POST /scrapers/{platform}/run`
2. FastAPI creates `scraper_run` row (`status=running`), returns `run_id`
3. Dashboard connects WebSocket `/ws/{run_id}`
4. Scraper `async def run(config, log_fn)` executes — `log_fn` pushes log lines to asyncio queue
5. `ws.py` drains queue → sends `{"type":"log","line":"..."}` to dashboard
6. `LogDrawer.tsx` appends lines, auto-scrolls
7. Scraper finishes → upserts restaurants/listings/menu_items to Supabase
8. `scraper_run` row updated (`status=success`, `records_saved=N`, `finished_at=now`)
9. WebSocket sends `{"type":"done","records":N}` → drawer shows summary

APScheduler calls same `run()` functions on cron — same flow minus WebSocket (logs written to `error_msg` only).

---

## Scraper Interface

```python
@dataclass
class ScraperConfig:
    address: str = "Pl. Poelaert 1, 1000 Bruxelles"
    target: str | None = None  # None = all restaurants
    max_items: int = 50

@dataclass
class ScraperResult:
    records_saved: int
    restaurants: list[dict]

async def run(config: ScraperConfig, log_fn: Callable[[str], None]) -> ScraperResult:
    ...
```

All 3 scrapers implement this interface. `log_fn` is a no-op when called from scheduler.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/scrapers/{platform}/run` | Trigger scraper, returns `run_id` |
| GET | `/scrapers/status` | Current status of all 3 scrapers |
| GET | `/runs` | Paginated run history |
| GET | `/runs/{id}` | Single run detail |
| GET | `/schedules` | All cron schedules |
| POST | `/schedules` | Create/update schedule |
| DELETE | `/schedules/{platform}` | Remove schedule |
| GET | `/restaurants` | Paginated restaurant list |
| GET | `/menu-items` | Menu items with filters |
| WS | `/ws/{run_id}` | Live log stream |

---

## Dashboard UI

**Layout:** Sidebar nav (dark) + content area.

**Scrapers page:**
- 3 expanded cards (one per platform)
- Each shows: status dot, last run time, duration, records saved, error if failed
- Buttons: Run now / Stop (while running) / Retry (if failed)
- **LogDrawer:** fixed bottom panel, slides up when run starts, WebSocket log stream with auto-scroll, dismiss button

**Dashboard page:**
- Stat cards: total restaurants, total menu items, last run per platform
- Recent runs list (last 10)

**History page:**
- Table: platform, status, started_at, duration, records_saved, error_msg
- Paginated, filterable by platform/status

**Schedule page:**
- Per-platform cron expression input + enable/disable toggle
- Shows next scheduled run time

**Data page:**
- Searchable restaurant table
- Filter by platform
- Expandable rows showing menu items

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Cloudflare block | Raises `CloudflareBlockedError` → `status=blocked`, retried after 30min by scheduler |
| Scraper already running | `POST /run` returns 409 |
| Supabase insert fail | Logged, run marked `status=partial`, records_saved = partial count |
| Playwright timeout | Raises, run marked `status=failed` with error_msg |

---

## Dev/Build (Makefile)

```makefile
install:
    cd backend && uv sync
    cd backend/dashboard && npm install
    cd backend/dashboard && npx playwright install chromium

dev:
    cd backend && uv run uvicorn main:app --reload --port 8000 &
    cd backend/dashboard && npm run dev

build:
    cd backend/dashboard && npm run build  # outputs to backend/static/

prod:
    cd backend && uv run uvicorn main:app --port 8000
```

- **Dev:** dashboard on `:5173` (Vite HMR), API on `:8000`, Vite proxies `/api` → `:8000`
- **Prod:** `make build` compiles React into `backend/static/`, FastAPI serves at `/`

---

## Out of Scope

- Remote hosting / deployment
- Authentication (local tool, no auth needed)
- Price diff alerts (future)
- Basket simulator (future, in forkeur-app)
