# Design: Migrate from Supabase to Self-Hosted PostgreSQL

**Date:** 2026-06-09  
**Approach:** Schema-first, scrapers-repopulate (no data migration)  
**Status:** Approved (amended 2026-06-09 during plan writing — see "Plan-time corrections")

---

## Plan-time corrections

Four technical decisions were refined while writing the implementation plan, after reading the full backend call graph and migration set. They override the original prose below where they conflict:

1. **Driver = psycopg3 (sync `ConnectionPool`), not asyncpg.** `backend/db.py` exposes ~40 **synchronous** functions called by 10 async Playwright scrapers — directly (blocking) and via `asyncio.to_thread`. asyncpg would force `async def` on every function and break every call site. psycopg3's sync pool keeps `db.py` synchronous: zero scraper changes, routers keep `asyncio.to_thread(db.fn)`, and it is PgBouncer-transaction-mode safe.
2. **Extensions = `pg_stat_statements` only.** `gen_random_uuid()` is core in PostgreSQL 13+ (no `uuid-ossp`). `unaccent`/`pg_trgm` are never called at runtime (matching uses Python `rapidfuzz.JaroWinkler`; migration 019 confirms zero trgm indexes) — skip both.
3. **Schema provisioning = `pg_dump --schema-only` from Supabase, sanitized.** The 20 migrations grant to Supabase-only roles (`anon`, `service_role`) and move extensions into a Supabase-only `extensions` schema, so naive `psql` replay fails on vanilla PG16. Dump the live public schema, strip RLS/policy/grant/owner lines, apply one clean `selfhosted_schema.sql`. The `merge_restaurants_atomic(uuid,uuid)` function must survive the strip (it is the only runtime RPC).
4. **`BACKEND_URL` must be added to `queries.ts` + `sitemap.ts`.** It is NOT yet referenced there (only in `app/api/refresh/route.ts` and `app/api/claims/route.ts`). A shared `lib/backend.ts` helper centralizes it.

---

## Context

Forkeur currently uses Supabase (hosted PostgreSQL + PostgREST + GoTrue) for all data storage. The backend (`db.py`) wraps the Supabase Python client; the Next.js frontend (`lib/queries.ts`) wraps `@supabase/ssr`. No Supabase Auth is used — the only auth is a custom JWT on FastAPI for admin operations.

Goal: move PostgreSQL to the existing Hetzner server (`178.104.57.72`, Ubuntu 24.04, 7.6GB RAM, 4 vCPU, 75GB disk). No data migration — scrapers repopulate everything after cutover.

---

## Architecture

```
[Next.js :3000]
      |
      | HTTP (BACKEND_URL=http://localhost:8000)
      v
[FastAPI :8000]  ←  APScheduler + Playwright scrapers
      |
      | asyncpg (postgresql://forkeur_app@localhost:5432/forkeur)
      v
[PgBouncer :5432]  — transaction pooling, 20 server conns, 100 client slots
      |
      | internal socket
      v
[PostgreSQL 16 :5433]  — system service, DB: forkeur, owner: forkeur_app
```

**No Supabase JS client anywhere after migration.** Frontend calls FastAPI only. FastAPI owns all DB access.

---

## Section 1 — Infrastructure

**PostgreSQL 16** via `apt` as system service. Listens on `localhost:5433` (not exposed externally). DB: `forkeur`, role: `forkeur_app` (login, no superuser). All 20 migrations applied via `psql`.

Extensions needed (currently on Supabase):
- `uuid-ossp` — for `gen_random_uuid()` / `uuid_generate_v4()`
- `pg_stat_statements` — slow query monitoring
- `unaccent` — used in search/matching

**PgBouncer** on port `5432`. Mode: transaction pooling (safe for asyncpg, compatible with scraper burst patterns). Config:
```ini
[databases]
forkeur = host=127.0.0.1 port=5433 dbname=forkeur

[pgbouncer]
listen_port = 5432
listen_addr = 127.0.0.1
auth_type = scram-sha-256
pool_mode = transaction
max_client_conn = 100
default_pool_size = 20
```

**RLS policies** in migrations are kept as SQL but have no effect on direct `asyncpg` connections (which bypass PostgREST entirely). Backend connects as `forkeur_app`, not `anon`.

**Backups:**
```bash
# /etc/cron.d/forkeur-backup
0 3 * * * root pg_dump -U forkeur_app forkeur | gzip > /backups/forkeur-$(date +%F).gz
# Keep 7 days
0 4 * * * root find /backups -name "forkeur-*.gz" -mtime +7 -delete
```

**Scaling path:**
- Scraper/DB contention → separate PgBouncer pools per workload (scraper vs app)
- Outgrow single server → add streaming read replica via `pg_basebackup`
- Move to managed Postgres (Neon/RDS) if needed — single `DATABASE_URL` change

---

## Section 2 — Backend changes

### `backend/db.py`

Replace Supabase client with `asyncpg` connection pool. Key changes:

