# Restaurant Claims Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let restaurant owners submit their email + direct order URL via the consumer app; the claim lands in `restaurant_claims` as `verified=false` until an admin approves it, which then updates `restaurants.order_url` and upserts the direct `platform_listing`.

**Architecture:** Consumer-facing claim form (client component, no auth) → `POST /api/claims` (public endpoint, no JWT) → inserts into `restaurant_claims`. Admin dashboard page (authenticated) lists pending claims → `POST /api/claims/:id/approve` → writes `restaurants.order_url` + upserts `platform_listings` direct row. The `restaurant_claims` table already exists with the right schema.

**Tech Stack:** Next.js 15 App Router, FastAPI, Supabase Python client, React+Vite admin dashboard, Tailwind CSS (stone/orange theme), pytest (backend), vitest (frontend).

---

## File map

### New files
- `backend/routers/claims.py` — `POST /api/claims`, `GET /api/claims`, `POST /api/claims/{id}/approve`, `POST /api/claims/{id}/reject`
- `backend/tests/test_claims_router.py` — router unit tests
- `backend/dashboard/src/pages/Claims.tsx` — admin claims list page
- `forkeur-app/components/ClaimForm.tsx` — owner claim modal (client component)

### Modified files
- `backend/main.py` — include claims router, add `/api/claims` to public paths
- `backend/routers/data.py` — add `get_claims` + `approve_claim` DB calls (or do inline in router)
- `backend/db.py` — add `insert_claim`, `get_claims`, `approve_claim` helpers
- `backend/dashboard/src/api.ts` — add `getClaims`, `approveClaim`, `rejectClaim`
- `backend/dashboard/src/App.tsx` — add `/claims` route
- `backend/dashboard/src/components/Sidebar.tsx` — add "Claims" nav link
- `forkeur-app/app/restaurant/[id]/page.tsx` — render `<ClaimForm>` below basket

---

## Task 1: DB helpers — insert_claim + get_claims + approve_claim

**Files:**
- Modify: `backend/db.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_claims_db.py
import pytest
from unittest.mock import MagicMock, patch, call


def _make_client(insert_data=None, select_data=None, update_data=None):
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = insert_data or []
    client.table.return_value.select.return_value.order.return_value.execute.return_value.data = select_data or []
    client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = update_data or []
    return client


def test_insert_claim_returns_id():
    with patch("db.get_client") as mock_get:
        mock_get.return_value = _make_client(insert_data=[{"id": "claim-abc"}])
        import db
        result = db.insert_claim(
            restaurant_id="rest-1",
            owner_email="owner@example.com",
            direct_order_url="https://myrest.com/order",
        )
    assert result == "claim-abc"


def test_get_claims_pending_only():
    rows = [
        {"id": "c1", "restaurant_id": "r1", "owner_email": "a@b.com",
         "direct_order_url": "https://x.com", "verified": False, "claimed_at": "2026-06-03T10:00:00Z"},
    ]
    with patch("db.get_client") as mock_get:
        client = MagicMock()
        client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = rows
        mock_get.return_value = client
        import db
        result = db.get_claims(verified=False)
    assert len(result) == 1
    assert result[0]["id"] == "c1"


def test_approve_claim_updates_restaurant_and_listing():
    claim = {
        "id": "c1", "restaurant_id": "rest-1",
        "direct_order_url": "https://myrest.com/order", "verified": False,
    }
    with patch("db.get_client") as mock_get, \
         patch("db.upsert_listing") as mock_upsert:
        client = MagicMock()
        # get_claim fetch
        client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [claim]
        mock_get.return_value = client
        import db
        db.approve_claim("c1")

        # restaurants.order_url updated
        client.table.return_value.update.assert_any_call({"order_url": "https://myrest.com/order"})
        # claim marked verified
        client.table.return_value.update.assert_any_call({"verified": True})
        # direct listing upserted
        mock_upsert.assert_called_once_with({
            "restaurant_id": "rest-1",
            "platform": "direct",
            "url": "https://myrest.com/order",
            "is_available": True,
        })
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_claims_db.py -v
```
Expected: FAIL — `db` has no `insert_claim`, `get_claims`, `approve_claim`.

- [ ] **Step 3: Add DB helpers to `backend/db.py`**

Add at end of file:

