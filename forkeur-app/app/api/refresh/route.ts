import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'
const JWT_SECRET = process.env.BACKEND_ADMIN_TOKEN ?? ''
// REFRESH_SECRET must be set and matched in callers (e.g. StaleRefresh component).
// Same value as NEXT_PUBLIC_REFRESH_SECRET (readable server-side without the prefix too).
const REFRESH_SECRET = process.env.NEXT_PUBLIC_REFRESH_SECRET ?? ''

// Fire-and-forget: trigger a fees scrape when a restaurant page is stale.
// Uses a pre-issued long-lived token from BACKEND_ADMIN_TOKEN env var.
// Rate-limited on the backend side (won't re-run if already running).
export async function POST(req: NextRequest) {
  if (!JWT_SECRET) return NextResponse.json({ ok: false }, { status: 503 })

  // Require the shared secret so arbitrary public callers cannot trigger scrapes.
  if (REFRESH_SECRET) {
    const provided = req.headers.get('x-refresh-secret') ?? ''
    if (provided !== REFRESH_SECRET) {
      return NextResponse.json({ ok: false }, { status: 401 })
    }
  }

  // Non-blocking — we don't await the scraper finishing
  fetch(`${BACKEND}/api/scrapers/fees/run`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${JWT_SECRET}`,
    },
    body: JSON.stringify({}),
  }).catch(() => {})

  return NextResponse.json({ ok: true })
}
