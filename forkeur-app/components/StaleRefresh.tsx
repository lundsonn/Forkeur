'use client'
import { useEffect } from 'react'

const STALE_HOURS = 24
const LS_KEY = 'forkeur_refresh_last'
const COOLDOWN_MS = 60 * 60 * 1000 // 1h between auto-triggers

export default function StaleRefresh({ lastScrapedAt }: { lastScrapedAt: string | null }) {
  useEffect(() => {
    if (!lastScrapedAt) return
    const ageH = (Date.now() - new Date(lastScrapedAt).getTime()) / 3_600_000
    if (ageH < STALE_HOURS) return

    // Client-side rate limit: don't hammer the scraper on every page load
    const lastRefresh = Number(localStorage.getItem(LS_KEY) ?? '0')
    if (Date.now() - lastRefresh < COOLDOWN_MS) return

    localStorage.setItem(LS_KEY, String(Date.now()))
    fetch('/api/refresh', { method: 'POST' }).catch((err) => {
      // Telemetry-only: don't surface to the user, but don't pretend it didn't
      // happen either. Server-side same-origin + cooldown enforce the gate now.
      console.warn('[StaleRefresh] trigger failed:', err)
    })
  }, [lastScrapedAt])

  return null
}
