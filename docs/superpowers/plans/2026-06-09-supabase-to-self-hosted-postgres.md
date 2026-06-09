# Supabase → Self-Hosted PostgreSQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Forkeur's database off hosted Supabase onto system PostgreSQL 16 on the existing Hetzner server, replacing the Supabase Python client with psycopg3 in the backend and routing all frontend reads through new FastAPI public endpoints.

**Architecture:** `Next.js → FastAPI (psycopg3 sync pool) → PgBouncer → PostgreSQL 16`. The backend owns all DB access; the frontend never touches Postgres directly. No data migration — scrapers repopulate after cutover. Supabase stays live as a fallback until smoke tests pass.

**Tech Stack:** PostgreSQL 16 (apt), PgBouncer (transaction pooling), psycopg3 + psycopg_pool (sync `ConnectionPool`, `dict_row`), FastAPI, Next.js 16 (App Router, ISR `revalidate=3600`).

**Spec:** `docs/superpowers/specs/2026-06-09-supabase-to-self-hosted-postgres-design.md` (read the "Plan-time corrections" section first — it overrides the original prose).

---

## Driver decision (read before Task 1)

The spec originally said asyncpg. **We use psycopg3 sync instead.** Reason: `backend/db.py` is ~40 synchronous functions called by 10 async Playwright scrapers, both directly (blocking the loop intentionally) and through `asyncio.to_thread(db.fn, ...)`. Making `db.py` async would force `await` on every call site across all scrapers and break the `to_thread` wrappers. psycopg3's `ConnectionPool` is a threadsafe **synchronous** pool — `db.py` stays sync, every scraper call site is untouched, and routers keep doing `asyncio.to_thread(db.fn)`. It is safe under PgBouncer transaction pooling (no session-state features used).

---

## File structure

**Backend — new files:**
- `backend/pgpool.py` — owns the psycopg3 `ConnectionPool`, `get_pool()`, `close_pool()`, and three thin query helpers (`fetchall`, `fetchone`, `execute`). One responsibility: connection lifecycle + query execution.
- `backend/routers/public.py` — unauthenticated read endpoints for the frontend. One responsibility: serialize DB rows into the exact nested JSON shapes the frontend already consumes.

**Backend — modified:**
- `backend/db.py` — every Supabase `.table().select()...` chain replaced with parameterized SQL via `pgpool`. All pure helpers (`_validate_uuid`, `_is_junk`, `_canonical`, `_normalize_for_match`, `infer_cuisine`) unchanged. Add 4 public-read functions.
- `backend/main.py` — open the pool in `lifespan` startup, close on shutdown; register `public.py` router; allowlist `/api/public/` in `AuthMiddleware`; swap `_REQUIRED_ENV` from `SUPABASE_*` to `DATABASE_URL`.
- `backend/pyproject.toml` — add `psycopg[binary]`, `psycopg-pool`; remove `supabase`.
- `backend/.env` — add `DATABASE_URL`; remove `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.

**Frontend — new file:**
- `forkeur-app/lib/backend.ts` — exports `BACKEND_URL` and a typed `backendFetch<T>()` helper. One responsibility: centralize backend base URL + fetch error handling.

**Frontend — modified:**
- `forkeur-app/lib/queries.ts` — `getRestaurants`, `getDeals`, `getRestaurantWithListings` swap their data source from Supabase to `backendFetch`. The raw-row transform logic stays (endpoints return PostgREST-shaped nested JSON).
- `forkeur-app/app/sitemap.ts` — fetch restaurant ids from `/api/public/restaurants`.
- `forkeur-app/app/api/refresh/route.ts` — cooldown check via `/api/public/scraper-runs/latest`.
- `forkeur-app/package.json` — remove `@supabase/ssr`, `@supabase/supabase-js`.
- `forkeur-app/.env.local` (local + prod) — remove `NEXT_PUBLIC_SUPABASE_*`.

**Frontend — deleted:**
- `forkeur-app/utils/supabase/server.ts`, `client.ts`, `middleware.ts`.

**Server — new config:**
- `/etc/postgresql/16/main/conf.d/forkeur.conf`, `/etc/pgbouncer/pgbouncer.ini`, `/etc/pgbouncer/userlist.txt`, `/etc/cron.d/forkeur-backup`, `/opt/forkeur/ops/selfhosted_schema.sql`.

---

## Phase A — Server: provision PostgreSQL + PgBouncer

> All Phase A steps run on the production server: `ssh -i ~/.ssh/id_ed25519_forkeur root@178.104.57.72`. These are ops steps (no TDD); each ends in a verification command with expected output. Do NOT touch the running backend yet — Phase A stands up the DB alongside the live Supabase-backed app.

### Task 1: Install PostgreSQL 16 + create role and database

**Files:** none (server packages + psql).

- [ ] **Step 1: Install PostgreSQL 16**

```bash
apt-get update
apt-get install -y postgresql-16 postgresql-client-16
systemctl enable --now postgresql
```

- [ ] **Step 2: Verify the server is up on the default socket**

Run: `sudo -u postgres psql -tAc "select version();"`
Expected: a line starting `PostgreSQL 16`.

- [ ] **Step 3: Create the application role and database**

Pick a strong password and substitute it for `CHANGE_ME` (record it — it goes into `DATABASE_URL` and PgBouncer userlist later).

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE forkeur_app LOGIN PASSWORD 'CHANGE_ME';
CREATE DATABASE forkeur OWNER forkeur_app;
SQL
sudo -u postgres psql -d forkeur -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
```

- [ ] **Step 4: Move Postgres to port 5433 + enable slow-query log + pg_stat_statements**

Create `/etc/postgresql/16/main/conf.d/forkeur.conf`:

```ini
port = 5433
listen_addresses = '127.0.0.1'
shared_preload_libraries = 'pg_stat_statements'
log_min_duration_statement = 500
work_mem = '8MB'
```

Then:

```bash
systemctl restart postgresql
```

- [ ] **Step 5: Verify port + extension**

Run: `sudo -u postgres psql -p 5433 -d forkeur -tAc "select count(*) from pg_extension where extname='pg_stat_statements';"`
Expected: `1`

### Task 2: Build and apply the sanitized schema

**Files:**
- Create on server: `/opt/forkeur/ops/selfhosted_schema.sql`

The 20 Supabase migrations can't be replayed verbatim (they grant to `anon`/`service_role` and juggle an `extensions` schema that doesn't exist here). Instead, dump the live Supabase public schema and strip the Supabase-only statements.

- [ ] **Step 1: Get the Supabase direct connection string**

From the Supabase dashboard → Project `ltpicouyzdmamblzwcgc` → Settings → Database → "Connection string" → URI (direct, port 5432, **not** the pooler). It looks like `postgresql://postgres:[PASSWORD]@db.ltpicouyzdmamblzwcgc.supabase.co:5432/postgres`. Export it locally (run this and the dump on your laptop, which can reach Supabase):

```bash
export SUPA_DIRECT='postgresql://postgres:PASSWORD@db.ltpicouyzdmamblzwcgc.supabase.co:5432/postgres'
```

- [ ] **Step 2: Dump the public schema only, no owners, no privileges**

```bash
pg_dump "$SUPA_DIRECT" \
  --schema-only --no-owner --no-privileges \
  --schema=public \
  --file=supabase_public_dump.sql
```

