'use client'
import { useState, useMemo, useRef } from 'react'
import {
  BasketItem,
  PlatformFees,
  Platform,
  PLATFORMS,
  PLATFORM_LABELS,
  PLATFORM_COLORS,
  calculateAllTotals,
  findCheapestPlatform,
  centsToEuro,
} from '@/lib/basket'
import { MenuItemWithPrices, PlatformListing } from '@/lib/queries'
import PlatformPriceRow from './PlatformPriceRow'
import StickyOrderBar from './StickyOrderBar'

type Props = {
  menuItems: MenuItemWithPrices[]
  listings: PlatformListing[]
}

export default function BasketSimulator({ menuItems, listings }: Props) {
  const [basket, setBasket] = useState<BasketItem[]>([])
  const [compareOpen, setCompareOpen] = useState(false)

  const fees: PlatformFees = useMemo(() => {
    const result: PlatformFees = { uber_eats: null, deliveroo: null, takeaway: null }
    for (const l of listings) result[l.platform] = l.delivery_fee_cents
    return result
  }, [listings])

  const platformUrls = useMemo(() => {
    const result: Partial<Record<Platform, string>> = {}
    for (const l of listings) {
      if (l.platform_url) result[l.platform] = l.platform_url
    }
    return result
  }, [listings])

  const totals = useMemo(() => calculateAllTotals(basket, fees), [basket, fees])
  const cheapestPlatform = useMemo(() => findCheapestPlatform(totals), [totals])

  // Group menu items by category
  const grouped = useMemo(() => {
    const map = new Map<string, MenuItemWithPrices[]>()
    for (const item of menuItems) {
      const cat = item.category ?? 'Menu'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(item)
    }
    return map
  }, [menuItems])

  const swipeRef = useRef<{ startX: number; startY: number } | null>(null)

  function addItem(item: MenuItemWithPrices) {
    setBasket((prev) => {
      const existing = prev.find((b) => b.name === item.name)
      if (existing) {
        return prev.map((b) => b.name === item.name ? { ...b, qty: b.qty + 1 } : b)
      }
      return [...prev, { name: item.name, qty: 1, prices: item.prices }]
    })
  }


  const sortedByTotal = useMemo(() => {
    return PLATFORMS
      .filter((p) => fees[p] !== null)
      .map((p) => ({ platform: p, total: totals[p] }))
      .sort((a, b) => {
        if (a.total === null) return 1
        if (b.total === null) return -1
        return a.total - b.total
      })
  }, [fees, totals])

  const cheapestTotal = cheapestPlatform ? totals[cheapestPlatform] : null
  const otherTotals = sortedByTotal.filter((x) => x.platform !== cheapestPlatform && x.total !== null)
  const elsewhereMin = otherTotals.length ? Math.min(...otherTotals.map((x) => x.total!)) : null
  const elsewhereMax = otherTotals.length ? Math.max(...otherTotals.map((x) => x.total!)) : null

  // Find ETA label for a platform
  function getEta(platform: Platform): string | null {
    return listings.find((l) => l.platform === platform)?.eta_label ?? null
  }

  const basketLabel = basket
    .map((b) => (b.qty > 1 ? `${b.qty}× ${b.name}` : b.name))
    .join(' · ')

  return (
    <div className="px-5">
      {/* Selected items chip */}
      {basket.length > 0 && (
        <div
          className="flex items-center justify-between mb-4 py-2.5 border-b border-stone-100 cursor-grab active:cursor-grabbing"
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId)
            swipeRef.current = { startX: e.clientX, startY: e.clientY }
          }}
          onPointerMove={(e) => {
            if (!swipeRef.current) return
            const dy = Math.abs(e.clientY - swipeRef.current.startY)
            if (dy > 20) { swipeRef.current = null; return }
            if (e.clientX - swipeRef.current.startX < -80) {
              setBasket([])
              swipeRef.current = null
            }
          }}
          onPointerUp={() => { swipeRef.current = null }}
          onPointerCancel={() => { swipeRef.current = null }}
        >
          <p className="text-xs text-stone-500 truncate pr-3">{basketLabel}</p>
          <button
            onClick={() => setBasket([])}
            className="text-xs text-stone-400 hover:text-stone-700 shrink-0"
          >
            Clear
          </button>
        </div>
      )}

      {/* Menu items list */}
      {menuItems.length === 0 ? (
        <p className="text-sm text-stone-400 py-6">No menu data available yet.</p>
      ) : (
        <div className="mb-6">
          {Array.from(grouped.entries()).map(([category, items]) => (
            <div key={category}>
              <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase pt-4 pb-2">
                {category}
              </p>
              {items.map((item, i) => (
                <PlatformPriceRow
                  key={item.name}
                  item={item}
                  onAdd={() => addItem(item)}
                  isLast={i === items.length - 1}
                />
              ))}
            </div>
          ))}
        </div>
      )}

      {/* Recommendation section — only shown when basket has items */}
      {basket.length > 0 && cheapestPlatform && (
        <div className="border-t border-stone-100 pt-5 pb-6">
          {/* BEST RIGHT NOW */}
          <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-3">
            Best right now
          </p>
          <div className="flex items-center gap-2 mb-1">
            <span className={`w-2.5 h-2.5 rounded-full ${PLATFORM_COLORS[cheapestPlatform].dot}`} />
            <p className="text-2xl font-bold text-stone-900">{PLATFORM_LABELS[cheapestPlatform]}</p>
          </div>
          <p className="text-sm text-stone-500 mb-4">Cheapest right now.</p>

          {/* Metrics */}
          <div className="flex gap-6 mb-5">
            <div>
              <p className="text-xl font-bold text-stone-900">{centsToEuro(cheapestTotal)}</p>
              <p className="text-[10px] text-stone-400 uppercase tracking-wide mt-0.5">Total</p>
            </div>
            {getEta(cheapestPlatform) && (
              <div>
                <p className="text-xl font-bold text-stone-900">{getEta(cheapestPlatform)}</p>
                <p className="text-[10px] text-stone-400 uppercase tracking-wide mt-0.5">Delivery</p>
              </div>
            )}
            {elsewhereMax !== null && cheapestTotal !== null && elsewhereMax > cheapestTotal && (
              <div>
                <p className="text-xl font-bold text-green-600">{centsToEuro(elsewhereMax - cheapestTotal)}</p>
                <p className="text-[10px] text-stone-400 uppercase tracking-wide mt-0.5">You save</p>
              </div>
            )}
          </div>

          {/* Compare all three (collapsible) */}
          {sortedByTotal.length > 1 && (
            <>
              <div className="border-t border-stone-100 pt-4">
                <button
                  onClick={() => setCompareOpen((o) => !o)}
                  className="flex items-center justify-between w-full text-left"
                >
                  <span className="text-sm font-medium text-stone-800">Compare all three</span>
                  <span className="text-xs text-stone-400">
                    {elsewhereMin !== null && elsewhereMax !== null
                      ? elsewhereMin === elsewhereMax
                        ? `${centsToEuro(elsewhereMin)} elsewhere`
                        : `${centsToEuro(elsewhereMin)}–${centsToEuro(elsewhereMax)} elsewhere`
                      : ''}
                    {' '}{compareOpen ? '∧' : '∨'}
                  </span>
                </button>
              </div>

              {compareOpen && (
                <div className="mt-3">
                  <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-3">
                    All three · live prices
                  </p>
                  {sortedByTotal.map(({ platform, total }) => {
                    const isBest = platform === cheapestPlatform
                    const colors = PLATFORM_COLORS[platform]
                    const eta = getEta(platform)
                    return (
                      <div
                        key={platform}
                        className="flex items-center justify-between py-2.5 border-b border-stone-100 last:border-0"
                      >
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${colors.dot}`} />
                          <span className="text-sm text-stone-800">{PLATFORM_LABELS[platform]}</span>
                          {isBest && (
                            <span className="text-[10px] border border-stone-300 rounded-full px-1.5 py-0.5 text-stone-500 leading-none">
                              Best
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-4 text-right">
                          {eta && <span className="text-xs text-stone-400">{eta}</span>}
                          <span className={`text-sm font-semibold ${isBest ? 'text-stone-900' : 'text-stone-500'}`}>
                            {centsToEuro(total)}
                          </span>
                        </div>
                      </div>
                    )
                  })}
                  {cheapestPlatform && (
                    <p className="text-xs text-stone-400 mt-3">
                      Why {PLATFORM_LABELS[cheapestPlatform]}? Lowest total including all fees.
                    </p>
                  )}
                </div>
              )}
            </>
          )}

        </div>
      )}

      <StickyOrderBar
        platform={basket.length > 0 ? cheapestPlatform : null}
        total={cheapestTotal}
        platformUrl={cheapestPlatform ? platformUrls[cheapestPlatform] ?? null : null}
      />

      {basket.length > 0 && cheapestPlatform && <div className="h-24" />}
    </div>
  )
}