```python
def insert_claim(restaurant_id: str, owner_email: str, direct_order_url: str) -> str:
    """Insert a restaurant claim (verified=False). Returns claim id."""
    client = get_client()
    res = client.table("restaurant_claims").insert({
        "restaurant_id": restaurant_id,
        "owner_email": owner_email,
        "direct_order_url": direct_order_url,
        "verified": False,
    }).execute()
    return res.data[0]["id"]


def get_claims(verified: bool | None = None) -> list[dict]:
    """Return claims, optionally filtered by verified status."""
    client = get_client()
    q = client.table("restaurant_claims").select(
        "id, restaurant_id, owner_email, direct_order_url, verified, claimed_at, "
        "restaurants(name)"
    )
    if verified is not None:
        q = q.eq("verified", verified)
    return q.order("claimed_at", desc=True).execute().data


def approve_claim(claim_id: str) -> None:
    """Approve a claim: set verified=True, update restaurants.order_url, upsert direct listing."""
    client = get_client()
    claim = client.table("restaurant_claims").select(
        "id, restaurant_id, direct_order_url"
    ).eq("id", claim_id).execute().data[0]

    client.table("restaurants").update(
        {"order_url": claim["direct_order_url"]}
    ).eq("id", claim["restaurant_id"]).execute()

    client.table("restaurant_claims").update(
        {"verified": True}
    ).eq("id", claim_id).execute()

    upsert_listing({
        "restaurant_id": claim["restaurant_id"],
        "platform": "direct",
        "url": claim["direct_order_url"],
        "is_available": True,
    })


def reject_claim(claim_id: str) -> None:
    """Delete a claim (rejected — not approved)."""
    get_client().table("restaurant_claims").delete().eq("id", claim_id).execute()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_claims_db.py -v
```
Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/db.py backend/tests/test_claims_db.py
git commit -m "feat: add insert_claim, get_claims, approve_claim, reject_claim DB helpers"
```

---

## Task 2: Backend API router — claims endpoints

**Files:**
- Create: `backend/routers/claims.py`
- Create: `backend/tests/test_claims_router.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing router tests**

```python
# backend/tests/test_claims_router.py
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from routers import claims as claims_router


def _make_app():
    app = FastAPI()
    app.include_router(claims_router.router, prefix="/api")
    return app


def test_post_claim_returns_201():
    with patch("routers.claims.db") as mock_db:
        mock_db.insert_claim.return_value = "claim-xyz"
        client = TestClient(_make_app())
        res = client.post("/api/claims", json={
            "restaurant_id": "rest-1",
            "owner_email": "owner@example.com",
            "direct_order_url": "https://myrest.com/order",
        })
    assert res.status_code == 201
    assert res.json()["claim_id"] == "claim-xyz"


def test_post_claim_rejects_invalid_email():
    client = TestClient(_make_app())
    res = client.post("/api/claims", json={
        "restaurant_id": "rest-1",
        "owner_email": "not-an-email",
        "direct_order_url": "https://myrest.com/order",
    })
    assert res.status_code == 422


def test_post_claim_rejects_invalid_url():
    client = TestClient(_make_app())
    res = client.post("/api/claims", json={
        "restaurant_id": "rest-1",
        "owner_email": "owner@example.com",
        "direct_order_url": "not-a-url",
    })
    assert res.status_code == 422


def test_get_claims_returns_list():
    with patch("routers.claims.db") as mock_db:
        mock_db.get_claims.return_value = [
            {"id": "c1", "owner_email": "a@b.com", "verified": False}
        ]
        client = TestClient(_make_app())
        res = client.get("/api/claims")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_approve_claim_returns_200():
    with patch("routers.claims.db") as mock_db:
        mock_db.approve_claim.return_value = None
        client = TestClient(_make_app())
        res = client.post("/api/claims/c1/approve")
    assert res.status_code == 200
    mock_db.approve_claim.assert_called_once_with("c1")


def test_reject_claim_returns_200():
    with patch("routers.claims.db") as mock_db:
        mock_db.reject_claim.return_value = None
        client = TestClient(_make_app())
        res = client.post("/api/claims/c1/reject")
    assert res.status_code == 200
    mock_db.reject_claim.assert_called_once_with("c1")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_claims_router.py -v
```
Expected: ImportError — `routers/claims.py` doesn't exist.

- [ ] **Step 3: Create `backend/routers/claims.py`**

```python
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, HttpUrl
import db

router = APIRouter(prefix="/claims", tags=["claims"])


class ClaimIn(BaseModel):
    restaurant_id: str
    owner_email: EmailStr
    direct_order_url: HttpUrl


@router.post("", status_code=201)
async def submit_claim(body: ClaimIn):
    claim_id = db.insert_claim(
        restaurant_id=body.restaurant_id,
        owner_email=body.owner_email,
        direct_order_url=str(body.direct_order_url),
    )
    return {"claim_id": claim_id}


@router.get("")
async def list_claims(verified: bool | None = None):
    return db.get_claims(verified=verified)


@router.post("/{claim_id}/approve")
async def approve_claim(claim_id: str):
    try:
        db.approve_claim(claim_id)
    except (IndexError, KeyError):
        raise HTTPException(404, "Claim not found")
    return {"status": "approved"}


@router.post("/{claim_id}/reject")
async def reject_claim(claim_id: str):
    db.reject_claim(claim_id)
    return {"status": "rejected"}
```

