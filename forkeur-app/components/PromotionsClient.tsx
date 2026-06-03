'use client'
import { useState, useMemo } from 'react'
import Link from 'next/link'
import type { PromoItem } from '@/lib/queries'

const PROMO_META: Record<string, { label: string; emoji: string; color: string }> = {
  free_delivery: { label: 'Free delivery',  emoji: '🚚', color: 'bg-emerald-100 text-emerald-700' },
  bogo:          { label: '2-for-1',         emoji: '🎁', color: 'bg-orange-100 text-orange-700'  },
  pct_discount:  { label: '% off',           emoji: '💸', color: 'bg-purple-100 text-purple-700'  },
  abs_discount:  { label: '€ off',           emoji: '💶', color: 'bg-blue-100 text-blue-700'      },
  free_item:     { label: 'Free item',       emoji: '⭐', color: 'bg-amber-100 text-amber-700'    },
  spend_save:    { label: 'Spend & save',    emoji: '🏷️', color: 'bg-teal-100 text-teal-700'      },
  other:         { label: 'Deal',            emoji: '🔥', color: 'bg-stone-100 text-stone-600'    },
}

const PLATFORM_META: Record<string, { name: string; color: string }> = {
  uber_eats:  { name: 'UberEats',  color: 'bg-black text-white'           },
  deliveroo:  { name: 'Deliveroo', color: 'bg-teal-500 text-white'        },
  takeaway:   { name: 'Takeaway',  color: 'bg-orange-500 text-white'      },
}

const FILTER_TYPES = ['all', 'free_delivery', 'bogo', 'pct_discount', 'free_item', 'abs_discount', 'spend_save'] as const
type FilterType = typeof FILTER_TYPES[number]

function promoSummary(p: PromoItem): string {
  if (p.promo_type === 'pct_discount' && p.value) {
    return `${p.value}% off${p.min_order ? ` from €${p.min_order}` : ''}`
  }
  if (p.promo_type === 'abs_discount' && p.value) {
    return `€${p.value} off${p.min_order ? ` from €${p.min_order}` : ''}`
  }
  if (p.promo_type === 'free_delivery') {
    return p.min_order ? `Free delivery from €${p.min_order}` : 'Free delivery'
  }
  if (p.promo_type === 'free_item') {
    return p.min_order ? `Free item from €${p.min_order}` : 'Free item'
  }
  if (p.promo_type === 'bogo') return 'Buy 1 get 1 free'
  if (p.promo_type === 'spend_save') {
    return p.min_order ? `Save from €${p.min_order}` : 'Spend & save'
  }
  return p.label
}

export default function PromotionsClient({ promos }: { promos: PromoItem[] }) {
  const [filter, setFilter] = useState<FilterType>('all')
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    return promos.filter((p) => {
      const matchType = filter === 'all' || p.promo_type === filter
      const matchSearch = !search || p.restaurant_name.toLowerCase().includes(search.toLowerCase())
      return matchType && matchSearch
    })
  }, [promos, filter, search])

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: promos.length }
    for (const p of promos) c[p.promo_type] = (c[p.promo_type] ?? 0) + 1
    return c
  }, [promos])

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
      <h1 className="text-[1.65rem] font-bold text-stone-900 leading-tight mb-1">
        Deals & promos
      </h1>
      <p className="text-sm text-stone-400 mb-5">
        {promos.length} active offers on UberEats
      </p>

      {/* Search */}
      <div className="flex items-center gap-2.5 border border-stone-200 rounded-xl px-4 py-3 mb-4">
        <span className="text-stone-400 text-sm">🔍</span>
        <input
          className="flex-1 text-sm outline-none placeholder:text-stone-400"
          placeholder="Search a restaurant"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button onClick={() => setSearch('')} className="text-stone-300 text-xs">✕</button>
        )}
      </div>

      {/* Filter chips */}
      <div className="flex gap-2 overflow-x-auto pb-2 mb-5 scrollbar-hide">
        {FILTER_TYPES.map((type) => {
          const meta = type === 'all' ? null : PROMO_META[type]
          const isActive = filter === type
          const count = counts[type] ?? 0
          if (type !== 'all' && count === 0) return null
          return (
            <button
              key={type}
              onClick={() => setFilter(type)}
              className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                isActive
                  ? 'bg-stone-900 text-white'
                  : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
              }`}
            >
              {meta && <span>{meta.emoji}</span>}
              <span>{type === 'all' ? 'All' : meta!.label}</span>
              <span className={`text-[10px] ${isActive ? 'text-stone-400' : 'text-stone-400'}`}>
                {count}
              </span>
            </button>
          )
        })}
      </div>

      {/* Promo cards */}
      {filtered.length === 0 ? (
        <p className="text-sm text-stone-400 text-center py-10">No deals match your search.</p>
      ) : (
        <div className="space-y-3 pb-10">
          {filtered.map((p) => {
            const pm = PROMO_META[p.promo_type] ?? PROMO_META.other
            const plat = PLATFORM_META[p.platform] ?? { name: p.platform, color: 'bg-stone-200 text-stone-700' }
            return (
              <Link
                key={p.id}
                href={`/restaurant/${p.restaurant_id}`}
                className="block border border-stone-100 rounded-2xl p-4 hover:border-stone-300 hover:shadow-sm transition-all"
              >
                {/* Top row */}
                <div className="flex items-start justify-between gap-3 mb-2">
                  <span className="font-semibold text-sm text-stone-900 leading-snug">
                    {p.restaurant_name}
                  </span>
                  <span className={`flex-shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-full ${plat.color}`}>
                    {plat.name}
                  </span>
                </div>

                {/* Promo content */}
                <div className="flex items-center gap-2">
                  <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${pm.color}`}>
                    {pm.emoji} {pm.label}
                  </span>
                  <span className="text-xs text-stone-500 truncate">
                    {promoSummary(p)}
                  </span>
                </div>

                {/* Raw label if different from summary */}
                {p.label !== promoSummary(p) && (
                  <p className="text-[11px] text-stone-400 mt-1.5 truncate">{p.label}</p>
                )}
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
