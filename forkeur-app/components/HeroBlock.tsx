'use client'

import { useTranslations } from 'next-intl'
import { findBestSavingExample } from '@/lib/savings'
import { PLATFORM_LABELS } from '@/lib/basket'
import type { RestaurantSummary } from '@/lib/queries'

type Props = {
  restaurants: RestaurantSummary[]
  neighborhood: string | null
}

export default function HeroBlock({ restaurants }: Props) {
  const t = useTranslations()
  const example = findBestSavingExample(restaurants)

  return (
    <div className="py-4 flex flex-col gap-2">
      <p className="text-sm text-stone-500 text-center">{t('hero.credibility')}</p>

      {example !== null && (
        <>
          <p className="text-sm font-semibold text-stone-700 text-center">{t('hero.rightNow')}</p>
          <p className="text-center text-stone-900">
            <span className="font-bold">{example.restaurant.name}</span>
            {' '}
            <span className="text-green-600 font-semibold">€{(example.savingsCents / 100).toFixed(2)}</span>
            {' cheaper on '}
            <span className="font-semibold">{PLATFORM_LABELS[example.winner.platform]}</span>
          </p>
        </>
      )}

      <p className="text-xs text-stone-400 text-center">{t('hero.neutrality')}</p>
    </div>
  )
}
