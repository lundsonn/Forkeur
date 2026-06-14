'use client'
import { useState, useMemo, useEffect, Suspense } from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import type { RestaurantSummary } from '@/lib/queries'
import RestaurantCard from './RestaurantCard'
import { useTranslations } from 'next-intl'
import LangToggle from './LangToggle'
import { getOpenStatus } from '@/lib/hours'

const MapView = dynamic(() => import('./MapView'), {
  ssr: false,
  loading: () => <div className="rounded-xl border border-stone-200 bg-stone-50 animate-pulse h-[calc(100vh-240px)]" />,
})

type SortBy = 'best' | 'cheapest' | 'fastest'

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
  const [sortBy, setSortBy] = useState<SortBy>('best')
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
  const tHero = useTranslations('hero')
  const tSearch = useTranslations('search')
  const tFilters = useTranslations('filters')
  const tResults = useTranslations('results')
  const tDirect = useTranslations('direct')
  const tCard = useTranslations('card')
  const tSort = useTranslations('sort')
  const tOwners = useTranslations('owners')
  const tHowItWorks = useTranslations('howItWorks')
  const tFooter = useTranslations('footer')

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

  const metrics = useMemo(() => {
    const map = new Map<string, { minFee: number | null; minEta: number | null; platformCount: number; savings: number; maxFee: number | null }>()
    for (const r of restaurants) {
      const available = r.listings.filter((l) => l.delivery_fee_cents !== null)
      const fees = available.map((l) => l.delivery_fee_cents!)
      const etas = r.listings.map((l) => l.eta_min).filter((e): e is number => e !== null)
      const minFee = fees.length > 0 ? Math.min(...fees) : null
      const maxFee = fees.length > 1 ? Math.max(...fees) : null
      const minEta = etas.length > 0 ? Math.min(...etas) : null
      const savings = maxFee !== null && minFee !== null ? maxFee - minFee : 0
      map.set(r.id, { minFee, minEta, platformCount: available.length, savings, maxFee })
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

    let result = base
    if (sortBy !== 'best') {
      result = [...base].sort((a, b) => {
        const ma = metrics.get(a.id)!
        const mb = metrics.get(b.id)!
        if (sortBy === 'cheapest') {
          if (ma.minFee === null && mb.minFee === null) return 0
          if (ma.minFee === null) return 1
          if (mb.minFee === null) return -1
          return ma.minFee - mb.minFee
        }
        // fastest
        if (ma.minEta === null && mb.minEta === null) return 0
        if (ma.minEta === null) return 1
        if (mb.minEta === null) return -1
        return ma.minEta - mb.minEta
      })
    }

    // Open first; within closed group sort by next opening time soonest first
    const now = new Date()
    return [...result].sort((a, b) => {
      const ca = getClosedSortKey(a, now)
      const cb = getClosedSortKey(b, now)
      if (ca.isClosed !== cb.isClosed) return ca.isClosed ? 1 : -1
      if (ca.isClosed && cb.isClosed) return ca.opensAtKey - cb.opensAtKey
      return 0
    })
  }, [restaurants, search, selectedNeighborhood, selectedCuisine, sortBy, metrics])

  const hasFilter = !!(search || selectedNeighborhood)

  const nearYou = useMemo(() => {
    if (!userCoords || hasFilter) return []
    const [ulat, ulng] = userCoords
    return restaurants
      .filter((r): r is typeof r & { lat: number; lng: number } => r.lat !== null && r.lng !== null)
      .sort((a, b) => haversineKm(ulat, ulng, a.lat, a.lng) - haversineKm(ulat, ulng, b.lat, b.lng))
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
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-green-700 bg-green-50 border border-green-200 rounded-full px-3 py-1 mb-3">
        <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse shrink-0" />
        {tHero('live_badge')}
      </span>
      <h1 className="text-[1.65rem] font-bold text-stone-900 leading-tight mb-2">
        {tHero('heading_line1')}<br />{tHero('heading_line2')}
      </h1>
      <p
        className="text-sm text-stone-500 mb-5 leading-relaxed"
        dangerouslySetInnerHTML={{ __html: tHero.raw('subtitle') }}
      />

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

      {/* How it works */}
      <div className="overflow-hidden flex items-start gap-0 mb-6">
        {([
          { num: 1, title: tHowItWorks('step1_title'), body: tHowItWorks('step1_body') },
          { num: 2, title: tHowItWorks('step2_title'), body: tHowItWorks('step2_body') },
          { num: 3, title: tHowItWorks('step3_title'), body: tHowItWorks('step3_body') },
        ] as const).map(({ num, title, body }, i, arr) => (
          <div key={num} className="flex-1 flex flex-col items-center text-center relative">
            <div className="w-7 h-7 rounded-full bg-stone-900 text-white text-xs font-bold flex items-center justify-center mb-1.5 z-10">
              {num}
            </div>
            {i < arr.length - 1 && (
              <div className="absolute top-3.5 left-1/2 w-full h-px bg-stone-200" />
            )}
            <p className="text-xs font-semibold text-stone-800">{title}</p>
            <p className="text-[11px] text-stone-400 mt-0.5 leading-tight">{body}</p>
          </div>
        ))}
      </div>

      {/* Toolbar: area filter + sort */}
      <div className="flex items-center justify-between py-2 mb-1">
        <div className="flex items-center">
          {selectedNeighborhood ? (
            <>
              <button
                type="button"
                onClick={() => setNeighborhoodSheetOpen(true)}
                className="flex items-center rounded-l-full border border-r-0 border-[#1A1A1A] bg-white px-3 min-h-[44px] text-xs font-medium text-[#1A1A1A]"
              >
                {selectedNeighborhood}
              </button>
              <button
                type="button"
                onClick={() => setSelectedNeighborhood(null)}
                className="flex items-center rounded-r-full border border-[#1A1A1A] bg-white px-2 min-h-[44px] text-xs text-[#888780]"
              >
                ✕
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setNeighborhoodSheetOpen(true)}
              className="flex items-center gap-1 rounded-full bg-[#EDEDEA] px-3 min-h-[44px] text-xs font-medium text-[#888780]"
            >
              {tSort('all_areas')}
            </button>
          )}
        </div>

        {/* Sort pills */}
        <div className="flex gap-3">
          {(['best', 'cheapest', 'fastest'] as SortBy[]).map((s) => (
            <button
              type="button"
              key={s}
              onClick={() => resetAndSet(setSortBy)(s)}
              className={`min-[360px]:text-sm text-xs min-h-[44px] inline-flex items-end pb-1 transition-colors ${
                sortBy === s
                  ? 'font-medium text-[#1A1A1A] border-b-2 border-[#1A1A1A]'
                  : 'text-[#888780]'
              }`}
            >
              {tSort(s)}
            </button>
          ))}
        </div>
      </div>

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
                  const m = metrics.get(r.id)
                  return (
                    <RestaurantCard
                      key={r.id}
                      restaurant={r}
                      href={`/restaurant/${r.id}`}
                      isLast={i === nearYou.length - 1}
                      maxFee={m?.maxFee}
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
              const m = metrics.get(r.id)
              return (
                <RestaurantCard
                  key={r.id}
                  restaurant={r}
                  href={`/restaurant/${r.id}`}
                  isLast={i === Math.min(visibleCount, filtered.length) - 1}
                  maxFee={m?.maxFee}
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
