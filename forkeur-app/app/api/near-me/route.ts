import { NextRequest, NextResponse } from 'next/server'
import { getNearMe } from '@/lib/queries'

export const revalidate = 0

export async function GET(req: NextRequest) {
  const commune = req.nextUrl.searchParams.get('commune') ?? 'bruxelles'
  try {
    const restaurants = await getNearMe(commune)
    return NextResponse.json(restaurants)
  } catch (e) {
    console.error('[near-me proxy]', e)
    return NextResponse.json([], { status: 500 })
  }
}
