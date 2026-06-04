'use client'
import { useState, useMemo } from 'react'
import Link from 'next/link'
import type { DealItem, DealFilter } from '@/lib/deals'
import {
  DEAL_FILTERS,
  matchesFilter,
  filterCounts,
  sortDeals,
} from '@/lib/deals'
import { useTranslations } from 'next-intl'
import LangToggle from './LangToggle'

const PLATFORM_META: Record<string, { name: string; color: string }> = {
  uber_eats: { name: 'UberEats', color: 'bg-black text-white' },
  deliveroo: { name: 'Deliveroo', color: 'bg-teal-500 text-white' },
  takeaway: { name: 'Takeaway', color: 'bg-orange-500 text-white' },
}

type ActiveSet = Set<Exclude<DealFilter, 'all'>>

export default function DealsClient({ deals }: { deals: DealItem[] }) {
  const [active, setActive] = useState<ActiveSet>(new Set())
  const [search, setSearch] = useState('')

  const tNav = useTranslations('nav')
  const tDeals = useTranslations('deals')
  const tFilters = useTranslations('filters')
  const tBadge = useTranslations('badge')

  function localizedBadge(d: DealItem): string {
    switch (d.promo_type) {
      case 'bogo': return tBadge('bogo')
      case 'pct_discount': return d.value != null ? tBadge('pct_off', { value: Math.round(d.value) }) : '%'
      case 'abs_discount': return d.value != null ? tBadge('eur_off', { value: d.value.toFixed(2) }) : '€'
      case 'free_delivery': return tBadge('free_delivery')
      case 'free_item': return tBadge('free_item')
      default: return d.label
    }
  }

  const filterLabel: Record<DealFilter, string> = {
    all: tFilters('all'),
    bogo: tFilters('bogo'),
    pct: tFilters('pct'),
    free_delivery: tFilters('free_delivery'),
    free_item: tFilters('free_item'),
  }

  const counts = useMemo(() => filterCounts(deals), [deals])

  const visible = useMemo(() => {
    const q = search.toLowerCase()
    const matched = deals.filter(
      (d) => matchesFilter(d, active) && (!q || d.restaurant_name.toLowerCase().includes(q))
    )
    return sortDeals(matched, active)
  }, [deals, active, search])

  function toggle(key: DealFilter) {
    if (key === 'all') { setActive(new Set()); return }
    setActive((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <div className="max-w-md mx-auto px-5">
      {/* Nav */}
      <div className="flex items-center justify-between pt-5 pb-4">
        <Link href="/" className="flex items-center gap-1.5">
          <span className="text-stone-700 text-base">⑂</span>
          <span className="font-bold text-base tracking-tight">
            fork<span className="text-orange-500">eur</span>
          </span>
        </Link>
        <div className="flex items-center gap-1">
          <LangToggle />
          <Link href="/" className="text-xs text-stone-400 hover:text-stone-600">
            {tNav('back_restaurants')}
          </Link>
        </div>
      </div>

      {/* Hero */}
      <h1 className="text-[1.65rem] font-bold leading-tight mb-1" style={{ color: '#1A1A1A' }}>
        {tDeals('heading')}
      </h1>
      <p className="text-sm text-stone-400 mb-5">
        {tDeals('subtitle', { count: deals.length })}
      </p>

      {/* Search */}
      <div className="flex items-center gap-2.5 border border-stone-200 rounded-xl px-4 py-3 mb-4">
        <span className="text-stone-400 text-sm">🔍</span>
        <input
          className="flex-1 text-sm outline-none placeholder:text-stone-400"
          placeholder={tDeals('search_placeholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button type="button" onClick={() => setSearch('')} className="text-stone-300 text-xs">✕</button>
        )}
      </div>

      {/* Filter pills */}
      <div className="flex gap-2 overflow-x-auto pb-2 mb-5 scrollbar-hide">
        {DEAL_FILTERS.map(({ key }) => {
          const isActive = key === 'all' ? active.size === 0 : active.has(key)
          const count = counts[key]
          if (key !== 'all' && count === 0) return null
          return (
            <button
              key={key}
              onClick={() => toggle(key)}
              className={`flex-shrink-0 flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                isActive
                  ? 'text-white border-transparent'
                  : 'bg-white text-stone-600 border-stone-200 hover:border-stone-300'
              }`}
              style={isActive ? { backgroundColor: '#2E86D8' } : undefined}
            >
              <span>{filterLabel[key]}</span>
              {key !== 'all' && (
                <span className={`text-[10px] ${isActive ? 'text-blue-100' : 'text-stone-400'}`}>
                  {count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Deal cards */}
      {visible.length === 0 ? (
        <p className="text-sm text-stone-400 text-center py-16">
          {tDeals('none')}
        </p>
      ) : (
        <div className="space-y-3 pb-10">
          {visible.map((d) => {
            const plat = PLATFORM_META[d.platform] ?? {
              name: d.platform,
              color: 'bg-stone-200 text-stone-700',
            }
            const meta = [d.cuisine.join(' · '), d.area].filter(Boolean).join(' · ')
            return (
              <div
                key={d.id}
                className="border border-stone-100 rounded-2xl p-4 hover:border-stone-300 hover:shadow-sm transition-all"
              >
                <Link href={`/restaurant/${d.restaurant_id}`} className="block">
                  {/* Top row: name + platform */}
                  <div className="flex items-start justify-between gap-3 mb-1">
                    <span className="font-semibold text-sm leading-snug" style={{ color: '#1A1A1A' }}>
                      {d.restaurant_name}
                    </span>
                    <span className={`flex-shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-full ${plat.color}`}>
                      {plat.name}
                    </span>
                  </div>

                  {/* Cuisine · area */}
                  {meta && (
                    <p className="text-xs mb-2.5" style={{ color: '#888780' }}>
                      {meta}
                    </p>
                  )}

                  {/* Deal badge + min order + rating */}
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className="inline-flex items-center text-xs font-semibold px-2.5 py-1 rounded-full text-white"
                      style={{ backgroundColor: '#1E8A5A' }}
                    >
                      {localizedBadge(d)}
                    </span>
                    {d.min_order != null && (
                      <span className="text-xs" style={{ color: '#888780' }}>
                        {tDeals('min_order', { amount: d.min_order })}
                      </span>
                    )}
                    {d.rating != null && (
                      <span className="ml-auto text-xs font-medium flex items-center gap-0.5" style={{ color: '#1A1A1A' }}>
                        <span className="text-amber-400">★</span>
                        {d.rating.toFixed(1)}
                        {d.review_count != null && (
                          <span className="text-stone-400 font-normal">({d.review_count})</span>
                        )}
                      </span>
                    )}
                  </div>
                </Link>

                {/* Order CTA */}
                {d.platform_url && (
                  <a
                    href={d.platform_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-3 flex items-center justify-center w-full py-2 rounded-xl text-xs font-semibold text-white bg-stone-900 hover:bg-stone-700 transition-colors"
                  >
                    {tDeals('order_on', { platform: plat.name })}
                  </a>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