`--no-privileges` drops `GRANT`/`REVOKE`. RLS `CREATE POLICY` / `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` lines are still present and must be stripped next (they reference roles that don't exist locally).

- [ ] **Step 3: Strip RLS, policies, and extension-schema noise**

```bash
grep -viE '^(CREATE POLICY|ALTER TABLE .* (ENABLE|FORCE) ROW LEVEL SECURITY|ALTER (EXTENSION|SCHEMA)|CREATE SCHEMA extensions|CREATE EXTENSION (unaccent|pg_trgm))' \
  supabase_public_dump.sql > selfhosted_schema.sql
```

- [ ] **Step 4: Manually verify the stripped schema**

Run: `grep -nE 'POLICY|ROW LEVEL SECURITY|anon|service_role|extensions\.' selfhosted_schema.sql`
Expected: **no output** (empty). If any `extensions.unaccent(` or `extensions.` qualified call survives inside a function body, remove the schema qualifier (it's unused — matching is Python-side). 

Run: `grep -nc 'merge_restaurants_atomic' selfhosted_schema.sql`
Expected: `>= 1` (the only runtime RPC must survive the strip). If it's `0`, the function was defined with a SECURITY-related clause that got grepped out — re-extract it from `supabase/migrations/017_constraints_and_indexes.sql` and append it to `selfhosted_schema.sql` by hand.

- [ ] **Step 5: Copy to server and apply**

```bash
scp -i ~/.ssh/id_ed25519_forkeur selfhosted_schema.sql root@178.104.57.72:/opt/forkeur/ops/selfhosted_schema.sql
ssh -i ~/.ssh/id_ed25519_forkeur root@178.104.57.72 \
  "sudo -u postgres psql -p 5433 -d forkeur -v ON_ERROR_STOP=1 -f /opt/forkeur/ops/selfhosted_schema.sql"
```

Expected: completes with no `ERROR:` lines. If an error references a missing extension, `CREATE EXTENSION IF NOT EXISTS <name>;` it in `forkeur` and re-run.

- [ ] **Step 6: Verify the table set matches Supabase**

Run on server: `sudo -u postgres psql -p 5433 -d forkeur -tAc "select string_agg(tablename, ',' order by tablename) from pg_tables where schemaname='public';"`
Expected (order matters in the sort): `menu_items,platform_listings,promotions,restaurant_claims,restaurant_match_decisions,restaurants,scraper_runs` (plus `scraper_schedules` if migration 009 created it). Confirm `restaurants`, `platform_listings`, `menu_items`, `promotions`, `scraper_runs`, `restaurant_claims`, `restaurant_match_decisions` are all present.

- [ ] **Step 7: Grant table ownership/privileges to forkeur_app**

The dump created tables as `postgres`. Reassign to the app role so it can read/write without RLS friction:

```bash
sudo -u postgres psql -p 5433 -d forkeur <<'SQL'
DO $$
DECLARE t text;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('ALTER TABLE public.%I OWNER TO forkeur_app;', t);
  END LOOP;
END $$;
ALTER FUNCTION public.merge_restaurants_atomic(uuid, uuid) OWNER TO forkeur_app;
SQL
```

- [ ] **Step 8: Verify forkeur_app can write**

Run: `psql "postgresql://forkeur_app:CHANGE_ME@127.0.0.1:5433/forkeur" -tAc "insert into restaurants (name, slug) values ('smoke-test','smoke-test-slug') returning id;"`
Expected: a UUID. Then clean up: `psql "postgresql://forkeur_app:CHANGE_ME@127.0.0.1:5433/forkeur" -c "delete from restaurants where slug='smoke-test-slug';"`

### Task 3: Install and configure PgBouncer

**Files:**
- Create on server: `/etc/pgbouncer/pgbouncer.ini`, `/etc/pgbouncer/userlist.txt`

- [ ] **Step 1: Install PgBouncer**

```bash
apt-get install -y pgbouncer
```

- [ ] **Step 2: Write the SCRAM secret to userlist.txt**

Get the SCRAM verifier for `forkeur_app` from Postgres (so PgBouncer never stores the plaintext password):

```bash
sudo -u postgres psql -p 5433 -tAc \
  "select '\"forkeur_app\" \"' || rolpassword || '\"' from pg_authid where rolname='forkeur_app';" \
  > /etc/pgbouncer/userlist.txt
chown pgbouncer:pgbouncer /etc/pgbouncer/userlist.txt
chmod 600 /etc/pgbouncer/userlist.txt
```

- [ ] **Step 3: Write `/etc/pgbouncer/pgbouncer.ini`**

```ini
[databases]
forkeur = host=127.0.0.1 port=5433 dbname=forkeur

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 5432
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 100
default_pool_size = 20
server_reset_query =
ignore_startup_parameters = extra_float_digits
```

> `server_reset_query` is empty because transaction mode resets per-transaction; `ignore_startup_parameters = extra_float_digits` is required — psycopg/libpq sends it and PgBouncer otherwise rejects the connection.

- [ ] **Step 4: Restart and verify**

```bash
systemctl enable --now pgbouncer
systemctl restart pgbouncer
```

Run: `psql "postgresql://forkeur_app:CHANGE_ME@127.0.0.1:5432/forkeur" -tAc "select 1;"`
Expected: `1` (this connects **through** PgBouncer on 5432).

### Task 4: Backups + monitoring

**Files:**
- Create on server: `/etc/cron.d/forkeur-backup`

- [ ] **Step 1: Create backup directory**

```bash
mkdir -p /backups
chown postgres:postgres /backups
```

- [ ] **Step 2: Write `/etc/cron.d/forkeur-backup`**

```cron
# Daily schema+data dump at 03:00, keep 7 days
0 3 * * * postgres pg_dump -p 5433 forkeur | gzip > /backups/forkeur-$(date +\%F).gz
0 4 * * * root find /backups -name "forkeur-*.gz" -mtime +7 -delete
```

- [ ] **Step 3: Dry-run the backup once**

Run: `sudo -u postgres bash -c 'pg_dump -p 5433 forkeur | gzip > /backups/forkeur-manual.gz' && ls -la /backups/forkeur-manual.gz`
Expected: a non-empty `.gz` file. Then `rm /backups/forkeur-manual.gz`.

- [ ] **Step 4: Add 2GB swap as an OOM safety net (scrapers peak ~5.5GB on 7.6GB box)**

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

Run: `free -m | grep Swap`
Expected: a Swap line showing ~2048 total.

---

## Phase B — Backend: psycopg3 pool + db.py rewrite

> From here, all steps run locally in `backend/` with `uv`, TDD where the logic is pure or integration-testable. Integration tests need a throwaway local Postgres; gate them on `TEST_DATABASE_URL` so they skip in CI where no DB exists.

### Task 5: Add psycopg, build the pool module

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/pgpool.py`
- Test: `backend/tests/test_pgpool.py`

- [ ] **Step 1: Swap dependencies**

```bash
cd backend
uv add "psycopg[binary]" psycopg-pool
uv remove supabase
```

Run: `uv run python -c "import psycopg, psycopg_pool; print('ok')"`
Expected: `ok`

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_pgpool.py`:

```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set",
)


def test_fetchone_returns_dict():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    import pgpool
    pgpool.close_pool()  # reset any pool from a previous test
    row = pgpool.fetchone("select 1 as n, 'x' as s")
    assert row == {"n": 1, "s": "x"}


def test_fetchall_returns_list_of_dicts():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    import pgpool
    rows = pgpool.fetchall("select * from (values (1),(2)) as t(n) order by n")
    assert rows == [{"n": 1}, {"n": 2}]


def test_execute_returns_rowcount():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    import pgpool
    n = pgpool.execute("select 1")
    assert isinstance(n, int)
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_pgpool.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'pgpool'`), or SKIP if `TEST_DATABASE_URL` is unset. To actually exercise it: `createdb forkeur_test && TEST_DATABASE_URL=postgresql://localhost/forkeur_test uv run pytest tests/test_pgpool.py -v`.

- [ ] **Step 4: Write `backend/pgpool.py`**

```python
"""psycopg3 connection pool — the single point of DB access for the backend.

Synchronous on purpose: db.py exposes sync functions called by async scrapers
(directly and via asyncio.to_thread). A sync pool keeps every call site
unchanged. Safe under PgBouncer transaction pooling — no session state is used.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Sequence

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv

load_dotenv()

_pool: ConnectionPool | None = None
_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                dsn = os.environ["DATABASE_URL"]
                _pool = ConnectionPool(
                    dsn,
                    min_size=2,
                    max_size=10,
                    kwargs={"row_factory": dict_row},
                    open=True,
                )
    return _pool


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def fetchall(sql: str, params: Sequence[Any] | dict | None = None) -> list[dict]:
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetchone(sql: str, params: Sequence[Any] | dict | None = None) -> dict | None:
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql: str, params: Sequence[Any] | dict | None = None) -> int:
    """Run a statement, return affected rowcount. Use for INSERT/UPDATE/DELETE
    without RETURNING."""
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `createdb forkeur_test 2>/dev/null; TEST_DATABASE_URL=postgresql://localhost/forkeur_test uv run pytest tests/test_pgpool.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/pgpool.py backend/tests/test_pgpool.py
git commit -m "feat(db): add psycopg3 connection pool module"
```

### Task 6: Add generic INSERT/UPDATE helpers to db.py

**Files:**
- Modify: `backend/db.py` (top, after the pure helpers)
- Test: `backend/tests/test_db_helpers.py`

These two helpers replace the repeated PostgREST `.upsert(dict)` / `.update(dict)` patterns with parameterized SQL built from a dict, so the rest of the rewrite stays short.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_db_helpers.py`:

```python
import db


def test_build_insert_simple():
    sql, params = db._build_insert("restaurants", {"name": "X", "slug": "x"})
    assert sql == 'INSERT INTO restaurants (name, slug) VALUES (%s, %s) RETURNING id'
    assert params == ["X", "x"]


def test_build_insert_on_conflict():
    sql, params = db._build_insert(
        "restaurants", {"name": "X", "slug": "x"}, on_conflict="slug"
    )
    assert "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name" in sql
    assert params == ["X", "x"]


def test_build_update():
    sql, params = db._build_update("restaurants", {"cuisine": "Pizza"}, "id", "abc")
    assert sql == 'UPDATE restaurants SET cuisine = %s WHERE id = %s'
    assert params == ["Pizza", "abc"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_db_helpers.py -v`
Expected: FAIL (`AttributeError: module 'db' has no attribute '_build_insert'`).

- [ ] **Step 3: Implement the helpers**

In `backend/db.py`, replace the Supabase import block at the top:

```python
import os
import re
import threading
import unicodedata
from uuid import UUID
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
```

with:

```python
import re
import unicodedata
import json as _json
from uuid import UUID

import pgpool
from dotenv import load_dotenv

load_dotenv()


def _build_insert(table: str, data: dict, on_conflict: str | None = None,
                  returning: str = "id") -> tuple[str, list]:
    cols = list(data.keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    if on_conflict:
        # mirror Supabase upsert: on conflict, overwrite every non-conflict column
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in cols if c != on_conflict
        )
        sql += f" ON CONFLICT ({on_conflict}) DO UPDATE SET {updates}" if updates \
            else f" ON CONFLICT ({on_conflict}) DO NOTHING"
    if returning:
        sql += f" RETURNING {returning}"
    return sql, [_coerce(v) for v in data.values()]


def _build_update(table: str, data: dict, where_col: str, where_val) -> tuple[str, list]:
    sets = ", ".join(f"{c} = %s" for c in data.keys())
    sql = f"UPDATE {table} SET {sets} WHERE {where_col} = %s"
    return sql, [_coerce(v) for v in data.values()] + [where_val]


def _coerce(v):
    """psycopg adapts dict/list to jsonb only with an explicit Jsonb wrapper;
    Supabase accepted raw dicts. Wrap dict/list as JSON strings for jsonb cols
    (features, opening_hours)."""
    if isinstance(v, (dict, list)):
        return _json.dumps(v)
    return v
```

> Note: `_coerce` serializes dict/list to JSON text. Postgres casts JSON text into `jsonb`/`json` columns automatically on insert. This covers `restaurant_match_decisions.features` and any `opening_hours` writes.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_db_helpers.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/db.py backend/tests/test_db_helpers.py
git commit -m "feat(db): add parameterized insert/update builders, swap supabase import for pgpool"
```

### Task 7: Rewrite run-tracking + restaurant/listing/menu writers

**Files:**
- Modify: `backend/db.py`

Replace these functions body-for-body. The signatures and return types stay identical so callers don't change. Each `get_client().table(X)...execute()` becomes a `pgpool` call.

- [ ] **Step 1: Replace the run-tracking functions**

Replace `run_exists`, `create_run`, `update_run_progress`, `finish_run`, `get_runs`, `get_run`, `get_last_run_per_platform`, `get_last_successful_run`, `get_last_successful_run_batch`, `orphan_stale_runs` with:

```python
def run_exists(run_id: str) -> bool:
    row = pgpool.fetchone("SELECT id FROM scraper_runs WHERE id = %s LIMIT 1", [run_id])
    return row is not None


def create_run(platform: str) -> str:
    row = pgpool.fetchone(
        "INSERT INTO scraper_runs (platform, status) VALUES (%s, 'running') RETURNING id",
        [platform],
    )
    return str(row["id"])


def update_run_progress(run_id: str, records_saved: int) -> None:
    pgpool.execute(
        "UPDATE scraper_runs SET records_saved = %s WHERE id = %s",
        [records_saved, run_id],
    )


def finish_run(run_id: str, status: str, records_saved: int = 0,
               error_msg: str | None = None) -> None:
    pgpool.execute(
        "UPDATE scraper_runs SET status = %s, records_saved = %s, "
        "finished_at = now(), error_msg = %s WHERE id = %s",
        [status, records_saved, error_msg, run_id],
    )


def get_runs(limit: int = 50, offset: int = 0) -> list[dict]:
    return pgpool.fetchall(
        "SELECT * FROM scraper_runs ORDER BY started_at DESC LIMIT %s OFFSET %s",
        [limit, offset],
    )


def get_run(run_id: str) -> dict | None:
    return pgpool.fetchone("SELECT * FROM scraper_runs WHERE id = %s", [run_id])


def get_last_run_per_platform() -> dict[str, dict]:
    platforms = ("ubereats", "deliveroo", "takeaway", "direct", "direct_menu", "dom_menu", "match")
    rows = pgpool.fetchall(
        "SELECT * FROM scraper_runs WHERE platform = ANY(%s) "
        "ORDER BY started_at DESC LIMIT 140",
        [list(platforms)],
    )
    seen: dict[str, dict] = {}
    for row in rows:
        p = row["platform"]
        if p not in seen:
            seen[p] = row
    return seen


def get_last_successful_run(platform: str) -> dict | None:
    return pgpool.fetchone(
        "SELECT * FROM scraper_runs WHERE platform = %s AND status = 'success' "
        "ORDER BY started_at DESC LIMIT 1",
        [platform],
    )


def get_last_successful_run_batch(platforms: list[str]) -> dict[str, dict]:
    if not platforms:
        return {}
    rows = pgpool.fetchall(
        "SELECT platform, status, started_at, finished_at, records_saved "
        "FROM scraper_runs WHERE status = 'success' AND platform = ANY(%s) "
        "ORDER BY finished_at DESC LIMIT %s",
        [platforms, len(platforms) * 5],
    )
    result: dict[str, dict] = {}
    for row in rows:
        p = row["platform"]
        if p not in result:
            result[p] = row
    return result


def orphan_stale_runs(max_age_hours: int = 2) -> int:
    return pgpool.execute(
        "UPDATE scraper_runs SET status = 'failed', finished_at = now(), "
        "error_msg = 'orphaned — backend restarted' "
        "WHERE status = 'running' AND started_at < now() - make_interval(hours => %s)",
        [max_age_hours],
    )
```

- [ ] **Step 2: Replace the listing/menu/promo writers**

Replace `upsert_listing`, `patch_listing`, `upsert_promotions`, `delete_menu_items`, `insert_menu_items`:

```python
def upsert_listing(data: dict) -> str:
    sql, params = _build_insert(
        "platform_listings", data, on_conflict="restaurant_id,platform"
    )
    row = pgpool.fetchone(sql, params)
    return str(row["id"])


def patch_listing(listing_id: str, data: dict) -> None:
    sql, params = _build_update("platform_listings", data, "id", listing_id)
    pgpool.execute(sql, params)


def upsert_promotions(listing_id: str, promotions: list[dict]) -> int:
    pgpool.execute("DELETE FROM promotions WHERE listing_id = %s", [listing_id])
    if not promotions:
        return 0
    saved = 0
    for p in promotions:
        sql, params = _build_insert("promotions", {"listing_id": listing_id, **p})
        pgpool.fetchone(sql, params)
        saved += 1
    return saved


def delete_menu_items(listing_id: str) -> None:
    pgpool.execute("DELETE FROM menu_items WHERE listing_id = %s", [listing_id])


def insert_menu_items(listing_id: str, items: list[dict]) -> int:
    pgpool.execute("DELETE FROM menu_items WHERE listing_id = %s", [listing_id])
    pgpool.execute(
        "UPDATE platform_listings SET last_scraped_at = now() WHERE id = %s",
        [listing_id],
    )
    if not items:
        return 0
    total = 0
    with pgpool.get_pool().connection() as conn, conn.cursor() as cur:
        for i in range(0, len(items), _MENU_INSERT_CHUNK):
            chunk = items[i : i + _MENU_INSERT_CHUNK]
            for item in chunk:
                row = {**item, "listing_id": listing_id}
                cols = ", ".join(row.keys())
                ph = ", ".join(["%s"] * len(row))
                cur.execute(
                    f"INSERT INTO menu_items ({cols}) VALUES ({ph})",
                    [_coerce(v) for v in row.values()],
                )
                total += 1
    return total
```

> `on_conflict="restaurant_id,platform"` produces `ON CONFLICT (restaurant_id,platform)` — a valid composite conflict target matching the unique index from migration `009_unique_restaurant_platform.sql`.

- [ ] **Step 3: Verify the module still imports**

Run: `uv run python -c "import db; print('ok')"`
Expected: `ok` (no `supabase` import error).

- [ ] **Step 4: Commit**

```bash
git add backend/db.py
git commit -m "feat(db): rewrite run-tracking + listing/menu writers to psycopg3"
```

### Task 8: Rewrite upsert_restaurant + the domain cache

**Files:**
- Modify: `backend/db.py`

This is the highest-risk function — a 5-step cross-platform match. Preserve the escalation order and the `_found` partial-update semantics exactly.

- [ ] **Step 1: Replace `get_client`/`close_client`/`_client` globals**

Delete the `_client`, `_client_lock`, `get_client`, `close_client` definitions. Keep `_domain_cache` and `invalidate_domain_cache`. Add a `close_client` shim so `main.py`/any caller during transition still works:

```python
_domain_cache: dict[str, str] | None = None  # domain → restaurant_id


def invalidate_domain_cache() -> None:
    global _domain_cache
    _domain_cache = None


def close_client() -> None:
    """Back-compat shim — closes the psycopg pool."""
    pgpool.close_pool()
```

- [ ] **Step 2: Replace `upsert_restaurant`**

```python
def upsert_restaurant(data: dict) -> str:
    """Match restaurant by name across platforms, insert if new. Returns id.

    5 escalating steps: exact → case-insensitive → domain lock → canonical base
    → suffixed variant → fully-normalized.
    """
    name: str = data["name"].strip()
    data = {**data, "name": name}

    if _is_junk(name):
        raise ValueError(f"Junk entry skipped: {name!r}")

    canonical = _canonical(name)
    norm = _normalize_for_match(name)
    norm_canonical = _normalize_for_match(canonical)

    if not data.get("cuisine"):
        data = {**data, "cuisine": infer_cuisine(name)}

    _MATCH_COLS = "id, cuisine, image_url, lat, lng, geo_source"

    def _found(rid: str, row: dict | None = None) -> str:
        if row is None:
            row = pgpool.fetchone(
                "SELECT cuisine, image_url, lat, lng, geo_source, phone, neighborhood "
                "FROM restaurants WHERE id = %s LIMIT 1", [rid]
            ) or {}
        updates: dict = {}
        if data.get("cuisine") and not row.get("cuisine"):
            updates["cuisine"] = data["cuisine"]
        if data.get("image_url") and not row.get("image_url"):
            updates["image_url"] = data["image_url"]
        if data.get("phone") and not row.get("phone"):
            updates["phone"] = data["phone"]
        if data.get("neighborhood") and not row.get("neighborhood"):
            updates["neighborhood"] = data["neighborhood"]
        incoming_src = data.get("geo_source")
        _VENUE = {"uber_eats", "direct", "takeaway"}
        if data.get("lat") is not None and data.get("lng") is not None:
            if incoming_src in _VENUE:
                updates["lat"] = data["lat"]
                updates["lng"] = data["lng"]
                updates["geo_source"] = incoming_src
            elif incoming_src == "deliveroo_venue" and row.get("geo_source") not in _VENUE:
                updates["lat"] = data["lat"]
                updates["lng"] = data["lng"]
                updates["geo_source"] = incoming_src
            elif row.get("lat") is None:
                updates["lat"] = data["lat"]
                updates["lng"] = data["lng"]
                if incoming_src:
                    updates["geo_source"] = incoming_src
        if updates:
            sql, params = _build_update("restaurants", updates, "id", rid)
            pgpool.execute(sql, params)
        return str(rid)

    # 1. Exact name match
    row = pgpool.fetchone(
        f"SELECT {_MATCH_COLS} FROM restaurants WHERE name = %s LIMIT 1", [name]
    )
    if row:
        return _found(row["id"], row)

    # 2. Case-insensitive exact match
    row = pgpool.fetchone(
        f"SELECT {_MATCH_COLS} FROM restaurants WHERE name ILIKE %s LIMIT 1", [name]
    )
    if row:
        return _found(row["id"], row)

    # 2b. Website-domain lock
    import matching as _m
    incoming_domain = _m.domain_of(data.get("website"))
    if incoming_domain:
        global _domain_cache
        if _domain_cache is None:
            cands = pgpool.fetchall(
                "SELECT id, website FROM restaurants WHERE website IS NOT NULL"
            )
            _domain_cache = {}
            for c in cands:
                d = _m.domain_of(c.get("website"))
                if d:
                    _domain_cache[d] = c["id"]
        if incoming_domain in _domain_cache:
            return _found(_domain_cache[incoming_domain])

    # 3. Canonical base match
    if canonical != name:
        row = pgpool.fetchone(
            f"SELECT {_MATCH_COLS} FROM restaurants WHERE name ILIKE %s LIMIT 1",
            [canonical],
        )
        if row:
            return _found(row["id"], row)

    # 4. Suffixed variant match ("Burger King" → "Burger King - Ixelles")
    row = pgpool.fetchone(
        f"SELECT {_MATCH_COLS} FROM restaurants WHERE name ILIKE %s LIMIT 1",
        [f"{canonical} -%"],
    )
    if row:
        return _found(row["id"], row)

    # 5. Fully-normalized match by significant-word prefix
    _ARTICLES = {"le", "la", "les", "l'", "au", "aux", "un", "une", "de", "du", "the", "a"}
    words = canonical.split()
    sig_words = [w for w in words if w.lower().rstrip("'") not in _ARTICLES]
    prefix = sig_words[0] if sig_words else (words[0] if words else canonical[:5])
    if len(prefix) >= 3:
        candidates = pgpool.fetchall(
            f"SELECT name, {_MATCH_COLS} FROM restaurants WHERE name ILIKE %s",
            [f"{prefix}%"],
        )
        for cand in candidates:
            cand_norm = _normalize_for_match(cand["name"])
            cand_norm_can = _normalize_for_match(_canonical(cand["name"]))
            if cand_norm in (norm, norm_canonical) or cand_norm_can in (norm, norm_canonical):
                return _found(cand["id"], cand)

    # Not found — insert
    sql, params = _build_insert("restaurants", data, on_conflict="slug")
    row = pgpool.fetchone(sql, params)
    rid = str(row["id"])
    invalidate_domain_cache()
    return rid
```

> ILIKE special-char note: PostgREST's `.ilike` and SQL `ILIKE` both treat `%`/`_` as wildcards. Step 4's `f"{canonical} -%"` intentionally uses a trailing `%` wildcard (same as the original). Steps 1–3 pass literal names; if a name contains a literal `%`/`_` the behavior is unchanged from the Supabase version (which had the same property), so no escaping is added — preserving exact current behavior.

- [ ] **Step 3: Verify import**

Run: `uv run python -c "import db; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/db.py
git commit -m "feat(db): rewrite upsert_restaurant matching to psycopg3"
```

### Task 9: Rewrite remaining admin/query/match helpers

**Files:**
- Modify: `backend/db.py`

- [ ] **Step 1: Replace the simple readers/patchers**

Replace `get_restaurants`, `set_restaurant_chain`, `get_menu_items`, `get_listings_with_urls`, `patch_restaurant_geo`, `patch_restaurant_website`, `patch_restaurant_phone`, `mark_restaurant_searched`, `delete_stale_listings`, `prune_stale_menu_items`:

```python
def get_restaurants(limit: int = 100, offset: int = 0, search: str | None = None) -> list[dict]:
    if search:
        return pgpool.fetchall(
            "SELECT * FROM restaurants WHERE name ILIKE %s ORDER BY id LIMIT %s OFFSET %s",
            [f"%{search}%", limit, offset],
        )
    return pgpool.fetchall(
        "SELECT * FROM restaurants ORDER BY id LIMIT %s OFFSET %s", [limit, offset]
    )


def set_restaurant_chain(restaurant_id: str, is_chain: bool) -> dict:
    return pgpool.fetchone(
        "UPDATE restaurants SET is_chain = %s WHERE id = %s RETURNING *",
        [is_chain, restaurant_id],
    )


def get_menu_items(listing_id: str) -> list[dict]:
    return pgpool.fetchall(
        "SELECT * FROM menu_items WHERE listing_id = %s LIMIT 2000", [listing_id]
    )


def get_listings_with_urls(platform: str) -> list[dict]:
    return pgpool.fetchall(
        "SELECT id, restaurant_id, url, delivery_fee, min_order FROM platform_listings "
        "WHERE platform = %s AND url IS NOT NULL",
        [platform],
    )


def patch_restaurant_geo(restaurant_id: str, lat: float, lng: float, geo_source: str) -> None:
    existing = pgpool.fetchone(
        "SELECT geo_source FROM restaurants WHERE id = %s LIMIT 1", [restaurant_id]
    )
    if existing:
        current_src = existing.get("geo_source")
        if _GEO_RANK.get(current_src, 0) >= _GEO_RANK.get(geo_source, 0):
            return
    pgpool.execute(
        "UPDATE restaurants SET lat = %s, lng = %s, geo_source = %s WHERE id = %s",
        [lat, lng, geo_source, restaurant_id],
    )


def patch_restaurant_website(restaurant_id: str, website: str | None, order_url: str | None) -> None:
    pgpool.execute(
        "UPDATE restaurants SET website = %s, order_url = %s, website_searched_at = now() "
        "WHERE id = %s",
        [website, order_url, restaurant_id],
    )
    invalidate_domain_cache()


def patch_restaurant_phone(restaurant_id: str, phone: str) -> None:
    existing = pgpool.fetchone(
        "SELECT phone FROM restaurants WHERE id = %s LIMIT 1", [restaurant_id]
    )
    if existing and not existing.get("phone"):
        pgpool.execute(
            "UPDATE restaurants SET phone = %s WHERE id = %s", [phone, restaurant_id]
        )


def mark_restaurant_searched(restaurant_id: str) -> None:
    pgpool.execute(
        "UPDATE restaurants SET website_searched_at = now() WHERE id = %s",
        [restaurant_id],
    )


def delete_stale_listings(days: int = 30) -> int:
    return pgpool.execute(
        "DELETE FROM platform_listings WHERE last_scraped_at IS NOT NULL "
        "AND last_scraped_at < now() - make_interval(days => %s)",
        [days],
    )


def prune_stale_menu_items(days: int = 30) -> int:
    stale = pgpool.fetchall(
        "SELECT id FROM platform_listings WHERE last_scraped_at IS NOT NULL "
        "AND last_scraped_at < now() - make_interval(days => %s)",
        [days],
    )
    if not stale:
        return 0
    ids = [row["id"] for row in stale]
    return pgpool.execute(
        "DELETE FROM menu_items WHERE listing_id = ANY(%s)", [ids]
    )
```

> `ANY(%s)` with a Python list replaces PostgREST's chunked `.in_()` — there's no URL-length limit in a real SQL bind, so the manual 200-item chunking is dropped.

- [ ] **Step 2: Replace claims functions**

Replace `insert_claim`, `get_claims`, `approve_claim`, `reject_claim` (keep `_validate_order_url` unchanged):

```python
def insert_claim(owner_email: str, inquiry_type: str = "add_url",
                 restaurant_id: str | None = None, direct_order_url: str | None = None,
                 restaurant_name_free: str | None = None) -> str:
    row = pgpool.fetchone(
        "INSERT INTO restaurant_claims "
        "(restaurant_id, owner_email, direct_order_url, inquiry_type, "
        " restaurant_name_free, verified) "
        "VALUES (%s, %s, %s, %s, %s, false) RETURNING id",
        [restaurant_id, owner_email, direct_order_url, inquiry_type, restaurant_name_free],
    )
    return str(row["id"])


def get_claims(verified: bool | None = None) -> list[dict]:
    base = (
        "SELECT c.id, c.restaurant_id, c.owner_email, c.direct_order_url, "
        "c.inquiry_type, c.restaurant_name_free, c.verified, c.claimed_at, "
        "json_build_object('name', r.name) AS restaurants "
        "FROM restaurant_claims c LEFT JOIN restaurants r ON r.id = c.restaurant_id"
    )
    if verified is not None:
        return pgpool.fetchall(
            base + " WHERE c.verified = %s ORDER BY c.claimed_at DESC", [verified]
        )
    return pgpool.fetchall(base + " ORDER BY c.claimed_at DESC")


def approve_claim(claim_id: str) -> None:
    claim = pgpool.fetchone(
        "SELECT id, restaurant_id, direct_order_url, inquiry_type "
        "FROM restaurant_claims WHERE id = %s", [claim_id]
    )
    if not claim:
        raise ValueError(f"Claim not found: {claim_id!r}")
    if (claim.get("inquiry_type") == "add_url" and claim.get("restaurant_id")
            and claim.get("direct_order_url")):
        _validate_order_url(claim["direct_order_url"])
        pgpool.execute(
            "UPDATE restaurants SET order_url = %s WHERE id = %s",
            [claim["direct_order_url"], claim["restaurant_id"]],
        )
        upsert_listing({
            "restaurant_id": claim["restaurant_id"],
            "platform": "direct",
            "url": claim["direct_order_url"],
            "is_available": True,
        })
    pgpool.execute(
        "UPDATE restaurant_claims SET verified = true WHERE id = %s", [claim_id]
    )


def reject_claim(claim_id: str) -> None:
    pgpool.execute("DELETE FROM restaurant_claims WHERE id = %s", [claim_id])
```

- [ ] **Step 3: Replace match helpers**

Replace `load_restaurants_for_match`, `enqueue_decision`, `merge_restaurants`, `delete_decisions`, `get_stale_queued_decisions`, `get_queued_decisions`, `resolve_decision`, `load_menu_items_for_match`, `load_slugs_for_match`, `load_listing_addresses_for_match`:

```python
def load_restaurants_for_match() -> list[dict]:
    return pgpool.fetchall(
        "SELECT id, name, website, phone, lat, lng, geo_source, cuisine, created_at, "
        "is_chain FROM restaurants WHERE merged_into IS NULL ORDER BY id"
    )


def enqueue_decision(*, survivor_id: str, loser_id: str, score: float,
                     features: dict, status: str) -> str:
    s = _validate_uuid(survivor_id)
    l = _validate_uuid(loser_id)
    if s == l:
        raise ValueError("survivor_id and loser_id must differ")
    existing = pgpool.fetchone(
        "SELECT id FROM restaurant_match_decisions "
        "WHERE (survivor_id = %s AND loser_id = %s) "
        "   OR (survivor_id = %s AND loser_id = %s) LIMIT 1",
        [s, l, l, s],
    )
    if existing:
        did = existing["id"]
        pgpool.execute(
            "UPDATE restaurant_match_decisions "
            "SET survivor_id = %s, loser_id = %s, score = %s, features = %s, status = %s "
            "WHERE id = %s",
            [survivor_id, loser_id, score, _coerce(features), status, did],
        )
        return str(did)
    row = pgpool.fetchone(
        "INSERT INTO restaurant_match_decisions "
        "(survivor_id, loser_id, score, features, status) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        [survivor_id, loser_id, score, _coerce(features), status],
    )
    return str(row["id"])


def merge_restaurants(survivor_id: str, loser_id: str) -> None:
    if survivor_id == loser_id:
        return
    s = _validate_uuid(survivor_id)
    l = _validate_uuid(loser_id)
    pgpool.execute("SELECT merge_restaurants_atomic(%s, %s)", [s, l])


def delete_decisions(ids: list[str]) -> None:
    if not ids:
        return
    validated = [_validate_uuid(i) for i in ids]
    pgpool.execute(
        "DELETE FROM restaurant_match_decisions WHERE id = ANY(%s)", [validated]
    )


def get_stale_queued_decisions() -> list[dict]:
    rows = pgpool.fetchall(
        "SELECT * FROM restaurant_match_decisions WHERE status = 'queued'"
    )
    return [r for r in rows if (r.get("features") or {}).get("geo_dist") is None]


def get_queued_decisions(limit: int = 100, offset: int = 0) -> list[dict]:
    rows = pgpool.fetchall(
        "SELECT * FROM restaurant_match_decisions WHERE status = 'queued' "
        "ORDER BY created_at DESC LIMIT %s OFFSET %s",
        [limit, offset],
    )
    if not rows:
        return rows
    rid_set: set[str] = set()
    for d in rows:
        if d.get("survivor_id"):
            rid_set.add(d["survivor_id"])
        if d.get("loser_id"):
            rid_set.add(d["loser_id"])
    listings_by_rid: dict[str, list[dict]] = {}
    if rid_set:
        lrows = pgpool.fetchall(
            "SELECT restaurant_id, platform, url FROM platform_listings "
            "WHERE restaurant_id = ANY(%s)",
            [list(rid_set)],
        )
        for row in lrows:
            rid = row.get("restaurant_id")
            if not rid or not row.get("url"):
                continue
            listings_by_rid.setdefault(rid, []).append(
                {"platform": row.get("platform"), "url": row["url"]}
            )
    for d in rows:
        d["survivor_listings"] = listings_by_rid.get(d.get("survivor_id"), [])
        d["loser_listings"] = listings_by_rid.get(d.get("loser_id"), [])
    return rows


def resolve_decision(decision_id: str, *, approve: bool, resolved_by: str) -> None:
    d = pgpool.fetchone(
        "SELECT id, survivor_id, loser_id, status FROM restaurant_match_decisions "
        "WHERE id = %s LIMIT 1", [decision_id]
    )
    if not d:
        return
    if approve:
        merge_restaurants(d["survivor_id"], d["loser_id"])
    pgpool.execute(
        "UPDATE restaurant_match_decisions SET status = %s, resolved_at = now(), "
        "resolved_by = %s WHERE id = %s",
        ["approved" if approve else "rejected", resolved_by, decision_id],
    )


def load_menu_items_for_match() -> dict[str, set[str]]:
    import re as _re
    import unicodedata as _ud
    rows = pgpool.fetchall(
        "SELECT mi.title, pl.restaurant_id "
        "FROM menu_items mi JOIN platform_listings pl ON pl.id = mi.listing_id"
    )
    result: dict[str, set[str]] = {}
    for row in rows:
        rid = str(row.get("restaurant_id") or "")
        if not rid or rid == "None":
            continue
        raw = row.get("title") or ""
        nfkd = _ud.normalize("NFD", raw)
        no_acc = "".join(ch for ch in nfkd if _ud.category(ch) != "Mn")
        norm = _re.sub(r"[^a-z0-9]", "", no_acc.lower())
        if norm and len(norm) >= 3:
            result.setdefault(rid, set()).add(norm)
    return result


def load_slugs_for_match() -> dict[str, list[str]]:
    from urllib.parse import urlparse
    rows = pgpool.fetchall(
        "SELECT restaurant_id, url FROM platform_listings WHERE url IS NOT NULL"
    )
    result: dict[str, list[str]] = {}
    for row in rows:
        rid = str(row.get("restaurant_id") or "")
        url = row.get("url") or ""
        if not rid or rid == "None" or not url:
            continue
        try:
            path = urlparse(url).path.rstrip("/")
            segments = [s for s in path.split("/") if s]
            slug = None
            for seg in reversed(segments):
                if len(seg) >= 3 and not re.match(r'^[A-Za-z0-9_\-]{20,}$', seg):
                    slug = seg
                    break
            if slug:
                result.setdefault(rid, []).append(slug)
        except Exception:
            continue
    return result


def load_listing_addresses_for_match() -> dict[str, dict]:
    rows = pgpool.fetchall(
        "SELECT restaurant_id, street_address, postal_code FROM platform_listings "
        "WHERE street_address IS NOT NULL"
    )
    result: dict[str, dict] = {}
    for row in rows:
        rid = str(row.get("restaurant_id") or "")
        if not rid or rid == "None":
            continue
        if rid not in result or (not result[rid].get("postal_code") and row.get("postal_code")):
            result[rid] = {
                "street_address": row.get("street_address"),
                "postal_code": row.get("postal_code"),
            }
    return result
```

- [ ] **Step 4: Verify the whole module imports and no `get_client` references remain**

Run: `uv run python -c "import db; print('ok')"` → Expected: `ok`
Run: `grep -n "get_client\|\.table(\|\.execute()\|supabase" db.py` → Expected: **no output** (every Supabase call removed).

- [ ] **Step 5: Run the existing backend test suite**

Run: `uv run pytest -q`
Expected: PASS (pure-logic tests for matching/promos/direct_menu don't touch the DB). Any test that imported `supabase` or called `get_client` must be updated to use `pgpool`/`TEST_DATABASE_URL` or marked skip — fix inline.

- [ ] **Step 6: Commit**

```bash
git add backend/db.py
git commit -m "feat(db): rewrite admin/query/claims/match helpers to psycopg3"
```

### Task 10: Add public-read DB functions (nested JSON)

**Files:**
- Modify: `backend/db.py` (append a "Public reads" section)
- Test: `backend/tests/test_public_reads.py`

These return the exact PostgREST-shaped nested JSON the frontend `queries.ts` transform already consumes, built server-side with `json_build_object` + `json_agg`.

- [ ] **Step 1: Write the failing integration test**

Create `backend/tests/test_public_reads.py`:

```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)


