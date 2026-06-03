# Forkeur — food price comparison (Brussels)

Compare restaurant prices across UberEats, Deliveroo, Takeaway, and direct ordering.

## Architecture

```
Forkeur/              ← repo root
├── backend/          ← Python scraper manager (FastAPI + APScheduler + Playwright)
├── forkeur-app/      ← Next.js 15 consumer app (App Router + Supabase)
└── supabase/         ← DB migrations (applied to remote Supabase project)
```

**`Forkeur/`** directory inside the repo root is dead code — ignore it.
**Root-level `scrape-*.js` and `*.json`** are prototype artifacts — ignore them.

## Database

Supabase project: `ltpicouyzdmamblzwcgc`

Tables:
- `restaurants` — master list (includes `phone`, `website`, `lat`, `lng`)
- `platform_listings` — one row per restaurant per platform (`uber_eats` | `deliveroo` | `takeaway` | `direct`)
- `menu_items` — menu items linked to platform_listings
- `promotions` — structured promotions (one row per promo per listing; types: `free_delivery`, `bogo`, `pct_discount`, `abs_discount`, `free_item`, `spend_save`, `other`)
- `scraper_runs` — run history (platforms: `ubereats` | `deliveroo` | `takeaway` | `fees` | `direct`)
- `claims` — user-submitted data corrections

MCP wired: `.mcp.json` → use Supabase MCP tools for schema/query work.
6 migrations applied: `supabase/migrations/`

> **Platform naming gotcha:** `platform_listings.platform` uses `uber_eats` (underscore), while `scraper_runs.platform` uses `ubereats` (no underscore).

## Scrapers (backend/scrapers/)

- `ubereats.py`, `deliveroo.py`, `takeaway.py` — full restaurant + menu scrape
- `fees.py` — refresh `delivery_fee` + `min_order` for existing UberEats and Deliveroo listings
- `promos.py` — shared promotion-parsing utilities (classify + deduplicate promo labels into structured rows)
- `direct.py` — two phases: enrich existing restaurant websites for direct ordering; discover new restaurants via Google Maps

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

- **IP:** `178.104.57.72` (Hetzner Cloud, Ubuntu, hostname `ubuntu-4gb-nbg1-1`)
- **SSH:** `ssh -i ~/.ssh/id_ed25519 root@178.104.57.72`
- **App location:** `/opt/forkeur/`
- **Services:** `systemctl restart forkeur-backend` / `forkeur-frontend`
- **Backend API:** `http://localhost:8000` (internal only)
- **Auth:** POST `/api/auth/login` with `{"password":"<ADMIN_PASSWORD>"}` → Bearer token (JWT, 30-day expiry; requires `JWT_SECRET` env var)
- **Deploy:** `cd /opt/forkeur && git pull && systemctl restart forkeur-backend`
- **Trigger scraper:** `POST /api/scrapers/{ubereats|deliveroo|takeaway|fees|direct}/run` with Bearer token

## Key conventions

- Backend: Python 3.12+, `uv` for packages (`uv run <cmd>`, never activate venv manually)
- Frontend: Next.js 15 App Router — Server Components by default, `'use client'` only when needed
- Supabase client: `utils/supabase/server.ts` in Server Components, `utils/supabase/client.ts` in Client Components
- Tests: `pytest` (backend), `vitest` (frontend)
