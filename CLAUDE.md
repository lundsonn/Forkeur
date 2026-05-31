# Forkeur — food price comparison (Brussels)

Compare restaurant prices across UberEats, Deliveroo, and Takeaway.

## Architecture

```
food-price-compare/
├── backend/          ← Python scraper manager (FastAPI + APScheduler + Playwright)
├── forkeur-app/      ← Next.js 15 consumer app (App Router + Supabase)
└── supabase/         ← DB migrations (applied to remote Supabase project)
```

**`Forkeur/`** at root is dead code — ignore it.
**Root-level `scrape-*.js` and `*.json`** are prototype artifacts — ignore them.

## Database

Supabase project: `ltpicouyzdmamblzwcgc`
Tables: `restaurants`, `platform_listings`, `menu_items`, `claims`, `scraper_runs`
MCP wired: `.mcp.json` → use Supabase MCP tools for schema/query work.

3 migrations applied: `supabase/migrations/`

## Running

```bash
# Install everything
make install

# Dev: FastAPI on :8000, Vite dashboard on :5173
make dev

# Next.js app
cd forkeur-app && npm run dev   # :3000
```

## Key conventions

- Backend: Python 3.12+, `uv` for packages (`uv run <cmd>`, never activate venv manually)
- Frontend: Next.js 15 App Router — Server Components by default, `'use client'` only when needed
- Supabase client: `utils/supabase/server.ts` in Server Components, `utils/supabase/client.ts` in Client Components
- Tests: `pytest` (backend), `vitest` (frontend)
