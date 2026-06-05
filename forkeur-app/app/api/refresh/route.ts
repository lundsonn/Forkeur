import { NextRequest, NextResponse } from 'next/server'
import { checkSameOrigin } from '@/lib/same-origin'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'
const JWT_SECRET = process.env.BACKEND_ADMIN_TOKEN ?? ''

// In-memory throttle so a single tab can't hammer the backend even if it
// bypasses the localStorage cooldown on the client. NOTE: per-process state —
// a multi-instance deploy multiplies the effective rate by instance count.
const COOLDOWN_MS = 60 * 60 * 1000
let lastFire = 0

// Fire-and-forget: trigger a fees scrape when a restaurant page is stale.
// Auth model: same-origin (Origin/Referer) + server-side cooldown.
export async function POST(req: NextRequest) {
  if (!JWT_SECRET) return NextResponse.json({ ok: false }, { status: 503 })

  const reason = checkSameOrigin(req)
  if (reason) return NextResponse.json({ ok: false }, { status: 403 })

  const now = Date.now()
  if (now - lastFire < COOLDOWN_MS) {
    return NextResponse.json({ ok: true, throttled: true })
  }
  lastFire = now

  // Non-blocking — we don't await the scraper finishing.
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