- [ ] **Step 4: Wire router into `backend/main.py`**

Add import and include. The `/api/claims` POST must be public (no JWT), while GET/approve/reject stay protected.

In `main.py`, add to imports:
```python
from routers import scrapers, runs, schedule, data, websites, claims as claims_router_mod
```

Add to `_PUBLIC_PATHS`:
```python
_PUBLIC_PATHS = {"/api/auth/login", "/api/claims"}
```

Add after the other `include_router` lines:
```python
app.include_router(claims_router_mod.router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_claims_router.py -v
```
Expected: all 6 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/claims.py backend/tests/test_claims_router.py backend/main.py
git commit -m "feat: add /api/claims router (submit, list, approve, reject)"
```

---

## Task 3: Admin dashboard — Claims page

**Files:**
- Create: `backend/dashboard/src/pages/Claims.tsx`
- Modify: `backend/dashboard/src/api.ts`
- Modify: `backend/dashboard/src/App.tsx`
- Modify: `backend/dashboard/src/components/Sidebar.tsx`

- [ ] **Step 1: Add API helpers to `backend/dashboard/src/api.ts`**

Append to end of file:

```typescript
export interface Claim {
  id: string
  restaurant_id: string
  owner_email: string
  direct_order_url: string
  verified: boolean
  claimed_at: string
  restaurants?: { name: string } | null
}

