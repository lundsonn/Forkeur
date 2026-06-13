'use client'

import { useState, useMemo } from 'react'
import { useTranslations } from 'next-intl'
import type { DealItem } from '../lib/deals'
import type { ActiveType, ActivePlatform, SortMode } from '../lib/deals'
import { matchesFilter, filterCounts, sortDeals, savingsEstimate } from '../lib/deals'
import FeaturedStrip from './FeaturedStrip'

function freshnessColor(oldestScrapedAt: string): 'stone' | 'amber' | 'red' {
  const ageMs = Date.now() - new Date(oldestScrapedAt).getTime()
  const ageMin = ageMs / 60_000
  if (ageMin < 90) return 'stone'
  if (ageMin < 180) return 'amber'
  return 'red'
}

function FreshnessChip({ deals }: { deals: DealItem[] }) {
  const t = useTranslations()
  if (deals.length === 0) return null
  const oldest = deals.reduce((min, d) => d.scraped_at < min ? d.scraped_at : min, deals[0].scraped_at)
  const ageMin = Math.round((Date.now() - new Date(oldest).getTime()) / 60_000)
  const color = freshnessColor(oldest)
  const colorClass = { stone: 'text-stone-500', amber: 'text-amber-600', red: 'text-red-600' }[color]
  const label = color === 'red'
    ? t('deals.freshness_stale')
    : color === 'amber'
    ? t('deals.freshness_warning', { minutes: ageMin })
    : t('deals.freshness', { minutes: ageMin })
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${colorClass}`}>
      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
      </svg>
      {label}
    </span>
  )
}

const BADGE_COLOR: Record<string, string> = {
  pct_discount: 'bg-orange-500 text-white',
  abs_discount: 'bg-orange-500 text-white',
  free_delivery: 'bg-stone-700 text-white',
  bogo: 'bg-amber-600 text-white',
  free_item: 'bg-stone-600 text-white',
}

const PLATFORM_DOT: Record<string, string> = {
  uber_eats: 'bg-orange-500',
  deliveroo: 'bg-teal-500',
  takeaway: 'bg-stone-700',
}

function DealCard({ deal }: { deal: DealItem }) {
  const t = useTranslations()
  const badgeColor = BADGE_COLOR[deal.promo_type] ?? 'bg-stone-500 text-white'
  const dotColor = PLATFORM_DOT[deal.platform] ?? 'bg-stone-400'
  const savings = savingsEstimate(deal)
  return (
    <div className="rounded-xl border border-stone-200 bg-white shadow-sm overflow-hidden flex flex-col">
      <div className={`${badgeColor} px-4 py-4 relative`}>
        <p className="text-base font-bold leading-snug line-clamp-2">{deal.label}</p>
        <div className="absolute top-2 right-3 text-right text-xs opacity-80 space-y-0.5">
          <div className="flex items-center justify-end gap-1">
            <span className={`inline-block w-2 h-2 rounded-full ${dotColor} opacity-90`} />
            <span>{t(`platform.${deal.platform}`)}</span>
          </div>
          {deal.rating && (
            <div>★ {deal.rating.toFixed(1)}{deal.review_count ? ` (${deal.review_count})` : ''}</div>
          )}
        </div>
      </div>
      <div className="px-4 py-3 flex flex-col gap-1.5 flex-1">
        <p className="font-semibold text-stone-900 leading-snug">{deal.restaurant_name}</p>
        {(deal.cuisine.length > 0 || deal.area) && (
          <p className="text-sm text-stone-400">
            {[deal.cuisine.slice(0, 2).join(' · '), deal.area].filter(Boolean).join(' · ')}
          </p>
        )}
        {savings && <p className="text-sm text-stone-600">{savings}</p>}
        {deal.min_order != null && deal.min_order > 0 && (
          <p className="text-xs text-stone-400">{t('deals.min_order', { amount: deal.min_order })}</p>
        )}
        <div className="mt-auto pt-3">
          {deal.platform_url ? (
            <a href={deal.platform_url} target="_blank" rel="noopener noreferrer"
               className="block text-center text-sm font-medium text-orange-600 hover:text-orange-700 border border-orange-200 rounded-lg py-2">
              {t('deals.order_on', { platform: t(`platform.${deal.platform}`) })}
            </a>
          ) : (
            <span className="block text-center text-sm text-stone-400 py-2">
              {t(`platform.${deal.platform}`)}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

const TYPE_FILTERS: { key: ActiveType; i18nKey: string }[] = [
  { key: 'all',           i18nKey: 'filters.all' },
  { key: 'free_delivery', i18nKey: 'filters.free_delivery' },
  { key: 'pct',           i18nKey: 'filters.pct' },
  { key: 'bogo',          i18nKey: 'filters.bogo' },
  { key: 'abs',           i18nKey: 'filters.eur_off' },
  { key: 'free_item',     i18nKey: 'filters.free_item' },
]

const PLATFORM_FILTERS: { key: ActivePlatform; labelKey: string; dotColor: string }[] = [
  { key: 'all',       labelKey: 'filters.all',        dotColor: '' },
  { key: 'uber_eats', labelKey: 'platform.uber_eats', dotColor: 'bg-orange-500' },
  { key: 'deliveroo', labelKey: 'platform.deliveroo', dotColor: 'bg-teal-500' },
  { key: 'takeaway',  labelKey: 'platform.takeaway',  dotColor: 'bg-stone-700' },
]

const SORT_OPTIONS: { value: SortMode; i18nKey: string }[] = [
  { value: 'best',   i18nKey: 'deals.sort_best' },
  { value: 'saving', i18nKey: 'deals.sort_saving' },
  { value: 'rated',  i18nKey: 'deals.sort_rated' },
  { value: 'newest', i18nKey: 'deals.sort_newest' },
]

export default function DealsClient({ deals }: { deals: DealItem[] }) {
  const t = useTranslations()
  const [activeType, setActiveType] = useState<ActiveType>('all')
  const [activePlatform, setActivePlatform] = useState<ActivePlatform>('all')
  const [sortMode, setSortMode] = useState<SortMode>('best')

  const counts = useMemo(() => filterCounts(deals, activePlatform), [deals, activePlatform])
  const filtered = useMemo(
    () => sortDeals(deals.filter(d => matchesFilter(d, activeType, activePlatform)), sortMode),
    [deals, activeType, activePlatform, sortMode]
  )

  const clearFilters = () => { setActiveType('all'); setActivePlatform('all'); setSortMode('best') }
  const isFiltered = activeType !== 'all' || activePlatform !== 'all'

  if (deals.length === 0) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12 text-center text-stone-500">
        <p className="font-medium">{t('deals.empty_total')}</p>
        <p className="text-sm mt-1">{t('deals.empty_total_hint')}</p>
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto px-4 pb-12">
      {/* Page header */}
      <div className="py-6 flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-stone-900">{t('deals.heading')}</h1>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-stone-500 text-sm">{filtered.length} {t('filters.all').toLowerCase()} offers</span>
          <FreshnessChip deals={deals} />
        </div>
      </div>

      {/* Sticky filter bar */}
      <div className="sticky top-0 z-10 bg-white/95 backdrop-blur-sm border-b border-stone-100 py-3 -mx-4 px-4 mb-6">
        {/* Row 1: type filters */}
        <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-none">
          {TYPE_FILTERS.map(({ key, i18nKey }) => (
            <button key={key} onClick={() => setActiveType(key)}
              className={`flex-shrink-0 rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                activeType === key ? 'bg-orange-500 text-white' : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
              }`}>
              {t(i18nKey)}
              {key !== 'all' && counts[key] > 0 && <span className="ml-1 opacity-70">({counts[key]})</span>}
              {key === 'all' && <span className="ml-1 opacity-70">({counts.all})</span>}
            </button>
          ))}
        </div>

        {/* Row 2: platform filters — horizontal scroll, no wrap */}
        <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none mt-2">
          {PLATFORM_FILTERS.map(({ key, labelKey, dotColor }) => (
            <button key={key} onClick={() => setActivePlatform(key)}
              className={`flex-shrink-0 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium transition-colors ${
                activePlatform === key ? 'bg-stone-800 text-white' : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
              }`}>
              {dotColor && <span className={`inline-block w-2 h-2 rounded-full ${dotColor}`} />}
              {t(labelKey)}
            </button>
          ))}
        </div>

        {/* Row 3: sort — right-aligned */}
        <div className="flex items-center justify-end gap-1.5 mt-2">
          <span className="text-xs text-stone-400">{t('deals.sort_label')}:</span>
          <select value={sortMode} onChange={e => setSortMode(e.target.value as SortMode)}
            className="text-sm text-stone-700 bg-transparent border-0 outline-none cursor-pointer pr-1">
            {SORT_OPTIONS.map(({ value, i18nKey }) => (
              <option key={value} value={value}>{t(i18nKey)}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Featured deals strip */}
      <FeaturedStrip deals={deals} />

      {/* Deal grid / empty state */}
      {filtered.length === 0 ? (
        <div className="py-12 text-center text-stone-500">
          <p className="font-medium">{t('deals.empty_filtered')}</p>
          <p className="text-sm mt-1">{t('deals.empty_filtered_hint', { total: deals.length })}</p>
          {isFiltered && (
            <button onClick={clearFilters} className="mt-4 text-sm text-orange-600 hover:text-orange-700 font-medium">
              {t('deals.clear_filters')}
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map(deal => <DealCard key={deal.id} deal={deal} />)}
        </div>
      )}
    </div>
  )
}
