'use client'
import { useState, useMemo } from 'react'
import Link from 'next/link'
import type { DealItem, DealFilter } from '@/lib/deals'
import {
  DEAL_FILTERS,
  matchesFilter,
  filterCounts,
  sortDeals,
  badgeText,
} from '@/lib/deals'

const PLATFORM_META: Record<string, { name: string; color: string }> = {
  uber_eats: { name: 'UberEats', color: 'bg-black text-white' },
  deliveroo: { name: 'Deliveroo', color: 'bg-teal-500 text-white' },
  takeaway: { name: 'Takeaway', color: 'bg-orange-500 text-white' },
}

type ActiveSet = Set<Exclude<DealFilter, 'all'>>

export default function DealsClient({ deals }: { deals: DealItem[] }) {
  const [active, setActive] = useState<ActiveSet>(new Set())

  const counts = useMemo(() => filterCounts(deals), [deals])

  const visible = useMemo(() => {
    const matched = deals.filter((d) => matchesFilter(d, active))
    return sortDeals(matched, active)
  }, [deals, active])

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
        <Link href="/" className="text-xs text-stone-400 hover:text-stone-600">
          ← Restaurants
        </Link>
      </div>

      {/* Hero */}
      <h1 className="text-[1.65rem] font-bold leading-tight mb-1" style={{ color: '#1A1A1A' }}>
        Best deals
      </h1>
      <p className="text-sm text-stone-400 mb-5">
        {deals.length} live offers across UberEats, Deliveroo & Takeaway
      </p>

      {/* Filter pills */}
      <div className="flex gap-2 overflow-x-auto pb-2 mb-5 scrollbar-hide">
        {DEAL_FILTERS.map(({ key, label }) => {
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
              <span>{label}</span>
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
          No deals in this category right now.
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
              <Link
                key={d.id}
                href={`/restaurant/${d.restaurant_id}`}
                className="block border border-stone-100 rounded-2xl p-4 hover:border-stone-300 hover:shadow-sm transition-all"
              >
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
                    {badgeText(d)}
                  </span>
                  {d.min_order != null && (
                    <span className="text-xs" style={{ color: '#888780' }}>
                      Min. €{d.min_order}
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
            )
          })}
        </div>
      )}
    </div>
  )
}
