'use client'
import { useMemo } from 'react'
import { getOpenStatus } from '@/lib/hours'
import type { OpeningHours } from '@/lib/queries'
import { useTranslations } from 'next-intl'

export default function OpenStatusBadge({
  openingHours,
  isAvailable,
}: {
  openingHours: OpeningHours | null
  isAvailable: boolean
}) {
  const t = useTranslations('hours')
  const status = useMemo(() => getOpenStatus(openingHours), [openingHours])

  if (!isAvailable) {
    return (
      <span className="text-[10px] font-semibold text-red-600 bg-red-50 border border-red-200 rounded-full px-1.5 py-0.5">
        {t('unavailable')}
      </span>
    )
  }

  if (status.status === 'closed') {
    const opensAt = status.opensAt
    const isTomorrow = opensAt?.startsWith('tomorrow ')
    const time = opensAt
      ? isTomorrow ? opensAt.replace('tomorrow ', '') : opensAt
      : null

    return (
      <span className="text-[10px] font-semibold text-stone-500 bg-stone-100 border border-stone-200 rounded-full px-1.5 py-0.5">
        {time
          ? isTomorrow
            ? t('opens_tomorrow', { time })
            : t('opens_at', { time })
          : t('closed')}
      </span>
    )
  }

  if (status.status === 'open' && status.closesAt) {
    const [h, m] = status.closesAt.split(':').map(Number)
    const nowMin = new Date().getHours() * 60 + new Date().getMinutes()
    const closeMin = h * 60 + m
    const remaining = closeMin > nowMin ? closeMin - nowMin : closeMin + 1440 - nowMin
    if (remaining <= 60) {
      return (
        <span className="text-[10px] font-semibold text-amber-600 bg-amber-50 border border-amber-200 rounded-full px-1.5 py-0.5">
          {t('closes_at', { time: status.closesAt })}
        </span>
      )
    }
  }

  return (
    <span
      title={t('not_checked_tooltip')}
      className="inline-flex items-center gap-0.5 text-[10px] font-medium text-stone-400 cursor-default select-none"
    >
      <svg width="9" height="9" viewBox="0 0 9 9" fill="none" aria-hidden="true" className="shrink-0">
        <circle cx="4.5" cy="4.5" r="4" stroke="currentColor" strokeWidth="1"/>
        <path d="M4.5 3.5v0.1M4.5 5v1.5" stroke="currentColor" strokeWidth="1" strokeLinecap="round"/>
      </svg>
      {t('not_checked')}
    </span>
  )
}
