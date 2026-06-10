import { NextRequest, NextResponse } from 'next/server'
import { checkSameOrigin } from '@/lib/same-origin'
import { backendFetch } from '@/lib/backend'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'
const JWT_SECRET = process.env.BACKEND_ADMIN_TOKEN ?? ''

// Cross-instance throttle: a fees run that started within this window means
// either it's still running OR it just finished — either way, don't fire
// another one. Backed by scraper_runs so horizontal scaling can't multiply
// the rate (the previous per-process `lastFire` did exactly that).
const COOLDOWN_MS = 60 * 60 * 1000

// Belt-and-suspenders local throttle: protects the DB from being asked the
// cooldown question hundreds of times a second from the same instance.
const LOCAL_DEBOUNCE_MS = 5_000
let lastLocalFire = 0

export async function POST(req: NextRequest) {
  if (!JWT_SECRET) return NextResponse.json({ ok: false }, { status: 503 })

  const reason = checkSameOrigin(req)
  if (reason) return NextResponse.json({ ok: false }, { status: 403 })

  const now = Date.now()
  if (now - lastLocalFire < LOCAL_DEBOUNCE_MS) {
    return NextResponse.json({ ok: true, throttled: 'local' })
  }

  try {
    const cutoff = new Date(now - COOLDOWN_MS).toISOString()
    const run = await backendFetch(
      `/api/public/scraper-runs/latest?platform=fees&since=${encodeURIComponent(cutoff)}`
    )
    if (run) {
      return NextResponse.json({ ok: true, throttled: 'cooldown' })
    }
  } catch (err) {
    console.warn('[refresh] cooldown lookup failed:', err)
    // fail-open: allow refresh on infrastructure failure
  }

  lastLocalFire = now

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
