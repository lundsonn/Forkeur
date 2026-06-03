'use client'
import { useState, useMemo } from 'react'
import Link from 'next/link'
import type { RestaurantSummary } from '@/lib/queries'
import RestaurantCard from './RestaurantCard'
import MapView from './MapView'
import { useTranslations } from 'next-intl'
import LangToggle from './LangToggle'

export default function HomepageClient({
  restaurants,
  cuisines,
}: {
  restaurants: RestaurantSummary[]
  cuisines: string[]
}) {
  const [search, setSearch] = useState('')
  const [selectedCuisine, setSelectedCuisine] = useState<string | null>(null)
  const [view, setView] = useState<'list' | 'map'>('list')

  const tNav = useTranslations('nav')
  const tHero = useTranslations('hero')
  const tSearch = useTranslations('search')
  const tFilters = useTranslations('filters')
  const tResults = useTranslations('results')
  const tDirect = useTranslations('direct')

  const filtered = useMemo(
    () =>
      restaurants.filter((r) => {
        const matchSearch = r.name.toLowerCase().includes(search.toLowerCase())
        const matchCuisine =
          !selectedCuisine ||
          r.cuisine.some((c) => c.toLowerCase().includes(selectedCuisine.toLowerCase()))
        return matchSearch && matchCuisine
      }),
    [restaurants, search, selectedCuisine]
  )

  return (
    <div className="max-w-md mx-auto px-5">
      {/* Nav */}
      <div className="flex items-center justify-between pt-5 pb-4">
        <div className="flex items-center gap-1.5">
          <span className="text-stone-700 text-base">⑂</span>
          <span className="font-bold text-base tracking-tight">
            fork<span className="text-orange-500">eur</span>
          </span>
        </div>
        <div className="flex items-center gap-1">
          <LangToggle />
          <Link
            href="/deals"
            className="px-2.5 py-1 rounded-lg text-xs font-medium text-orange-500 hover:text-orange-600 transition-colors"
          >
            {tNav('deals')}
          </Link>
          <button
            onClick={() => setView('list')}
            className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
              view === 'list'
                ? 'bg-stone-900 text-white'
                : 'text-stone-500 hover:text-stone-700'
            }`}
          >
            {tNav('list')}
          </button>
          <button
            onClick={() => setView('map')}
            className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
              view === 'map'
                ? 'bg-stone-900 text-white'
                : 'text-stone-500 hover:text-stone-700'
            }`}
          >
            {tNav('map')}
          </button>
        </div>
      </div>

      {/* Hero */}
      <h1 className="text-[1.65rem] font-bold text-stone-900 leading-tight mb-4">
        {tHero('heading_line1')}<br />{tHero('heading_line2')}
      </h1>

      {/* Search */}
      <div className="flex items-center gap-2.5 border border-stone-200 rounded-xl px-4 py-3 mb-5">
        <span className="text-stone-400 text-sm">🔍</span>
        <input
          className="flex-1 text-sm outline-none placeholder:text-stone-400"
          placeholder={tSearch('placeholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button onClick={() => setSearch('')} className="text-stone-300 text-xs">✕</button>
        )}
      </div>

      {/* Cuisine filters — dynamic */}
      <div className="flex gap-2 overflow-x-auto pb-1 mb-4">
        <button
          onClick={() => setSelectedCuisine(null)}
          className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
            !selectedCuisine ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-600'
          }`}
        >{tFilters('all')}</button>
        {cuisines.map((c) => (
          <button
            key={c}
            onClick={() => setSelectedCuisine(selectedCuisine === c ? null : c)}
            className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              selectedCuisine === c ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-600'
            }`}
          >{c}</button>
        ))}
      </div>

      {view === 'map' ? (
        <MapView
          restaurants={filtered}
          height="calc(100vh - 240px)"
        />
      ) : (
        <>
          {/* List label */}
          <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-3">
            {search || selectedCuisine ? tResults('count', { count: filtered.length }) : tResults('restaurants')}
          </p>

          {/* Restaurant list */}
          <div>
            {filtered.map((r, i) => (
              <Link key={r.id} href={`/restaurant/${r.id}`}>
                <RestaurantCard
                  restaurant={r}
                  isLast={i === filtered.length - 1}
                  directBadge={
                    r.direct_url_type === 'menu'
                      ? tDirect('badge_menu')
                      : r.direct_url_type === 'website'
                        ? tDirect('badge_website')
                        : tDirect('badge')
                  }
                />
              </Link>
            ))}
            {filtered.length === 0 && (
              <p className="text-center text-stone-400 text-sm py-16">{tResults('none')}</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
