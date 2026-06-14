'use client'
import { useState, useMemo, useEffect, Suspense } from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import type { RestaurantSummary } from '@/lib/queries'
import RestaurantCard from './RestaurantCard'
import { useTranslations } from 'next-intl'
import LangToggle from './LangToggle'
import { getOpenStatus } from '@/lib/hours'
import HeroBlock from './HeroBlock'
import FeedHeader, { type SortBy } from './FeedHeader'

const MapView = dynamic(() => import('./MapView'), {
  ssr: false,
  loading: () => <div className="rounded-xl border border-stone-200 bg-stone-50 animate-pulse h-[calc(100vh-240px)]" />,
})

function opensAtToSortKey(opensAt: string | null): number {
  if (opensAt === null) return Infinity
  if (opensAt.startsWith('tomorrow ')) {
    const time = opensAt.slice('tomorrow '.length)
    const [h, m] = time.split(':').map(Number)
    return 1440 + h * 60 + m
  }
  const [h, m] = opensAt.split(':').map(Number)
  return h * 60 + m
}

function getClosedSortKey(r: RestaurantSummary, now: Date): { isClosed: boolean; opensAtKey: number } {
  const bestListing = r.listings.find((l) => l.opening_hours != null) ?? r.listings[0] ?? null
  const openingHours = bestListing?.opening_hours ?? null
  const isAvailable = r.listings.some((l) => l.is_available)
  const status = getOpenStatus(openingHours, now)
  const isClosed = !isAvailable || status.status === 'closed'
  const opensAtKey = isClosed && status.status === 'closed' ? opensAtToSortKey(status.opensAt) : 0
  return { isClosed, opensAtKey }
}

function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371
  const dLat = ((lat2 - lat1) * Math.PI) / 180
  const dLng = ((lng2 - lng1) * Math.PI) / 180
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) * Math.sin(dLng / 2) ** 2
  return R * 2 * Math.asin(Math.sqrt(a))
}

