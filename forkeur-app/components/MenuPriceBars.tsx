'use client'

import { useTranslations } from 'next-intl'
import type { MenuItemWithPrices } from '@/lib/queries'
import { PLATFORM_LABELS, centsToEuro } from '@/lib/basket'
import { computeMenuStats } from '@/lib/menu-stats'

type Props = {
  items: MenuItemWithPrices[]
}

export default function MenuPriceBars({ items }: Props) {
  const t = useTranslations('menuPrices')
  const stats = computeMenuStats(items)
  if (!stats) return null

  const {
    platformStats,
    cheapestAvgPlatform,
    dearestAvgPlatform,
    maxAvgCents,
    avgPerItemGapCents,
    comparedCount,
    totalCount,
  } = stats

  return (
    <div className="px-5 mb-2 mt-4">
      <div className="bg-white rounded-xl border border-stone-100 p-4">
        {/* Eyebrow */}
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
          <p className="text-sm font-bold text-stone-900">
            {t('lowest_headline', { platform: PLATFORM_LABELS[cheapestAvgPlatform] })}
          </p>
        </div>

        {/* Sub */}
        {avgPerItemGapCents > 0 && (
          <p className="text-xs text-stone-500 mt-1">
            {t('cheaper_per_item', {
              amount: centsToEuro(avgPerItemGapCents),
              other: PLATFORM_LABELS[dearestAvgPlatform],
            })}
          </p>
        )}

        {/* Bars */}
        <div className="flex flex-col gap-2.5 mt-3">
          {platformStats.map((ps) => {
            const isCheapest = ps.platform === cheapestAvgPlatform
            const widthPct = maxAvgCents > 0 ? (ps.avgCents / maxAvgCents) * 100 : 100
            return (
              <div key={ps.platform}>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-stone-700">{PLATFORM_LABELS[ps.platform]}</span>
                  <span className={isCheapest ? 'font-bold text-green-600' : 'text-stone-500'}>
                    {t('avg', { amount: centsToEuro(ps.avgCents) })}
                  </span>
                </div>
                <div className="bg-stone-100 rounded-full h-2 mt-1 overflow-hidden">
                  <div
                    className={`h-2 rounded-full ${isCheapest ? 'bg-green-500' : 'bg-stone-300'}`}
                    style={{ width: `${widthPct}%` }}
                  />
                </div>
              </div>
            )
          })}
        </div>

        {/* Footnote */}
        <p className="text-[11px] text-stone-500 mt-3">
          {t('compared_footnote', { compared: comparedCount, total: totalCount })}
        </p>
      </div>
    </div>
  )
}