@pytest.fixture()
def seeded(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    import pgpool, db
    pgpool.close_pool()
    pgpool.execute("TRUNCATE restaurants, platform_listings, menu_items, promotions, scraper_runs RESTART IDENTITY CASCADE")
    rid = db.upsert_restaurant({"name": "Test Diner", "slug": "test-diner", "cuisine": "Burgers"})
    lid = db.upsert_listing({"restaurant_id": rid, "platform": "uber_eats", "url": "https://x", "delivery_fee": 2.5, "eta_min": 20, "is_available": True})
    db.insert_menu_items(lid, [{"title": "Cheeseburger", "price": 9.0}])
    return rid


def test_public_restaurants_shape(seeded):
    import db
    rows = db.get_public_restaurants()
    assert len(rows) == 1
    r = rows[0]
    assert r["name"] == "Test Diner"
    assert isinstance(r["platform_listings"], list)
    assert r["platform_listings"][0]["platform"] == "uber_eats"


def test_public_detail_shape(seeded):
    import db
    detail = db.get_public_restaurant_detail(seeded)
    assert detail["name"] == "Test Diner"
    listing = detail["platform_listings"][0]
    assert listing["menu_items"][0]["title"] == "Cheeseburger"


def test_public_detail_missing_returns_none(seeded):
    import db
    assert db.get_public_restaurant_detail("00000000-0000-0000-0000-000000000000") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `TEST_DATABASE_URL=postgresql://localhost/forkeur_test uv run pytest tests/test_public_reads.py -v`
Expected: FAIL (`AttributeError: ... 'get_public_restaurants'`). (Requires the test DB to have the schema — apply `selfhosted_schema.sql` to `forkeur_test` first: `psql forkeur_test -f ../ops/selfhosted_schema.sql` or reuse the dump.)

- [ ] **Step 3: Implement the public-read functions**

Append to `backend/db.py`:

```python
# ---------------------------------------------------------------------------
# Public reads (frontend) — return PostgREST-shaped nested JSON
# ---------------------------------------------------------------------------

def get_public_restaurants() -> list[dict]:
    """Homepage: every non-merged restaurant with its listings (short shape)."""
    return pgpool.fetchall(
        """
        SELECT r.id, r.name, r.cuisine, r.neighborhood, r.lat, r.lng,
               r.order_url, r.image_url, r.is_chain,
               COALESCE(
                 json_agg(
                   json_build_object(
                     'platform', pl.platform, 'delivery_fee', pl.delivery_fee,
                     'eta_min', pl.eta_min, 'url_type', pl.url_type,
                     'is_available', pl.is_available, 'opening_hours', pl.opening_hours,
                     'last_scraped_at', pl.last_scraped_at
                   )
                 ) FILTER (WHERE pl.id IS NOT NULL), '[]'
               ) AS platform_listings
        FROM restaurants r
        LEFT JOIN platform_listings pl ON pl.restaurant_id = r.id
        WHERE r.merged_into IS NULL
        GROUP BY r.id
        """
    )


def get_public_restaurant_detail(restaurant_id: str) -> dict | None:
    """Detail page: one restaurant, listings with nested menu_items + promotions."""
    _validate_uuid(restaurant_id)
    return pgpool.fetchone(
        """
        SELECT r.id, r.name, r.neighborhood, r.cuisine, r.phone,
               r.order_url, r.image_url,
               COALESCE(
                 json_agg(
                   json_build_object(
                     'id', pl.id, 'platform', pl.platform, 'url', pl.url,
                     'url_type', pl.url_type, 'is_available', pl.is_available,
                     'opening_hours', pl.opening_hours, 'delivery_fee', pl.delivery_fee,
                     'min_order', pl.min_order, 'eta_min', pl.eta_min,
                     'eta_max', pl.eta_max, 'rating', pl.rating,
                     'last_scraped_at', pl.last_scraped_at,
                     'menu_items', COALESCE((
                       SELECT json_agg(json_build_object(
                         'title', mi.title, 'price', mi.price,
                         'catalog_name', mi.catalog_name, 'image_url', mi.image_url,
                         'description', mi.description))
                       FROM menu_items mi WHERE mi.listing_id = pl.id), '[]'),
                     'promotions', COALESCE((
                       SELECT json_agg(json_build_object(
                         'promo_type', pr.promo_type, 'label', pr.label, 'value', pr.value))
                       FROM promotions pr WHERE pr.listing_id = pl.id), '[]')
                   )
                 ) FILTER (WHERE pl.id IS NOT NULL), '[]'
               ) AS platform_listings
        FROM restaurants r
        LEFT JOIN platform_listings pl ON pl.restaurant_id = r.id
        WHERE r.id = %s
        GROUP BY r.id
        """,
        [restaurant_id],
    )


def get_public_deals() -> list[dict]:
    """Deals page: promotions joined to listing + restaurant (nested shape)."""
    return pgpool.fetchall(
        """
        SELECT p.id, p.promo_type, p.label, p.value, p.min_order,
               json_build_object(
                 'platform', pl.platform, 'url', pl.url, 'rating', pl.rating,
                 'review_count', pl.review_count, 'is_available', pl.is_available,
                 'opening_hours', pl.opening_hours,
                 'restaurants', json_build_object(
                   'id', r.id, 'name', r.name, 'cuisine', r.cuisine,
                   'neighborhood', r.neighborhood)
               ) AS platform_listings
        FROM promotions p
        JOIN platform_listings pl ON pl.id = p.listing_id
        JOIN restaurants r ON r.id = pl.restaurant_id
        WHERE p.promo_type NOT IN ('other', 'spend_save')
        """
    )


def get_latest_run(platform: str, since_iso: str | None = None) -> dict | None:
    """Most recent run for a platform, optionally only if started since a cutoff."""
    if since_iso:
        return pgpool.fetchone(
            "SELECT started_at FROM scraper_runs WHERE platform = %s "
            "AND started_at >= %s ORDER BY started_at DESC LIMIT 1",
            [platform, since_iso],
        )
    return pgpool.fetchone(
        "SELECT started_at FROM scraper_runs WHERE platform = %s "
        "ORDER BY started_at DESC LIMIT 1",
        [platform],
    )
```

- [ ] **Step 4: Run to verify the tests pass**

Run: `TEST_DATABASE_URL=postgresql://localhost/forkeur_test uv run pytest tests/test_public_reads.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/db.py backend/tests/test_public_reads.py
git commit -m "feat(db): add public-read functions returning nested JSON"
```

### Task 11: Public router + wire into main.py

**Files:**
- Create: `backend/routers/public.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_public_router.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_public_router.py`:

```python
import os
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set"
)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-pw")
    import pgpool
    pgpool.close_pool()
    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)


def test_public_restaurants_is_unauthenticated(client):
    r = client.get("/api/public/restaurants")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_public_detail_404(client):
    r = client.get("/api/public/restaurants/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `TEST_DATABASE_URL=postgresql://localhost/forkeur_test uv run pytest tests/test_public_router.py -v`
Expected: FAIL (route 404 because router not registered, or 401 because middleware blocks it).

- [ ] **Step 3: Write `backend/routers/public.py`**

```python
"""Unauthenticated read endpoints for the Next.js frontend.

These mirror the exact nested JSON shapes the frontend's lib/queries.ts
transform consumes (previously fetched from Supabase PostgREST).
"""
import asyncio

from fastapi import APIRouter, HTTPException

import db

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/restaurants")
async def public_restaurants():
    return await asyncio.to_thread(db.get_public_restaurants)


@router.get("/restaurants/{restaurant_id}")
async def public_restaurant_detail(restaurant_id: str):
    try:
        row = await asyncio.to_thread(db.get_public_restaurant_detail, restaurant_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return row


@router.get("/deals")
async def public_deals():
    return await asyncio.to_thread(db.get_public_deals)


@router.get("/scraper-runs/latest")
async def public_latest_run(platform: str = "fees", since: str | None = None):
    return await asyncio.to_thread(db.get_latest_run, platform, since)
```

- [ ] **Step 4: Wire into `backend/main.py`**

Make four edits:

(a) Import the public router — change line 17–18:

```python
from routers import scrapers, runs, schedule, data, websites, claims as claims_router_mod, cleanup, public
from routers.auth_router import router as auth_router
```

(b) Allowlist `/api/public/` in `AuthMiddleware.dispatch` — after the `_PUBLIC_POST_PATHS` block (line 35–36), add:

```python
        # Public read API for the frontend — unauthenticated GETs.
        if path.startswith("/api/public/") and request.method == "GET":
            return await call_next(request)
```

(c) Swap required env — change line 50:

```python
_REQUIRED_ENV = ("DATABASE_URL", "JWT_SECRET", "ADMIN_PASSWORD")
```

(d) Open the pool in lifespan + register the router. Change the lifespan startup (after `_check_required_env()`, line 63) to warm the pool, and register the router after line 97:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_required_env()
    import db
    import pgpool
    pgpool.get_pool()  # open the pool eagerly so a bad DATABASE_URL fails fast
    cleaned = db.orphan_stale_runs(max_age_hours=0)
    if cleaned:
        import logging
        logging.getLogger(__name__).warning("Startup: marked %d orphaned runs as failed", cleaned)
    sched.start()
    yield
    sched.shutdown()
    db.close_client()  # closes the pool via the back-compat shim
```

And add after the other `include_router` calls:

```python
app.include_router(public.router, prefix="/api")
```

- [ ] **Step 5: Run to verify the tests pass**

Run: `TEST_DATABASE_URL=postgresql://localhost/forkeur_test uv run pytest tests/test_public_router.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Run the full backend suite**

Run: `uv run pytest -q`
Expected: PASS (DB-bound tests skip without `TEST_DATABASE_URL`).

- [ ] **Step 7: Commit**

```bash
git add backend/routers/public.py backend/main.py backend/tests/test_public_router.py
git commit -m "feat(api): add unauthenticated public read router, wire pool into lifespan"
```

---

## Phase C — Frontend: route reads through FastAPI

### Task 12: Backend fetch helper

**Files:**
- Create: `forkeur-app/lib/backend.ts`
- Test: `forkeur-app/__tests__/backend.test.ts`

- [ ] **Step 1: Write the failing test**

Create `forkeur-app/__tests__/backend.test.ts`:

```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { backendFetch } from '../lib/backend'

afterEach(() => vi.restoreAllMocks())

describe('backendFetch', () => {
  it('returns parsed JSON on 200', async () => {
    vi.stubGlobal('fetch', vi.fn(async () =>
      new Response(JSON.stringify([{ id: '1' }]), { status: 200 })
    ))
    const data = await backendFetch<{ id: string }[]>('/api/public/restaurants')
    expect(data).toEqual([{ id: '1' }])
  })

  it('throws on non-OK status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 500 })))
    await expect(backendFetch('/api/public/deals')).rejects.toThrow('backend 500')
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd forkeur-app && npm test -- backend.test.ts`
Expected: FAIL (`Cannot find module '../lib/backend'`).

- [ ] **Step 3: Write `forkeur-app/lib/backend.ts`**

```ts
export const BACKEND_URL = process.env.BACKEND_URL ?? 'http://localhost:8000'

/**
 * Server-side fetch to the FastAPI backend. ISR-friendly: callers pass a
 * revalidate window. Throws on non-OK so callers fail loudly (matching the old
 * `if (error) throw` Supabase behavior).
 */
export async function backendFetch<T>(
  path: string,
  init?: RequestInit & { revalidate?: number }
): Promise<T> {
  const { revalidate, ...rest } = init ?? {}
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...rest,
    next: revalidate != null ? { revalidate } : undefined,
  })
  if (!res.ok) throw new Error(`backend ${res.status}: ${path}`)
  return res.json() as Promise<T>
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm test -- backend.test.ts`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add forkeur-app/lib/backend.ts forkeur-app/__tests__/backend.test.ts
git commit -m "feat(app): add backendFetch helper centralizing BACKEND_URL"
```

### Task 13: Swap queries.ts data source

**Files:**
- Modify: `forkeur-app/lib/queries.ts`

The transform logic stays — only the data acquisition changes. Endpoints return the same raw nested shapes the Supabase embeds returned, so the `RawRestaurantRow`/`RawPromoRow`/`RawRestaurantDetail` cast paths are untouched.

- [ ] **Step 1: Replace the imports + delete `getSupabase`**

Change lines 1–7:

```ts
import { cache } from 'react'
import type { Platform } from '@/lib/basket'
import type { DealItem, DealType } from '@/lib/deals'
import { normalizeTitle } from '@/lib/normalize-title'
import { backendFetch } from '@/lib/backend'
export { normalizeTitle }
```

Delete the `getSupabase` function (lines 160–163):

```ts
async function getSupabase() {
  const cookieStore = await cookies()
  return createClient(cookieStore)
}
```

- [ ] **Step 2: Rewrite `getRestaurants` data fetch**

Replace lines 183–192 (the `const supabase = ...` through the `if (error) throw` block) with:

```ts
  const data = await backendFetch<RawRestaurantRow[]>(
    '/api/public/restaurants',
    { revalidate: 3600 }
  )
```

The rest of `getRestaurants` (the `.map(...)` transform over `(data ?? [])`) is unchanged.

- [ ] **Step 3: Rewrite `getDeals` data fetch**

Replace lines 292–306 (`const supabase = ...` through `if (error) throw`) with:

```ts
  const data = await backendFetch<RawPromoRow[]>(
    '/api/public/deals',
    { revalidate: 3600 }
  )
```

The `.flatMap(...)` transform is unchanged.

- [ ] **Step 4: Rewrite `getRestaurantWithListings` data fetch**

Replace lines 336–352 (`const supabase = ...` through `if (error) return null`) with:

```ts
  const data = await backendFetch<RawRestaurantDetail | null>(
    `/api/public/restaurants/${encodeURIComponent(id)}`,
    { revalidate: 3600 }
  ).catch(() => null)
  if (!data) return null
```

The `raw`/`listings`/`itemMap` transform below is unchanged.

- [ ] **Step 5: Type-check + run query tests**

Run: `cd forkeur-app && npx tsc --noEmit && npm test -- queries.test.ts`
Expected: no type errors; `queries.test.ts` (tests `normalizeTitle`, a pure export) PASS.

- [ ] **Step 6: Commit**

```bash
git add forkeur-app/lib/queries.ts
git commit -m "feat(app): route queries.ts reads through FastAPI backend"
```

### Task 14: Swap sitemap.ts + refresh route

**Files:**
- Modify: `forkeur-app/app/sitemap.ts`
- Modify: `forkeur-app/app/api/refresh/route.ts`

- [ ] **Step 1: Rewrite `app/sitemap.ts`**

Replace the whole file:

```ts
import type { MetadataRoute } from 'next'
import { backendFetch } from '@/lib/backend'

const BASE_URL = 'https://forkeur.be'

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  let restaurants: { id: string }[] = []
  try {
    restaurants = await backendFetch<{ id: string }[]>(
      '/api/public/restaurants',
      { revalidate: 3600 }
    )
  } catch {
    restaurants = []
  }

  const restaurantUrls: MetadataRoute.Sitemap = restaurants.slice(0, 2000).map((r) => ({
    url: `${BASE_URL}/restaurant/${r.id}`,
    changeFrequency: 'daily',
    priority: 0.7,
  }))

  return [
    { url: BASE_URL, changeFrequency: 'daily', priority: 1.0 },
    { url: `${BASE_URL}/deals`, changeFrequency: 'daily', priority: 0.8 },
    { url: `${BASE_URL}/owners`, changeFrequency: 'monthly', priority: 0.4 },
    ...restaurantUrls,
  ]
}
```

- [ ] **Step 2: Rewrite the cooldown check in `app/api/refresh/route.ts`**

Replace the import on line 4:

```ts
import { backendFetch } from '@/lib/backend'
```

Replace the cooldown `try { const supabase = ... }` block (lines 34–52) with:

```ts
  // DB-backed cooldown via the backend public endpoint. Fail-open on error.
  try {
    const since = new Date(now - COOLDOWN_MS).toISOString()
    const latest = await backendFetch<{ started_at: string } | null>(
      `/api/public/scraper-runs/latest?platform=fees&since=${encodeURIComponent(since)}`
    )
    if (latest && latest.started_at) {
      return NextResponse.json({ ok: true, throttled: 'cooldown' })
    }
  } catch (err) {
    console.warn('[refresh] cooldown lookup failed:', err)
    // fail-open: better a duplicate run than a permanently blocked refresh
  }
