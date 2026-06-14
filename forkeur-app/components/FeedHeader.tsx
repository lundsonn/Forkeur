'use client'

import { useTranslations } from 'next-intl'

export type SortBy = 'cheapest' | 'fastest'

type Props = {
  neighborhood: string | null
  sortBy: SortBy
  onSortChange: (sort: SortBy) => void
  onNeighborhoodClick: () => void
}

export default function FeedHeader({ neighborhood, sortBy, onSortChange, onNeighborhoodClick }: Props) {
  const t = useTranslations()

  return (
    <div className="flex items-center justify-between px-4 py-2">
      {/* Left: neighborhood label */}
      <button
        onClick={onNeighborhoodClick}
        className="text-sm font-semibold text-stone-700 flex items-center gap-1"
      >
        {neighborhood ?? t('feed.allBrussels')}
        <span aria-hidden>▾</span>
      </button>

      {/* Right: sort pills */}
      <div className="flex gap-2" role="group" aria-label="Sort by">
        <button
          onClick={() => onSortChange('cheapest')}
          className={
            sortBy === 'cheapest'
              ? 'text-sm px-3 py-1 rounded-full bg-orange-500 text-white font-semibold'
              : 'text-sm px-3 py-1 rounded-full bg-stone-100 text-stone-600'
          }
          aria-pressed={sortBy === 'cheapest'}
        >
          {t('results.cheapest')}
        </button>
        <button
          onClick={() => onSortChange('fastest')}
          className={
            sortBy === 'fastest'
              ? 'text-sm px-3 py-1 rounded-full bg-orange-500 text-white font-semibold'
              : 'text-sm px-3 py-1 rounded-full bg-stone-100 text-stone-600'
          }
          aria-pressed={sortBy === 'fastest'}
        >
          {t('results.fastest')}
        </button>
      </div>
    </div>
  )
}
