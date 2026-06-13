# Forkeur — food price comparison (Brussels)

Compare restaurant prices across UberEats, Deliveroo, Takeaway, and direct ordering.

## Architecture

```
Forkeur/              ← repo root
├── backend/          ← Python scraper manager (FastAPI + APScheduler + Playwright); owns all DB access
├── forkeur-app/      ← Next.js 15 consumer app (App Router); reads via FastAPI public endpoints
└── supabase/         ← historical migration files (schema source for the self-hosted DB)
```

**`Forkeur/`** directory inside the repo root is dead code — ignore it.
**Root-level `scrape-*.js` and `*.json`** are prototype artifacts — ignore them.

## Database

**Self-hosted PostgreSQL 16** on the production server (migrated off hosted Supabase, 2026-06-11). Architecture: `Next.js → FastAPI (psycopg3 sync pool) → PgBouncer:5432 (transaction mode) → PostgreSQL:5433`. The backend owns all DB access; the frontend never touches Postgres directly — it reads through the unauthenticated `/api/public/*` endpoints (`backend/routers/public.py`).

- Connection: backend reads `DATABASE_URL` (points at PgBouncer on `127.0.0.1:5432`, db `forkeur`, role `forkeur_app`). Pool lives in `backend/pgpool.py` (`prepare_threshold=None` — required under PgBouncer transaction pooling).
- `backend/db.py` is the DB layer: typed helpers (`upsert_restaurant`, `upsert_listing`, …) plus a PostgREST-compat `get_client()` shim used by the not-yet-ported scrapers (`direct.py`, `direct_menu.py`, `dom_menu/`, `scheduler.py`).
- Schema source: `supabase/migrations/` (dumped from old Supabase, sanitized, applied to `/opt/forkeur/ops/selfhosted_schema.sql`). The old Supabase project `ltpicouyzdmamblzwcgc` is kept as a cold fallback only.

Tables:
- `restaurants` — master list (includes `phone`, `website`, `lat`, `lng`)
- `platform_listings` — one row per restaurant per platform (`uber_eats` | `deliveroo` | `takeaway` | `direct`)
- `menu_items` — menu items linked to platform_listings
- `promotions` — structured promotions (one row per promo per listing; types: `free_delivery`, `bogo`, `pct_discount`, `abs_discount`, `free_item`, `spend_save`, `other`)
- `scraper_runs` — run history (platforms: `ubereats` | `deliveroo` | `takeaway` | `fees` | `direct` | `direct_menu` | `dom_menu` | `match`)
- `restaurant_claims` — user-submitted data corrections / owner inquiries
- `restaurant_match_decisions` — cross-platform de-duplication queue/audit log
- `scraper_schedules` — persisted cron schedules

> The Supabase MCP tools in `.mcp.json` still point at the old hosted project — they are **not** the live DB anymore. For schema/query work on the live DB, use `psql` against the server (PgBouncer `127.0.0.1:5432` or Postgres `127.0.0.1:5433`).

> **Platform naming gotcha:** `platform_listings.platform` uses `uber_eats` (underscore), while `scraper_runs.platform` uses `ubereats` (no underscore).

## Scrapers (backend/scrapers/)

- `ubereats.py`, `deliveroo.py`, `takeaway.py` — full restaurant + menu scrape
- `fees.py` — refresh `delivery_fee` + `min_order` for existing UberEats and Deliveroo listings
- `promos.py` — shared promotion-parsing utilities (classify + deduplicate promo labels into structured rows)
- `direct.py` — two phases: enrich existing restaurant websites for direct ordering; discover new restaurants via Google Maps
- `direct_classify.py` — URL classifier (`ordering` | `menu` | `website` | `phone`)
- `direct_menu.py` — structured API scrapers for `url_type=ordering` listings (sq-menu/foodbooking, Odoo POS, piki-app); sync httpx; 66 tests
- `dom_menu/` — hybrid DOM scraper for `url_type=website|menu` listings (447 sites):
  - `generic.py` — JSON-LD first, then price-proximity heuristic (Playwright)
  - `sites/__init__.py` — per-site adapter registry (empty; add as needed after first run)

### Direct ordering — probed API shapes (do not re-probe)