export async function getClaims(verified?: boolean): Promise<Claim[]> {
  const qs = verified !== undefined ? `?verified=${verified}` : ''
  const res = await apiFetch(`${BASE}/claims${qs}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function approveClaim(id: string): Promise<void> {
  const res = await apiFetch(`${BASE}/claims/${id}/approve`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export async function rejectClaim(id: string): Promise<void> {
  const res = await apiFetch(`${BASE}/claims/${id}/reject`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}
```

- [ ] **Step 2: Create `backend/dashboard/src/pages/Claims.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { getClaims, approveClaim, rejectClaim, type Claim } from '../api'

export default function Claims() {
  const [claims, setClaims] = useState<Claim[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [acting, setActing] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await getClaims(false) // pending only
      setClaims(data)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function handleApprove(id: string) {
    setActing(id)
    try {
      await approveClaim(id)
      setClaims((prev) => prev.filter((c) => c.id !== id))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setActing(null)
    }
  }

  async function handleReject(id: string) {
    setActing(id)
    try {
      await rejectClaim(id)
      setClaims((prev) => prev.filter((c) => c.id !== id))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setActing(null)
    }
  }

  return (
    <div>
      <h1 className="text-xl font-bold text-stone-900 mb-6">Claims</h1>
      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}
      {loading ? (
        <p className="text-stone-400 text-sm">Loading…</p>
      ) : claims.length === 0 ? (
        <p className="text-stone-400 text-sm">No pending claims.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {claims.map((claim) => (
            <div key={claim.id} className="border border-stone-200 rounded-xl p-4">
              <p className="font-semibold text-stone-900 text-sm">
                {claim.restaurants?.name ?? claim.restaurant_id}
              </p>
              <p className="text-xs text-stone-500 mt-0.5">{claim.owner_email}</p>
              <a
                href={claim.direct_order_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-orange-600 hover:underline mt-1 block truncate"
              >
                {claim.direct_order_url}
              </a>
              <p className="text-xs text-stone-400 mt-1">
                {new Date(claim.claimed_at).toLocaleString('fr-BE')}
              </p>
              <div className="flex gap-2 mt-3">
                <button
                  disabled={acting === claim.id}
                  onClick={() => handleApprove(claim.id)}
                  className="px-3 py-1.5 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-xs font-semibold disabled:opacity-50 transition-colors"
                >
                  Approve
                </button>
                <button
                  disabled={acting === claim.id}
                  onClick={() => handleReject(claim.id)}
                  className="px-3 py-1.5 rounded-lg bg-stone-100 hover:bg-stone-200 text-stone-700 text-xs font-semibold disabled:opacity-50 transition-colors"
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Add route to `backend/dashboard/src/App.tsx`**

Add import:
```tsx
import Claims from './pages/Claims'
```

Add inside `<Routes>`:
```tsx
<Route path="/claims" element={<Claims />} />
```

- [ ] **Step 4: Add nav link to `backend/dashboard/src/components/Sidebar.tsx`**

Change the `links` array to:
```tsx
const links = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/scrapers', label: 'Scrapers' },
  { to: '/history', label: 'History' },
  { to: '/schedule', label: 'Schedule' },
  { to: '/data', label: 'Data' },
  { to: '/claims', label: 'Claims' },
]
```

- [ ] **Step 5: Build dashboard and verify no TypeScript errors**

```bash
cd backend/dashboard && npm run build 2>&1 | tail -20
```
Expected: no errors, outputs `dist/`.

- [ ] **Step 6: Commit**

```bash
git add backend/dashboard/src/pages/Claims.tsx backend/dashboard/src/api.ts backend/dashboard/src/App.tsx backend/dashboard/src/components/Sidebar.tsx
git commit -m "feat: add Claims page to admin dashboard (list, approve, reject)"
```

---

## Task 4: Consumer app — ClaimForm component

**Files:**
- Create: `forkeur-app/components/ClaimForm.tsx`
- Modify: `forkeur-app/app/restaurant/[id]/page.tsx`

- [ ] **Step 1: Write vitest tests for ClaimForm**

```typescript
// forkeur-app/__tests__/claim-form.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ClaimForm from '@/components/ClaimForm'

describe('ClaimForm', () => {
  beforeEach(() => {
    global.fetch = vi.fn()
  })

  it('renders trigger button', () => {
    render(<ClaimForm restaurantId="rest-1" restaurantName="Pizza Roma" />)
    expect(screen.getByText(/vous êtes le propriétaire/i)).toBeInTheDocument()
  })

  it('shows form on button click', () => {
    render(<ClaimForm restaurantId="rest-1" restaurantName="Pizza Roma" />)
    fireEvent.click(screen.getByText(/vous êtes le propriétaire/i))
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/url/i)).toBeInTheDocument()
  })

  it('submits form and shows success', async () => {
    ;(global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ claim_id: 'c1' }),
    })
    render(<ClaimForm restaurantId="rest-1" restaurantName="Pizza Roma" />)
    fireEvent.click(screen.getByText(/vous êtes le propriétaire/i))
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'owner@example.com' } })
    fireEvent.change(screen.getByLabelText(/url/i), { target: { value: 'https://myrest.com/order' } })
    fireEvent.click(screen.getByRole('button', { name: /envoyer/i }))
    await waitFor(() => expect(screen.getByText(/demande envoyée/i)).toBeInTheDocument())
  })

  it('shows error on failed submit', async () => {
    ;(global.fetch as any).mockResolvedValueOnce({
      ok: false,
      text: async () => 'Server error',
    })
    render(<ClaimForm restaurantId="rest-1" restaurantName="Pizza Roma" />)
    fireEvent.click(screen.getByText(/vous êtes le propriétaire/i))
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'owner@example.com' } })
    fireEvent.change(screen.getByLabelText(/url/i), { target: { value: 'https://myrest.com/order' } })
    fireEvent.click(screen.getByRole('button', { name: /envoyer/i }))
    await waitFor(() => expect(screen.getByText(/erreur/i)).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd forkeur-app && npx vitest run __tests__/claim-form.test.tsx 2>&1 | tail -10
```
Expected: FAIL — `ClaimForm` not found.

- [ ] **Step 3: Create `forkeur-app/components/ClaimForm.tsx`**

```tsx
'use client'
import { useState } from 'react'

type Props = {
  restaurantId: string
  restaurantName: string
}

export default function ClaimForm({ restaurantId, restaurantName }: Props) {
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [url, setUrl] = useState('')
  const [state, setState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setState('loading')
    try {
      const res = await fetch('/api/claims', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          restaurant_id: restaurantId,
          owner_email: email,
          direct_order_url: url,
        }),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(text)
      }
      setState('success')
    } catch (err: any) {
      setErrorMsg(err.message ?? 'Erreur inconnue')
      setState('error')
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-xs text-stone-400 hover:text-stone-600 underline underline-offset-2 transition-colors"
      >
        Vous êtes le propriétaire de ce restaurant ?
      </button>
    )
  }

  if (state === 'success') {
    return (
      <p className="text-xs text-stone-500 py-2">
        Demande envoyée — nous vérifierons et mettrons à jour votre fiche sous peu.
      </p>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 border border-stone-200 rounded-xl p-4 flex flex-col gap-3">
      <p className="text-sm font-semibold text-stone-900">Revendiquer {restaurantName}</p>
      <p className="text-xs text-stone-500">
        Indiquez votre email et votre lien de commande directe. Nous vérifierons avant publication.
      </p>

      <div className="flex flex-col gap-1">
        <label htmlFor="claim-email" className="text-xs font-medium text-stone-700">Email</label>
        <input
          id="claim-email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="vous@votrerestaurant.com"
          className="border border-stone-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="claim-url" className="text-xs font-medium text-stone-700">URL de commande</label>
        <input
          id="claim-url"
          type="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://votrerestaurant.com/commander"
          className="border border-stone-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-400"
        />
      </div>

      {state === 'error' && (
        <p className="text-xs text-red-600">Erreur : {errorMsg}</p>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={state === 'loading'}
          className="px-4 py-2 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-sm font-semibold disabled:opacity-50 transition-colors"
        >
          {state === 'loading' ? 'Envoi…' : 'Envoyer'}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="px-4 py-2 rounded-lg bg-stone-100 hover:bg-stone-200 text-stone-700 text-sm font-semibold transition-colors"
        >
          Annuler
        </button>
      </div>
    </form>
  )
}
```

- [ ] **Step 4: The fetch in `ClaimForm` hits `/api/claims` — this needs to be proxied from Next.js to the backend**

Add a Next.js route handler to proxy the claim submission (avoids CORS and keeps backend URL internal):

Create `forkeur-app/app/api/claims/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'

export async function POST(req: NextRequest) {
  const body = await req.json()
  const res = await fetch(`${BACKEND}/api/claims`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json()
  return NextResponse.json(data, { status: res.status })
}
```

- [ ] **Step 5: Add `ClaimForm` to restaurant detail page**

In `forkeur-app/app/restaurant/[id]/page.tsx`, add import:
```tsx
import ClaimForm from '@/components/ClaimForm'
```

Add below the `<BasketSimulator>` line, inside the `<div className="max-w-md mx-auto">`:
```tsx
<div className="px-5 pb-8">
  <ClaimForm restaurantId={data.id} restaurantName={data.name} />
</div>
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd forkeur-app && npx vitest run __tests__/claim-form.test.tsx 2>&1 | tail -10
```
Expected: all 4 PASS.

- [ ] **Step 7: Run full frontend test suite to check for regressions**

```bash
cd forkeur-app && npx vitest run 2>&1 | tail -20
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add forkeur-app/components/ClaimForm.tsx forkeur-app/app/api/claims/route.ts forkeur-app/app/restaurant/\[id\]/page.tsx
git commit -m "feat: add ClaimForm component and /api/claims proxy route"
```

---

## Task 5: End-to-end smoke test

- [ ] **Step 1: Start backend dev server**

```bash
cd backend && uv run uvicorn main:app --reload --port 8000
```

- [ ] **Step 2: Start Next.js dev server**

```bash
cd forkeur-app && npm run dev -- --port 30000
```

- [ ] **Step 3: Visit a restaurant detail page**

Open `http://localhost:30000/restaurant/<any-id>` — confirm "Vous êtes le propriétaire de ce restaurant ?" appears at bottom.

- [ ] **Step 4: Submit a test claim**

Click the link, fill in a valid email + URL, submit. Confirm "Demande envoyée" message appears.

- [ ] **Step 5: Verify claim in DB**

```bash
cd backend && uv run python -c "import db; print(db.get_claims(verified=False))"
```
Expected: list with 1 row, `verified=False`, matching the submitted email/URL.

- [ ] **Step 6: Log in to admin dashboard**

Open `http://localhost:8000/` → login → navigate to "Claims". Confirm the pending claim appears.

- [ ] **Step 7: Approve the claim**

Click "Approve". Confirm the claim disappears from the list.

- [ ] **Step 8: Verify DB state after approval**

```bash
cd backend && uv run python -c "
import db
# Check claim is verified
claims = db.get_claims()
print('All claims:', claims)
"
```

Also check the restaurant now has `order_url` set and a `direct` platform_listing row:

```sql
-- Run in Supabase MCP or psql
SELECT order_url FROM restaurants WHERE id = '<restaurant_id>';
SELECT * FROM platform_listings WHERE platform = 'direct' AND restaurant_id = '<restaurant_id>';
```

- [ ] **Step 9: Run all backend tests**

```bash
cd backend && uv run pytest -v 2>&1 | tail -20
```
Expected: all pass.

---

## Task 6: Run full test suite + final commit

- [ ] **Step 1: Run backend tests**

```bash
cd backend && uv run pytest -v
```
Expected: all pass.

- [ ] **Step 2: Run frontend tests**

```bash
cd forkeur-app && npx vitest run
```
Expected: all pass.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: restaurant claims — submit, admin review, approve writes order_url + direct listing"
```
