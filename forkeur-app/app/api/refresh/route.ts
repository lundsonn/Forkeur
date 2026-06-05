import { NextRequest, NextResponse } from 'next/server'
import { cookies } from 'next/headers'
import { checkSameOrigin } from '@/lib/same-origin'
import { createClient } from '@/utils/supabase/server'

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

  // DB-backed cooldown — anyone with the supabase URL/anon key can read
  // scraper_runs (it has a public SELECT policy), so we don't need the
  // service-role key here.
  try {
    const supabase = createClient(await cookies())
    const cutoff = new Date(now - COOLDOWN_MS).toISOString()
    const { data, error } = await supabase
      .from('scraper_runs')
      .select('started_at')
      .eq('platform', 'fees')
      .gte('started_at', cutoff)
      .limit(1)
    if (error) {
      console.warn('[refresh] cooldown lookup failed:', error.message)
      // fail-open on infrastructure failure: better to allow a duplicate
      // run than to permanently block refreshes when supabase is down
    } else if (data && data.length > 0) {
      return NextResponse.json({ ok: true, throttled: 'cooldown' })
    }
  } catch (err) {
    console.warn('[refresh] supabase client init failed:', err)
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