Fixtures saved in `backend/tests/fixtures/`:
- `sq_menu_response.json` — shape: `{categories:[{name, products:[{name, price(€), imageUrl}]}]}`
- `odoo_pos_response.json` — shape: `{result:[{name, list_price, categ_id:[id,name], description_sale}]}`; `categ_id` (NOT `pos_category_id`); requires session cookie (SessionExpiredException → GET pos-self URL first)
- `piki_app_response.json` — shape: `{categories:[{name, items:[{name, price(cents), imageUrl}]}]}`; prices in **cents** (÷100); top-level `categories` key (not bare array)

## Running

```bash
# Install everything
make install

# Dev: FastAPI on :8000, Vite dashboard on :5173
make dev

# Next.js app
cd forkeur-app && npm run dev   # :3000
```

## Production Server

- **IP:** `178.104.57.72` (Hetzner Cloud, Ubuntu, hostname `ubuntu-4gb-nbg1-1` — the box actually has **8 GB RAM** + 2 GB swap + 4 cores; the hostname is stale from a since-resized plan)
- **Scraper RAM:** each Playwright scraper (ubereats/deliveroo/takeaway/dom_menu) peaks ~2 GB; running 2 concurrently peaks ~5.5 GB / 8 GB. Parallelize with a launch gate that holds when MemAvailable < ~1.8 GB to keep margin.
- **SSH:** `ssh -i ~/.ssh/id_ed25519 root@178.104.57.72`
- **App location:** `/opt/forkeur/`
- **Services:** `systemctl restart forkeur-backend` / `forkeur-frontend` / `postgresql` / `pgbouncer`
- **Database:** PostgreSQL 16 on `127.0.0.1:5433`; PgBouncer (transaction mode) on `127.0.0.1:5432` → db `forkeur`, role `forkeur_app`. Daily `pg_dump` backup to `/backups` via `/etc/cron.d/forkeur-backup` (keep 7d). Schema at `/opt/forkeur/ops/selfhosted_schema.sql`.
- **Backend API:** `http://localhost:8000` (internal only)
- **Auth:** POST `/api/auth/login` with `{"password":"<ADMIN_PASSWORD>"}` → Bearer token (JWT, 12h expiry default; override with `JWT_EXPIRE_HOURS` env var; requires `JWT_SECRET`)
- **Deploy:** `cd /opt/forkeur && git pull && make migrate && systemctl restart forkeur-backend`
  - **DB migrations** run via `make migrate` (→ `backend/ops/migrate.py up`). The runner is a **separate** script (NOT the backend app) because `forkeur_app` has no CREATE privilege — DDL must run as the `postgres` superuser, connecting **directly to Postgres :5433** (NOT through PgBouncer; DDL must not go through transaction pooling). Set env `MIGRATE_DATABASE_URL` to that superuser DSN, e.g. `postgresql://postgres:PW@127.0.0.1:5433/forkeur` (fallback env name: `DATABASE_URL_SUPERUSER`). Applied migrations are tracked in the `schema_migrations` table (version = filename). `make migrate-check` lists pending without applying (exit 1 if any).
    - **First time only:** `make migrate-baseline` records the already-applied 001–027 migrations into `schema_migrations` WITHOUT re-running their SQL (the live DB has them applied but no tracking table yet).
    - The backend does a **read-only** pending check at startup (app role can SELECT `schema_migrations`). Pending migrations log a loud WARNING but do not block startup; set env `MIGRATIONS_STRICT=1` to make pending migrations a fatal startup error. If the tracking table is missing it warns to run `make migrate-baseline`.
  - **Admin dashboard changes** (`backend/dashboard/`) require a rebuild **on the server** — `index.html` is gitignored (`.gitignore` `*.html`) so the committed bundle hash never ships; the server keeps serving its old `index.html`. After `git pull`: `cd /opt/forkeur/backend/dashboard && npm install && npm run build` (regenerates `backend/static/dashboard/index.html` + assets). No backend restart needed (static files).
- **Trigger scraper:** `POST /api/scrapers/{ubereats|deliveroo|takeaway|fees|direct|direct_menu|dom_menu}/run` with Bearer token

## Key conventions

- Backend: Python 3.12+, `uv` for packages (`uv run <cmd>`, never activate venv manually)
- Frontend: Next.js 15 App Router — Server Components by default, `'use client'` only when needed
- Frontend data: read through `forkeur-app/lib/backend.ts` (`backendFetch`) → FastAPI `/api/public/*`. No direct DB/Supabase client.
- Tests: `pytest` (backend), `vitest` (frontend)
