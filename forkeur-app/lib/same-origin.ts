import type { NextRequest } from 'next/server'

const SITE_ORIGIN = process.env.SITE_ORIGIN ?? ''

/**
 * Returns `null` if the request is same-origin, otherwise the reason string.
 *
 * Fail-closed: in production-like environments (NODE_ENV !== 'development')
 * an unset SITE_ORIGIN is treated as a config error and ALL requests are
 * rejected. The previous behaviour of skipping the check when the env var
 * was missing turned the gate into a no-op in misconfigured deploys.
 */
export function checkSameOrigin(req: NextRequest): string | null {
  if (!SITE_ORIGIN) {
    if (process.env.NODE_ENV === 'development') return null
    return 'SITE_ORIGIN not configured'
  }
  const origin = req.headers.get('origin') ?? ''
  if (origin === SITE_ORIGIN) return null
  const referer = req.headers.get('referer') ?? ''
  if (referer) {
    try {
      if (new URL(referer).origin === SITE_ORIGIN) return null
    } catch {
      // fall through
    }
  }
  return 'cross-origin'
}
