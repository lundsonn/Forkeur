import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const UUID_RE = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i
const BACKEND_URL = process.env.BACKEND_URL ?? 'http://localhost:8000'

const GONE_HTML = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Page removed</title><meta http-equiv="refresh" content="0;url=/"></head><body></body></html>`

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const match = pathname.match(/^\/restaurant\/([^/]+)$/)
  if (!match || !UUID_RE.test(match[1])) return NextResponse.next()

  try {
    const res = await fetch(`${BACKEND_URL}/api/public/restaurants/${match[1]}`, {
      next: { revalidate: 3600 },
    })
    if (res.status === 404) {
      return new NextResponse(GONE_HTML, {
        status: 410,
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      })
    }
  } catch {
    // backend unreachable — let page handle it normally
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/restaurant/:id'],
}
