import { NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'
const JWT_SECRET = process.env.BACKEND_ADMIN_TOKEN ?? ''

// Fire-and-forget: trigger a fees scrape when a restaurant page is stale.
// Uses a pre-issued long-lived token from BACKEND_ADMIN_TOKEN env var.
// Rate-limited on the backend side (won't re-run if already running).
export async function POST() {
  if (!JWT_SECRET) return NextResponse.json({ ok: false }, { status: 503 })

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
