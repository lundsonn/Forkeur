import { NextRequest, NextResponse } from 'next/server'

const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'
const RECAPTCHA_SECRET = process.env.RECAPTCHA_SECRET_KEY ?? ''

async function verifyRecaptcha(token: string): Promise<boolean> {
  if (!RECAPTCHA_SECRET) return true // disabled if not configured
  try {
    const res = await fetch('https://www.google.com/recaptcha/api/siteverify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: `secret=${RECAPTCHA_SECRET}&response=${token}`,
    })
    const data = await res.json() as { success: boolean; score?: number }
    return data.success && (data.score ?? 1) >= 0.5
  } catch {
    return false
  }
}

export async function POST(req: NextRequest) {
  try {
    const raw = await req.json()

    const inquiry_type = typeof raw?.inquiry_type === 'string' ? raw.inquiry_type.trim() : 'add_url'
    const owner_email = typeof raw?.owner_email === 'string' ? raw.owner_email.trim() : null
    const restaurant_id = typeof raw?.restaurant_id === 'string' ? raw.restaurant_id.trim() : null
    const direct_order_url = typeof raw?.direct_order_url === 'string' ? raw.direct_order_url.trim() : null
    const restaurant_name_free = typeof raw?.restaurant_name_free === 'string' ? raw.restaurant_name_free.trim() : null
    const recaptcha_token = typeof raw?.recaptcha_token === 'string' ? raw.recaptcha_token : null

    if (!owner_email) {
      return NextResponse.json({ error: 'Missing required fields' }, { status: 400 })
    }

    if (RECAPTCHA_SECRET) {
      if (!recaptcha_token || !(await verifyRecaptcha(recaptcha_token))) {
        return NextResponse.json({ error: 'reCAPTCHA verification failed' }, { status: 400 })
      }
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
