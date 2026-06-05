import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'
const JWT_SECRET = process.env.BACKEND_ADMIN_TOKEN ?? ''
// SITE_ORIGIN is the public URL this app is served from. Used to gate the
// refresh trigger to genuine same-origin browser requests.
const SITE_ORIGIN = process.env.SITE_ORIGIN ?? ''

// In-memory throttle so a single tab can't hammer the backend even if it
// bypasses the localStorage cooldown on the client.
const COOLDOWN_MS = 60 * 60 * 1000
let lastFire = 0

// Fire-and-forget: trigger a fees scrape when a restaurant page is stale.
// Auth model: rely on same-origin enforcement (Origin/Referer header) +
// server-side cooldown. No client-side secret — anything `NEXT_PUBLIC_*` ends
// up in the browser bundle and provides no security.
export async function POST(req: NextRequest) {
  if (!JWT_SECRET) return NextResponse.json({ ok: false }, { status: 503 })

  if (SITE_ORIGIN) {
    const origin = req.headers.get('origin') ?? ''
    const referer = req.headers.get('referer') ?? ''
    const ok =
      origin === SITE_ORIGIN ||
      (referer && new URL(referer).origin === SITE_ORIGIN)
    if (!ok) return NextResponse.json({ ok: false }, { status: 403 })
  }

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
