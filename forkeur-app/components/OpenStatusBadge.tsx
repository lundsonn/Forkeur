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
    return (
      <span className="text-[10px] font-semibold text-red-600 bg-red-50 border border-red-200 rounded-full px-1.5 py-0.5">
        {t('closed')}
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

  return null
}
