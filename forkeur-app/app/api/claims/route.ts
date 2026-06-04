import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'

export async function POST(req: NextRequest) {
  try {
    const raw = await req.json()

    const inquiry_type = typeof raw?.inquiry_type === 'string' ? raw.inquiry_type.trim() : 'add_url'
    const owner_email = typeof raw?.owner_email === 'string' ? raw.owner_email.trim() : null
    const restaurant_id = typeof raw?.restaurant_id === 'string' ? raw.restaurant_id.trim() : null
    const direct_order_url = typeof raw?.direct_order_url === 'string' ? raw.direct_order_url.trim() : null
    const restaurant_name_free = typeof raw?.restaurant_name_free === 'string' ? raw.restaurant_name_free.trim() : null

    if (!owner_email) {
      return NextResponse.json({ error: 'Missing required fields' }, { status: 400 })
    }

    const res = await fetch(`${BACKEND}/api/claims`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inquiry_type, owner_email, restaurant_id, direct_order_url, restaurant_name_free }),
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
