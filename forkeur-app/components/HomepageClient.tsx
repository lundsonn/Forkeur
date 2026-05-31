'use client'
import { useState, useMemo } from 'react'
import Link from 'next/link'
import { RestaurantSummary } from '@/lib/queries'
import RestaurantCard from './RestaurantCard'

export default function HomepageClient({
  restaurants,
  cuisines,
}: {
  restaurants: RestaurantSummary[]
  cuisines: string[]
}) {
  const [search, setSearch] = useState('')
  const [selectedCuisine, setSelectedCuisine] = useState<string | null>(null)

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
        <span className="text-sm text-stone-500">Brussels ↓</span>
      </div>

      {/* Hero */}
      <h1 className="text-[1.65rem] font-bold text-stone-900 leading-tight mb-4">
        Where are you<br />ordering from?
      </h1>

      {/* Search */}
      <div className="flex items-center gap-2.5 border border-stone-200 rounded-xl px-4 py-3 mb-5">
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

      {/* Cuisine filters — dynamic */}
      <div className="flex gap-2 overflow-x-auto pb-1 mb-4">
        <button
          onClick={() => setSelectedCuisine(null)}
          className={`shrink-0 rounded-full px-3 py-1 text-xs font-medium transition-colors ${
            !selectedCuisine ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-600'
          }`}
        >All</button>
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

      {/* List label */}
      <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-3">
        {search || selectedCuisine ? `${filtered.length} result${filtered.length !== 1 ? 's' : ''}` : 'Restaurants'}
      </p>

      {/* Restaurant list */}
      <div>
        {filtered.map((r, i) => (
          <Link key={r.id} href={`/restaurant/${r.id}`}>
            <RestaurantCard restaurant={r} isLast={i === filtered.length - 1} />
          </Link>
        ))}
        {filtered.length === 0 && (
          <p className="text-center text-stone-400 text-sm py-16">No restaurants found</p>
        )}
      </div>
    </div>
  )
}
