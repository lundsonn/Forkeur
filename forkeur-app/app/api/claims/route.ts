import { NextRequest, NextResponse } from 'next/server'
import { checkSameOrigin } from '@/lib/same-origin'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'

export async function POST(req: NextRequest) {
  // Same-origin gate: only OwnerContactForm on the public site should call this.
  const reason = checkSameOrigin(req)
  if (reason) return NextResponse.json({ error: 'forbidden' }, { status: 403 })

  try {
    const raw = await req.json()

    const inquiry_type = typeof raw?.inquiry_type === 'string' ? raw.inquiry_type.trim() : 'add_url'
    const owner_email = typeof raw?.owner_email === 'string' ? raw.owner_email.trim() : null
    const restaurant_id = typeof raw?.restaurant_id === 'string' ? raw.restaurant_id.trim() : null
    const direct_order_url = typeof raw?.direct_order_url === 'string' ? raw.direct_order_url.trim() : null
    const restaurant_name_free = typeof raw?.restaurant_name_free === 'string' ? raw.restaurant_name_free.trim() : null
    const altcha_payload = typeof raw?.altcha_payload === 'string' ? raw.altcha_payload : null

    if (!owner_email) {
      return NextResponse.json({ error: 'Missing required fields' }, { status: 400 })
    }

    // RFC-5322-lite — backend re-validates with Pydantic EmailStr; cheap shape gate.
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(owner_email) || owner_email.length > 254) {
      return NextResponse.json({ error: 'Invalid email' }, { status: 400 })
    }
    if (direct_order_url) {
      try {
        const u = new URL(direct_order_url)
        if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new Error('scheme')
      } catch {
        return NextResponse.json({ error: 'Invalid URL' }, { status: 400 })
      }
    }
    const validTypes = new Set(['add_url', 'new_listing', 'remove'])
    if (!validTypes.has(inquiry_type)) {
      return NextResponse.json({ error: 'Invalid inquiry_type' }, { status: 400 })
    }

    // Altcha PoW verification is done by the FastAPI backend (has the HMAC key).
    const res = await fetch(`${BACKEND}/api/claims`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inquiry_type, owner_email, restaurant_id, direct_order_url, restaurant_name_free, altcha_payload }),
    })

    const text = await res.text()
    let data: unknown
    try { data = JSON.parse(text) } catch { data = { error: text } }
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    console.error('[claims proxy]', err)
    return NextResponse.json({ error: 'Internal error' }, { status: 500 })
  }
}