export default function HomepageClient({
  restaurants,
  cuisines,
}: {
  restaurants: RestaurantSummary[]
  cuisines: string[]
}) {
  const PAGE_SIZE = 20

  const [search, setSearch] = useState('')
  const [userCoords, setUserCoords] = useState<[number, number] | null>(null)
  const [selectedCuisine, setSelectedCuisine] = useState<string | null>(null)
  const [selectedNeighborhood, setSelectedNeighborhood] = useState<string | null>(null)
  const [neighborhoodSheetOpen, setNeighborhoodSheetOpen] = useState(false)
  const [sortBy, setSortBy] = useState<SortBy>('cheapest')
  const [view, setView] = useState<'list' | 'map'>('list')
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  useEffect(() => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (pos) => setUserCoords([pos.coords.latitude, pos.coords.longitude]),
      () => { /* denied or unavailable — stay null */ }
    )
  }, [])

  function resetAndSet<T>(setter: (v: T) => void) {
    return (v: T) => { setter(v); setVisibleCount(PAGE_SIZE) }
  }

  const tNav = useTranslations('nav')
  const tSearch = useTranslations('search')
  const tFilters = useTranslations('filters')
  const tResults = useTranslations('results')
  const tDirect = useTranslations('direct')
  const tCard = useTranslations('card')
  const tSort = useTranslations('sort')
  const tOwners = useTranslations('owners')
  const tFooter = useTranslations('footer')
  const tFeed = useTranslations('feed')

  const neighborhoods = useMemo(() => {
    const counts = new Map<string, number>()
    for (const r of restaurants) {
      if (r.neighborhood) {
        counts.set(r.neighborhood, (counts.get(r.neighborhood) ?? 0) + 1)
      }
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count }))
  }, [restaurants])

  const etaMap = useMemo(() => {
    const map = new Map<string, number | null>()
    for (const r of restaurants) {
      const etas = r.listings.map((l) => l.eta_min).filter((e): e is number => e !== null)
      map.set(r.id, etas.length > 0 ? Math.min(...etas) : null)
    }
    return map
  }, [restaurants])

  const filtered = useMemo(() => {
    const base = restaurants.filter((r) => {
      const matchSearch = r.name.toLowerCase().includes(search.toLowerCase())
      const matchNeighborhood = !selectedNeighborhood || r.neighborhood === selectedNeighborhood
      const matchCuisine = !selectedCuisine || r.cuisine.includes(selectedCuisine)
      return matchSearch && matchNeighborhood && matchCuisine
    })

    const result = [...base].sort((a, b) => {
      if (sortBy === 'cheapest') {
        return (b.cheapest?.savings_cents ?? 0) - (a.cheapest?.savings_cents ?? 0)
      }
      // fastest
      const ma = etaMap.get(a.id) ?? null
      const mb = etaMap.get(b.id) ?? null
      if (ma === null && mb === null) return 0
      if (ma === null) return 1
      if (mb === null) return -1
      return ma - mb
    })

    // Primary: more platforms first; within group, direct website first; then open/closed
    const now = new Date()
    return [...result].sort((a, b) => {
      const ca = getClosedSortKey(a, now)
      const cb = getClosedSortKey(b, now)
      if (ca.isClosed !== cb.isClosed) return ca.isClosed ? 1 : -1
      if (ca.isClosed && cb.isClosed) return ca.opensAtKey - cb.opensAtKey
      const pc = b.listings.length - a.listings.length
      if (pc !== 0) return pc
      const da = a.direct_url_type != null ? -1 : 0
      const db = b.direct_url_type != null ? -1 : 0
      return da - db
    })
  }, [restaurants, search, selectedNeighborhood, selectedCuisine, sortBy, etaMap])

  const hasFilter = !!(search || selectedNeighborhood)

  const nearYou = useMemo(() => {
    if (!userCoords || hasFilter) return []
    const [ulat, ulng] = userCoords
    return restaurants
      .filter((r): r is typeof r & { lat: number; lng: number } => r.lat !== null && r.lng !== null)
      .sort((a, b) => haversineKm(ulat, ulng, a.lat, a.lng) - haversineKm(ulat, ulng, b.lat, b.lng))
      .slice(0, 20)
      .sort((a, b) => (b.cheapest?.savings_cents ?? 0) - (a.cheapest?.savings_cents ?? 0))
      .slice(0, 3)
  }, [userCoords, hasFilter, restaurants])

  return (
    <div className="w-full max-w-md mx-auto px-5">
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
          <Link
            href="/owners"
            className="hidden min-[450px]:inline-flex items-center px-2.5 min-h-[44px] rounded-lg text-xs font-medium text-stone-400 hover:text-stone-600 transition-colors"
          >
            {tOwners('nav_link')}
          </Link>
          <Link
            href="/deals"
            className="px-2.5 min-h-[44px] inline-flex items-center rounded-lg text-xs font-medium text-orange-500 hover:text-orange-600 transition-colors"
          >
            {tNav('deals')}
          </Link>
          <button
            type="button"
            onClick={() => setView('list')}
            className={`px-2.5 min-h-[44px] inline-flex items-center rounded-lg text-xs font-medium transition-colors ${
              view === 'list'
                ? 'bg-stone-900 text-white'
                : 'text-stone-500 hover:text-stone-700'
            }`}
          >
            {tNav('list')}
          </button>
          <button
            type="button"
            onClick={() => setView('map')}
            className={`px-2.5 min-h-[44px] inline-flex items-center rounded-lg text-xs font-medium transition-colors ${
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
      <HeroBlock restaurants={restaurants} neighborhood={selectedNeighborhood} />

      {/* Search */}
      <div className="flex items-center gap-2.5 border border-stone-200 rounded-xl px-4 py-3 mb-5">
        <span className="text-stone-400 text-sm">🔍</span>
        <input
          className="flex-1 text-sm outline-none placeholder:text-stone-400"
          placeholder={tSearch('placeholder')}
          value={search}
          onChange={(e) => resetAndSet(setSearch)(e.target.value)}
        />
        {search && (
          <button type="button" onClick={() => resetAndSet(setSearch)('')} className="text-stone-300 text-xs">✕</button>
        )}
      </div>

      {/* Cuisine pills */}
      {cuisines.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1 mb-4 scrollbar-none">
          <button
            type="button"
            onClick={() => { setSelectedCuisine(null); setVisibleCount(PAGE_SIZE) }}
            className={`shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              !selectedCuisine ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
            }`}
          >
            {tFilters('all')}
          </button>
          {cuisines.map((c) => (
            <button
              type="button"
              key={c}
              onClick={() => { setSelectedCuisine(selectedCuisine === c ? null : c); setVisibleCount(PAGE_SIZE) }}
              className={`shrink-0 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                selectedCuisine === c ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-600 hover:bg-stone-200'
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      )}

      {/* Feed header: neighborhood filter + sort */}
      <FeedHeader
        neighborhood={selectedNeighborhood}
        sortBy={sortBy}
        onSortChange={resetAndSet(setSortBy)}
        onNeighborhoodClick={() => setNeighborhoodSheetOpen(true)}
      />

      {view === 'map' ? (
        <Suspense fallback={<div className="rounded-xl border border-stone-200 bg-stone-50 animate-pulse h-[calc(100vh-240px)]" />}>
          <MapView
            restaurants={filtered}
            height="calc(100vh - 240px)"
          />
        </Suspense>
      ) : (
        <>
          {/* Near you */}
          {nearYou.length > 0 && (
            <>
              <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-3">
                {tResults('popular')}
              </p>
              <div className="mb-6">
                {nearYou.map((r, i) => {
                  return (
                    <RestaurantCard
                      key={r.id}
                      restaurant={r}
                      href={`/restaurant/${r.id}`}
                      isLast={i === nearYou.length - 1}
                      priority={false}
                      directBadge={
                        r.direct_url_type === 'ordering'
                          ? tCard('direct_cta_ordering')
                          : r.direct_url_type === 'menu'
                            ? tCard('direct_cta_menu')
                            : r.direct_url_type === 'website'
                              ? tCard('direct_cta_website')
                              : r.direct_url_type === 'phone'
                                ? tCard('direct_cta_phone')
                                : tDirect('badge')
                      }
                    />
                  )
                })}
              </div>
            </>
          )}

          {/* List label */}
          <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-3">
            {hasFilter || nearYou.length > 0 ? tResults('count', { count: filtered.length }) : tResults('popular')}
          </p>

          {/* Restaurant list */}
          <div>
            {filtered.slice(0, visibleCount).map((r, i) => {
              return (
                <RestaurantCard
                  key={r.id}
                  restaurant={r}
                  href={`/restaurant/${r.id}`}
                  isLast={i === Math.min(visibleCount, filtered.length) - 1}
                  priority={i < 3}
                  directBadge={
                    r.direct_url_type === 'ordering'
                      ? tCard('direct_cta_ordering')
                      : r.direct_url_type === 'menu'
                        ? tCard('direct_cta_menu')
                        : r.direct_url_type === 'website'
                          ? tCard('direct_cta_website')
                          : r.direct_url_type === 'phone'
                            ? tCard('direct_cta_phone')
                            : tDirect('badge')
                  }
                />
              )
            })}
            {filtered.length === 0 && (
              <div className="flex flex-col items-center gap-3 py-16 bg-[#EDEDEA] rounded-2xl">
                <p className="text-sm font-medium text-[#1A1A1A] text-center px-6">
                  {search ? tResults('none_query', { query: search }) : tResults('none')}
                </p>
                {hasFilter && (
                  <button
                    type="button"
                    onClick={() => {
                      resetAndSet(setSearch)('')
                      resetAndSet(setSelectedNeighborhood)(null)
                    }}
                    className="text-sm text-[#2E86D8] font-medium"
                  >
                    {tResults('clear_search')}
                  </button>
                )}
              </div>
            )}
            {visibleCount < filtered.length && (
              <button
                type="button"
                onClick={() => setVisibleCount((n) => n + PAGE_SIZE)}
                className="w-full py-3 mt-2 text-sm font-medium text-stone-500 hover:text-stone-800 border border-stone-200 rounded-xl hover:border-stone-400 transition-colors"
              >
                {tResults('load_more', { next: Math.min(PAGE_SIZE, filtered.length - visibleCount), remaining: filtered.length - visibleCount })}
              </button>
            )}
          </div>

          {/* Coverage footer */}
          <p className="text-xs text-stone-400 text-center py-4">
            {tFeed('coverageFooter', { count: restaurants.length })}
          </p>

          {/* Footer disclaimer */}
          <p
            className="text-[11px] text-stone-400 leading-relaxed text-center mt-8 mb-6 [&_b]:font-semibold [&_b]:text-stone-600"
            dangerouslySetInnerHTML={{ __html: tFooter.raw('disclaimer') }}
          />
        </>
      )}

      {/* Neighborhood bottom sheet */}
      {neighborhoodSheetOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/30 backdrop-blur-sm flex flex-col justify-end"
          onClick={() => setNeighborhoodSheetOpen(false)}
        >
          <div
            className="bg-white rounded-t-2xl max-h-[60vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-[#EDEDEA] sticky top-0 bg-white">
              <span className="font-semibold text-sm text-[#1A1A1A]">{tSort('filter_by_area')}</span>
              <button
                type="button"
                onClick={() => setNeighborhoodSheetOpen(false)}
                className="text-[#888780] text-sm px-1"
              >
                ✕
              </button>
            </div>
            <div>
              <button
                type="button"
                className="w-full flex items-center justify-between px-5 py-3 border-b border-[#EDEDEA] text-left"
                onClick={() => { resetAndSet(setSelectedNeighborhood)(null); setNeighborhoodSheetOpen(false) }}
              >
                <span className={`text-sm ${!selectedNeighborhood ? 'font-semibold text-[#1A1A1A]' : 'text-[#888780]'}`}>
                  {tSort('all_areas_option')}
                </span>
                <span className="text-xs text-[#888780]">{restaurants.length}</span>
              </button>
              {neighborhoods.map(({ name, count }) => (
                <button
                  type="button"
                  key={name}
                  className="w-full flex items-center justify-between px-5 py-3 border-b border-[#EDEDEA] text-left"
                  onClick={() => { resetAndSet(setSelectedNeighborhood)(name); setNeighborhoodSheetOpen(false) }}
                >
                  <span className={`text-sm ${selectedNeighborhood === name ? 'font-semibold text-[#1A1A1A]' : 'text-[#888780]'}`}>
                    {name}
                  </span>
                  <span className="text-xs text-[#888780]">{count}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