```

Also remove the now-unused `import { cookies } from 'next/headers'` (line 2) if `cookies` is referenced nowhere else in the file.

- [ ] **Step 3: Type-check**

Run: `cd forkeur-app && npx tsc --noEmit`
Expected: no errors. (If `cookies` import removal left an unused-var lint error elsewhere, fix inline.)

- [ ] **Step 4: Commit**

```bash
git add forkeur-app/app/sitemap.ts forkeur-app/app/api/refresh/route.ts
git commit -m "feat(app): route sitemap + refresh cooldown through backend"
```

### Task 15: Delete Supabase client code + deps

**Files:**
- Delete: `forkeur-app/utils/supabase/server.ts`, `client.ts`, `middleware.ts`
- Modify: `forkeur-app/package.json`
- Modify: `forkeur-app/CLAUDE.md` (remove the `utils/supabase/` block from the structure diagram)

- [ ] **Step 1: Confirm nothing imports the supabase utils anymore**

Run: `cd forkeur-app && grep -rn "utils/supabase\|@supabase" app/ lib/ components/ utils/ --include="*.ts" --include="*.tsx" | grep -v "utils/supabase/"`
Expected: **no output**. (Only the three files in `utils/supabase/` reference `@supabase/ssr`, and they're about to be deleted.)

- [ ] **Step 2: Delete the files**

```bash
git rm forkeur-app/utils/supabase/server.ts forkeur-app/utils/supabase/client.ts forkeur-app/utils/supabase/middleware.ts
```

- [ ] **Step 3: Remove the deps**

```bash
cd forkeur-app && npm uninstall @supabase/ssr @supabase/supabase-js
```

- [ ] **Step 4: Update `forkeur-app/CLAUDE.md`**

In the structure diagram, delete the `└── utils/supabase/` block (the three `server.ts`/`client.ts`/`middleware.ts` lines).

- [ ] **Step 5: Verify build + full test suite**

Run: `cd forkeur-app && npx tsc --noEmit && npm run build && npm test`
Expected: build succeeds, all tests PASS. A failing build here almost always means a stray `@supabase` import — grep and remove it.

- [ ] **Step 6: Commit**

```bash
git add forkeur-app/package.json forkeur-app/package-lock.json forkeur-app/CLAUDE.md
git commit -m "chore(app): delete Supabase client code and dependencies"
```

---

## Phase D — Cutover

> No code changes — deployment sequence + verification. Supabase stays live until Step 6.

### Task 16: Deploy backend, point at local Postgres

**Files:** server `/opt/forkeur/backend/.env`

- [ ] **Step 1: Set `DATABASE_URL` in the server backend env**

```bash
ssh -i ~/.ssh/id_ed25519_forkeur root@178.104.57.72
cd /opt/forkeur/backend
# Edit .env: add DATABASE_URL through PgBouncer (port 5432), remove SUPABASE_*
# DATABASE_URL=postgresql://forkeur_app:CHANGE_ME@127.0.0.1:5432/forkeur
nano .env
```

- [ ] **Step 2: Pull + sync deps + restart**

```bash
cd /opt/forkeur && git pull
cd backend && /root/.local/bin/uv sync
systemctl restart forkeur-backend
```

- [ ] **Step 3: Verify the backend came up against Postgres**

Run: `journalctl -u forkeur-backend -n 30 --no-pager`
Expected: no `Missing required environment variables` and no psycopg connection errors. The startup `orphan_stale_runs` line (if any) confirms a successful DB round-trip.

Run: `curl -s http://localhost:8000/api/public/restaurants | head -c 100`
Expected: `[]` (empty array — schema is live but scrapers haven't run yet) or a JSON array.

### Task 17: Populate via scrapers

- [ ] **Step 1: Trigger a small UberEats run to validate writes end-to-end**

Get an admin token (`POST /api/auth/login` with `ADMIN_PASSWORD`), then trigger with `test_mode: true` (caps at 10 items per the `max_items=10` testing convention):

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H 'Content-Type: application/json' -d '{"password":"<ADMIN_PASSWORD>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -X POST http://localhost:8000/api/scrapers/ubereats/run -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"test_mode": true}'
```

- [ ] **Step 2: Verify rows landed**

Run: `sudo -u postgres psql -p 5433 -d forkeur -tAc "select count(*) from restaurants;"`
Expected: `> 0`. Also check `platform_listings` and `menu_items` counts are non-zero.

- [ ] **Step 3: Trigger full runs from the admin dashboard**

Per the project convention, full runs are triggered from the admin dashboard (not CLI). Trigger ubereats, deliveroo, takeaway, direct, then the menu + match jobs. Monitor `journalctl -u forkeur-backend -f` and `free -m` for OOM (swap is the safety net from Task 4).

### Task 18: Deploy frontend, smoke test, decommission

- [ ] **Step 1: Set `BACKEND_URL` in the frontend env + remove Supabase vars**

On the server, in the Next.js env (`/opt/forkeur/forkeur-app/.env.local` or the systemd env for `forkeur-frontend`): ensure `BACKEND_URL=http://localhost:8000` is set; remove `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.

- [ ] **Step 2: Pull, rebuild, restart frontend**

```bash
cd /opt/forkeur/forkeur-app && npm install && npm run build
systemctl restart forkeur-frontend
```

- [ ] **Step 3: Smoke test every read path**

Verify each returns 200 + real content:
- Homepage `https://forkeur.be/` — restaurant list renders
- A restaurant detail `https://forkeur.be/restaurant/<id>` — listings + menu prices render
- Deals `https://forkeur.be/deals` — deals render
- Sitemap `https://forkeur.be/sitemap.xml` — restaurant URLs present
- Owner claim form submit (`/api/claims`) — succeeds (writes via backend)
- Stale-refresh trigger (`/api/refresh`) — returns `{ok:true}` and fires a fees run

- [ ] **Step 4: Remove the local `.env.local` Supabase vars + commit**

In the repo (local), edit `forkeur-app/.env.local` to drop the two `NEXT_PUBLIC_SUPABASE_*` lines. (This file is typically gitignored — if so, just edit it locally and on the server; no commit. If tracked, commit the removal.)

- [ ] **Step 5: Decommission Supabase**

After 24h of stable operation: in the Supabase dashboard, pause/cancel the project. Remove any remaining `SUPABASE_*` references from `backend/.env.example` and commit that cleanup.

```bash
git add backend/.env.example
git commit -m "chore: remove Supabase env references after self-hosted cutover"
```

**Rollback (any time before Step 5):** revert the backend deploy (`git checkout <pre-migration-sha> && systemctl restart forkeur-backend`) and restore the frontend `NEXT_PUBLIC_SUPABASE_*` vars + redeploy. Supabase data is stale-but-intact (nothing wrote to it after Task 16), and the old Supabase-client code is in git history.

---

## Self-review notes

- **Spec coverage:** Infra (Tasks 1–4), backend db.py rewrite (Tasks 5–10), public router (Task 11), frontend (Tasks 12–15), migration sequence (Tasks 16–18), monitoring (Task 1 slow-query log + Task 4 swap/backups). All five spec sections covered.
- **Driver deviation** from spec (asyncpg → psycopg3) documented at top + in spec's "Plan-time corrections."
- **Type consistency:** `pgpool.fetchall/fetchone/execute` signatures are used identically across Tasks 7–11. `_build_insert`/`_build_update`/`_coerce` defined in Task 6, used in 7–10. `backendFetch<T>` defined in Task 12, used in 13–14. Public endpoint JSON shapes (Task 10/11) match the `Raw*` TS types consumed in Task 13.
- **No placeholders:** every code step shows complete code; every verification step shows the exact command + expected output.