- `get_client() → Client` becomes `get_pool() → asyncpg.Pool`
- Pool created at FastAPI startup (`lifespan`), closed on shutdown
- All `.from_().select().eq()...` chains replaced with parameterized SQL
- `_validate_uuid()` stays (injection protection still needed)
- `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` env vars → `DATABASE_URL`

`backend/.env` addition:
```
DATABASE_URL=postgresql://forkeur_app:PASSWORD@localhost:5432/forkeur
```

Dependencies: `uv add asyncpg` → `uv remove supabase`

### `backend/routers/public.py` (new file)

Unauthenticated read endpoints mirroring what `lib/queries.ts` currently fetches from PostgREST:

| Endpoint | Replaces |
|---|---|
| `GET /api/public/restaurants` | `getRestaurants()` |
| `GET /api/public/restaurants/{id}` | `getRestaurantWithListings()` |
| `GET /api/public/deals` | deals page query |
| `GET /api/public/scraper-runs/latest` | refresh cooldown + sitemap |

Response shapes match current Supabase responses exactly — no frontend type changes needed.

`main.py`: register `public.py` router, add `asyncpg.create_pool()` to lifespan startup.

---

## Section 3 — Frontend changes

### `forkeur-app/lib/queries.ts`

Replace all `createClient(cookieStore).from(...).select(...)` chains with:
```ts
const res = await fetch(`${BACKEND_URL}/api/public/restaurants`, {
  next: { revalidate: 3600 }
})
```

`BACKEND_URL = process.env.BACKEND_URL ?? 'http://localhost:8000'` — already exists in the codebase.

### Files to delete
- `forkeur-app/utils/supabase/server.ts`
- `forkeur-app/utils/supabase/client.ts`
- `forkeur-app/utils/supabase/middleware.ts` (dead code — no app-root `middleware.ts` imports it)

### `app/sitemap.ts` + `app/api/refresh/route.ts`
Both currently call `createClient` for a single DB read. Replace with `fetch(BACKEND_URL/api/public/scraper-runs/latest)`.

### `forkeur-app/package.json`
Remove: `@supabase/ssr`, `@supabase/supabase-js`

### `.env.local` (prod + local)
Remove: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
No new vars needed — `BACKEND_URL` already set.

---

## Section 4 — Migration sequence

**Zero forced downtime** if backend and frontend are deployed independently:

1. **Provision DB** — install PostgreSQL 16 + PgBouncer, apply migrations, create role + password
2. **Deploy backend** — `db.py` + `public.py` pointing to local Postgres. Scrapers run. Data populates. Supabase still live but no longer written to.
3. **Deploy frontend** — `queries.ts` switches to `BACKEND_URL`. Supabase JS client removed.
4. **Smoke test** — homepage, restaurant page, deals, sitemap, claims, scraper trigger
5. **Decommission Supabase** — cancel plan, revoke service keys from env files

Rollback: revert backend deploy (Supabase client still in git history), restore frontend env vars. Supabase data is stale but recoverable since scrapers haven't written to it after step 2.

---

## Section 5 — Monitoring & ops

- `pg_stat_statements` enabled: `CREATE EXTENSION pg_stat_statements;`
- Slow query log: `log_min_duration_statement = 500ms` in `postgresql.conf`
- `systemd` unit for PgBouncer with `Restart=always`
- After first full scraper run post-migration: `htop` baseline for RAM/CPU under load
- If Postgres killed during scrape: add 2GB swap (`fallocate -l 2G /swapfile`) + reduce `work_mem` to 4MB
- Decision gate: if scrapers + Postgres can't coexist on same server after 3 test runs → provision second Hetzner CX22 (€4/mo) for scrapers only

---

## Files changed summary

| File | Change |
|---|---|
| `backend/db.py` | Replace Supabase client with asyncpg pool |
| `backend/main.py` | Add pool lifecycle to lifespan, register public router |
| `backend/routers/public.py` | New — public read endpoints |
| `backend/pyproject.toml` | `asyncpg` in, `supabase` out |
| `backend/.env` | `DATABASE_URL` in, `SUPABASE_*` out |
| `forkeur-app/lib/queries.ts` | Supabase calls → fetch(BACKEND_URL) |
| `forkeur-app/app/sitemap.ts` | Same |
| `forkeur-app/app/api/refresh/route.ts` | Same |
| `forkeur-app/utils/supabase/server.ts` | Delete |
| `forkeur-app/utils/supabase/client.ts` | Delete |
| `forkeur-app/package.json` | Remove `@supabase/*` |
| `forkeur-app/.env.local` | Remove `NEXT_PUBLIC_SUPABASE_*` |
| Server: `/etc/postgresql/16/main/postgresql.conf` | Port 5433, slow query log |
| Server: `/etc/pgbouncer/pgbouncer.ini` | New config |
| Server: `/etc/cron.d/forkeur-backup` | Daily pg_dump |
