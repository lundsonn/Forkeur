'use client'
import React, { useState, useMemo, useEffect } from 'react'
import { useTranslations } from 'next-intl'
import Image from 'next/image'
import { ArrowRight } from 'lucide-react'
import {
  BasketItem,
  PlatformFees,
  PlatformTotals,
  Platform,
  PLATFORMS,
  PLATFORM_LABELS,
  PLATFORM_COLORS,
  calculateAllTotalsWithCoverage,
  findCheapestPlatform,
  findCheapestCompletePlatform,
  centsToEuro,
  computeDirectSavingsCents,
  computeDirectSavingsCentsFromMenu,
} from '@/lib/basket'
import { MenuItemWithPrices, PlatformListing } from '@/lib/queries'
import CompareSheet from './CompareSheet'
import PlatformLogo from './ui/PlatformLogo'

function DishModal({
  item,
  qty,
  onAdd,
  onRemove,
  onClose,
}: {
  item: MenuItemWithPrices
  qty: number
  onAdd: () => void
  onRemove: () => void
  onClose: () => void
}) {
  const tBasket = useTranslations('basket')
  const cheapest = (() => {
    let best: Platform | null = null
    let min = Infinity
    for (const p of PLATFORMS) {
      const price = item.prices[p]
      if (price !== null && price < min) { min = price; best = p }
    }
    return best
  })()

  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [])

  const platformsWithPrice = PLATFORMS.filter((p) => item.prices[p] !== null)

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center"
      onClick={onClose}
    >
      {/* backdrop */}
      <div className="absolute inset-0 bg-black/60" />

      {/* sheet */}
      <div
        className="relative w-full max-w-md max-h-[90vh] overflow-y-auto bg-white rounded-t-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* image */}
        {item.image_url ? (
          <div className="relative w-full h-56">
            <Image
              src={item.image_url}
              alt={item.name}
              fill
              className="object-cover"
            />
            <button
              onClick={onClose}
              className="absolute top-3 right-3 w-8 h-8 rounded-full bg-white/90 flex items-center justify-center text-stone-700 text-base font-bold shadow"
              aria-label="Close"
            >
              ×
            </button>
          </div>
        ) : (
          <div className="flex justify-end px-4 pt-4">
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-full bg-stone-100 flex items-center justify-center text-stone-600 text-base font-bold"
              aria-label="Close"
            >
              ×
            </button>
          </div>
        )}

        <div className="px-5 pt-4 pb-8">
          <h2 className="text-xl font-bold text-stone-900">{item.name}</h2>
          {item.description && (
            <p className="text-sm text-stone-500 mt-1 leading-relaxed">{item.description}</p>
          )}

          {platformsWithPrice.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-2">
                {tBasket('dish_prices')}
              </p>
              <div className="flex flex-col gap-1">
                {PLATFORMS.filter((p) => item.prices[p] !== null).map((p) => {
                  const price = item.prices[p]!
                  const isCheapest = p === cheapest
                  const isDirectCheapest = p === 'direct' && isCheapest
                  return (
                    <div
                      key={p}
                      className={`flex items-center justify-between px-3 py-2 rounded-xl ${
                        isCheapest ? 'bg-orange-50 border border-orange-200' : 'bg-stone-50'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${PLATFORM_COLORS[p].dot}`} />
                        <span className={`text-sm font-medium ${PLATFORM_COLORS[p].label}`}>
                          {PLATFORM_LABELS[p]}
                        </span>
                      </div>
                      <span className={`text-sm font-bold ${isDirectCheapest ? 'text-orange-500' : isCheapest ? 'text-green-600' : 'text-stone-700'}`}>
                        {centsToEuro(price)}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* qty + add */}
          <div className="mt-5 flex items-center gap-3">
            {qty > 0 && (
              <div className="flex items-center gap-2 bg-stone-100 rounded-full px-3 py-2">
                <button
                  onClick={onRemove}
                  className="w-6 h-6 flex items-center justify-center text-stone-600 text-lg leading-none"
                  aria-label="Remove one"
                >−</button>
                <span className="text-sm font-bold text-stone-900 min-w-[16px] text-center">{qty}</span>
                <button
                  onClick={onAdd}
                  className="w-6 h-6 flex items-center justify-center text-stone-700 text-lg leading-none"
                  aria-label="Add one"
                >+</button>
              </div>
            )}
            <button
              onClick={() => { onAdd(); if (qty === 0) onClose() }}
              className="flex-1 py-3 rounded-xl bg-orange-500 hover:bg-orange-600 text-white font-semibold text-sm transition-colors"
            >
              {qty === 0
                ? tBasket('dish_add')
                : `${tBasket('dish_add')} (+1)`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}


function cheapestPlatformForItem(prices: Record<Platform, number | null>): Platform | null {
  let cheapest: Platform | null = null
  let min = Infinity
  for (const p of PLATFORMS) {
    const price = prices[p]
    if (price !== null && price < min) { min = price; cheapest = p }
  }
  return cheapest
}

type Props = {
  menuItems: MenuItemWithPrices[]
  listings: PlatformListing[]
  phone: string | null
  matchRate?: number
}

export default function BasketSimulator({ menuItems, listings, phone, matchRate = 1 }: Props) {
  const [basket, setBasket] = useState<BasketItem[]>([])
  const [sheetOpen, setSheetOpen] = useState(false)
  const [selectedItem, setSelectedItem] = useState<MenuItemWithPrices | null>(null)

  const tBasket = useTranslations('basket')
  const tCard = useTranslations('card')

  const fees: PlatformFees = useMemo(() => {
    const result: PlatformFees = { uber_eats: null, deliveroo: null, takeaway: null, direct: null }
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

  const tier = matchRate >= 0.7 ? 1 : matchRate >= 0.3 ? 2 : 3

  const feesTotals = useMemo<PlatformTotals>(
    () => Object.fromEntries(PLATFORMS.map((p) => [p, fees[p]])) as PlatformTotals,
    [fees]
  )

  const { totals, coverages } = useMemo(
    () => calculateAllTotalsWithCoverage(basket, fees),
    [basket, fees]
  )
  const cheapestPlatform = useMemo(
    () => findCheapestCompletePlatform(totals, coverages, basket.length > 0),
    [totals, coverages, basket.length]
  )

  // Tier 3 with basket items → compare on fees only
  const isFeesOnly = tier === 3 && basket.length > 0

  const effectiveCheapestPlatform = useMemo(
    () => isFeesOnly ? findCheapestPlatform(feesTotals) : cheapestPlatform,
    [isFeesOnly, feesTotals, cheapestPlatform]
  )

  const directSavingsCents = useMemo(
    () => computeDirectSavingsCents(basket, fees),
    [basket, fees]
  )

  /**
   * Menu-aware savings: uses item prices from menuItems to compute direct savings.
   * Applies threshold: ≥3 basket items with direct prices AND ≥50% coverage.
   * platformTotals must be in euros (float) as required by computeDirectSavingsCentsFromMenu.
   */
  const menuDirectSavingsCents = useMemo(() => {
    if (basket.length === 0) return null
    const platformTotalsEuros: Record<Platform, number | null> = {
      uber_eats: totals.uber_eats !== null ? totals.uber_eats / 100 : null,
      deliveroo: totals.deliveroo !== null ? totals.deliveroo / 100 : null,
      takeaway: totals.takeaway !== null ? totals.takeaway / 100 : null,
      direct: totals.direct !== null ? totals.direct / 100 : null,
    }
    return computeDirectSavingsCentsFromMenu(basket, menuItems, platformTotalsEuros)
  }, [basket, menuItems, totals])

  const grouped = useMemo(() => {
    const map = new Map<string, MenuItemWithPrices[]>()
    for (const item of menuItems) {
      const cat = item.category ?? 'Menu'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(item)
    }
    return map
  }, [menuItems])

  function getQty(name: string): number {
    return basket.find((b) => b.name === name)?.qty ?? 0
  }

  function addItem(item: MenuItemWithPrices) {
    setBasket((prev) => {
      const existing = prev.find((b) => b.name === item.name)
      if (existing) {
        return prev.map((b) => b.name === item.name ? { ...b, qty: b.qty + 1 } : b)
      }
      return [...prev, { name: item.name, qty: 1, prices: item.prices }]
    })
  }

  function removeItem(item: MenuItemWithPrices) {
    setBasket((prev) => {
      const existing = prev.find((b) => b.name === item.name)
      if (!existing) return prev
      if (existing.qty <= 1) return prev.filter((b) => b.name !== item.name)
      return prev.map((b) => b.name === item.name ? { ...b, qty: b.qty - 1 } : b)
    })
  }

  const itemCount = basket.reduce((sum, b) => sum + b.qty, 0)

  const cheapestTotal = cheapestPlatform ? totals[cheapestPlatform] : null

  const sortedByTotal = useMemo(() => {
    return PLATFORMS
      .filter((p) => fees[p] !== null)
      .map((p) => ({
        platform: p,
        total: totals[p],
        eta: listings.find((l) => l.platform === p)?.eta_label ?? null,
      }))
      .sort((a, b) => {
        if (a.total === null) return 1
        if (b.total === null) return -1
        return a.total - b.total
      })
  }, [fees, totals, listings])

  const effectiveSortedByTotal = useMemo(() => {
    if (!isFeesOnly) return sortedByTotal
    return PLATFORMS
      .filter((p) => fees[p] !== null)
      .map((p) => ({
        platform: p,
        total: fees[p],
        eta: listings.find((l) => l.platform === p)?.eta_label ?? null,
      }))
      .sort((a, b) => (a.total ?? Infinity) - (b.total ?? Infinity))
  }, [isFeesOnly, sortedByTotal, fees, listings])

  const effectiveCheapestTotal = isFeesOnly && effectiveCheapestPlatform !== null
    ? fees[effectiveCheapestPlatform]
    : cheapestTotal

  const otherTotals = sortedByTotal
    .filter((x) => {
      if (x.platform === cheapestPlatform || x.total === null) return false
      if (basket.length === 0) return true
      const cov = coverages[x.platform]
      return cov !== null && cov.complete
    })
    .map((x) => x.total!)
  const savingsCents =
    otherTotals.length > 0 && cheapestTotal !== null
      ? Math.max(...otherTotals) - cheapestTotal
      : null

  const effectiveOtherTotals = isFeesOnly
    ? effectiveSortedByTotal
      .filter((x) => x.platform !== effectiveCheapestPlatform && x.total !== null)
      .map((x) => x.total!)
    : otherTotals
  const effectiveSavingsCents = isFeesOnly
    ? (effectiveOtherTotals.length > 0 && effectiveCheapestTotal !== null
        ? Math.max(...effectiveOtherTotals) - effectiveCheapestTotal
        : null)
    : savingsCents

  const cheapestEta = effectiveCheapestPlatform
    ? listings.find((l) => l.platform === effectiveCheapestPlatform)?.eta_label ?? null
    : null

  return (
    <div className="px-5">
      {/* Menu items list */}
      {menuItems.length === 0 ? (
        <p className="text-sm text-stone-400 py-6">{tBasket('no_menu')}</p>
      ) : (
        <div className="mb-6 -mx-5 px-5 overflow-x-auto">
          <table className="w-full min-w-[300px]">
            <thead>
              <tr className="border-b border-stone-200">
                <th className="text-left text-[10px] font-semibold tracking-widest text-stone-400 uppercase pb-2 pr-2">{tBasket('item')}</th>
                {PLATFORMS.map((p) => (
                  <th key={p} className={`text-center pb-2 w-14`}>
                    <PlatformLogo platform={p} size={16} className="mx-auto" />
                  </th>
                ))}
                <th className="w-9 pb-2" />
              </tr>
            </thead>
            <tbody>
              {Array.from(grouped.entries()).map(([category, items]) => (
                <React.Fragment key={category}>
                  <tr>
                    <td colSpan={5} className="pt-4 pb-1 text-[10px] font-semibold tracking-widest text-stone-400 uppercase">
                      {category}
                    </td>
                  </tr>
                  {items.map((item) => {
                    const qty = getQty(item.name)
                    const cheapest = cheapestPlatformForItem(item.prices)
                    return (
                      <tr key={item.name} className="border-b border-stone-100 last:border-0">
                        <td className="py-3 pr-2 max-w-[160px]">
                          <button
                            className="flex items-center gap-2 text-left w-full"
                            onClick={() => setSelectedItem(item)}
                          >
                            {item.image_url && (
                              <Image
                                src={item.image_url}
                                alt=""
                                width={36}
                                height={36}
                                className="rounded-lg shrink-0 object-cover"
                              />
                            )}
                            <div className="min-w-0">
                              <p className={`text-sm text-stone-900 truncate ${qty > 0 ? 'font-bold' : 'font-medium'}`}>
                                {item.name}
                              </p>
                              {item.description && (
                                <p className="text-xs text-stone-400 truncate">{item.description}</p>
                              )}
                            </div>
                          </button>
                        </td>
                        {PLATFORMS.map((platform) => {
                          const price = item.prices[platform]
                          const isCheapest = platform === cheapest && price !== null
                          const isDirectCheapest = platform === 'direct' && isCheapest
                          const priceClass = isDirectCheapest
                            ? 'font-semibold text-orange-500'
                            : isCheapest
                              ? 'font-semibold text-green-600'
                              : price !== null
                                ? 'text-stone-500'
                                : 'text-stone-300'
                          return (
                            <td key={platform} className="text-center py-3 w-14">
                              <span className={`text-xs ${priceClass}`}>
                                {price !== null ? centsToEuro(price) : '—'}
                              </span>
                            </td>
                          )
                        })}
                        <td className="py-3 w-9">
                          {qty === 0 ? (
                            <button
                              onClick={() => addItem(item)}
                              className="w-7 h-7 rounded-full border border-stone-300 flex items-center justify-center text-stone-600 hover:border-stone-600 hover:text-stone-900 transition-colors text-base leading-none ml-auto"
                              aria-label={`Add ${item.name} to basket`}
                            >
                              +
                            </button>
                          ) : (
                            <div className="flex items-center gap-1 bg-stone-100 rounded-full px-2 py-0.5 ml-auto w-fit">
                              <button
                                onClick={() => removeItem(item)}
                                className="w-5 h-5 flex items-center justify-center text-stone-500 hover:text-stone-900 transition-colors text-sm leading-none"
                                aria-label={`Remove ${item.name} from basket`}
                              >
                                −
                              </button>
                              <span className="text-xs font-semibold text-stone-900 min-w-[12px] text-center">{qty}</span>
                              <button
                                onClick={() => addItem(item)}
                                className="w-5 h-5 flex items-center justify-center text-stone-700 hover:text-stone-900 transition-colors text-sm leading-none"
                                aria-label={`Add ${item.name} to basket`}
                              >
                                +
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Direct ordering savings banner (menu-aware) */}
      {menuDirectSavingsCents !== null && menuDirectSavingsCents > 0 && (
        <div
          data-testid="direct-savings-banner"
          className="mb-4 p-3.5 rounded-xl bg-orange-100 border border-orange-300"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-bold text-orange-800">
                {tBasket('direct_savings_banner', { amount: centsToEuro(menuDirectSavingsCents) })}
              </p>
              <p className="text-xs text-orange-700 mt-0.5">
                {tBasket('direct_savings_subtitle')}
              </p>
            </div>
            {listings.find(l => l.platform === 'direct')?.platform_url && (
              <a
                href={listings.find(l => l.platform === 'direct')!.platform_url!}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 px-3 py-1.5 rounded-lg bg-orange-500 text-white text-xs font-semibold hover:bg-orange-600 transition-colors"
              >
                {tBasket('direct_order_btn')}
              </a>
            )}
          </div>
        </div>
      )}

      {/* Spacer so content isn't hidden behind sticky bar */}
      {basket.length > 0 && <div className="h-20" />}

      {/* Sticky basket bar */}
      {basket.length > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-40 flex justify-center pointer-events-none px-5 pb-5">
          {effectiveCheapestPlatform && effectiveCheapestTotal !== null ? (
            <div
              className="w-full max-w-md pointer-events-auto rounded-2xl bg-green-50 border border-green-200 p-3"
              style={{ paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom, 0px))' }}
            >
              <button
                data-testid="basket-bar"
                onClick={() => setSheetOpen(true)}
                className="w-full flex items-center justify-between gap-3 text-left"
              >
                <div className="min-w-0">
                  <p className="text-[11px] text-green-700">
                    {tBasket('bottom_cheapest', { count: itemCount })}
                  </p>
                  <p className="text-sm font-bold text-stone-900">
                    {tBasket('all_in', {
                      platform: PLATFORM_LABELS[effectiveCheapestPlatform],
                      amount: centsToEuro(effectiveCheapestTotal),
                    })}
                  </p>
                </div>
                {effectiveSavingsCents !== null && effectiveSavingsCents > 0 && (
                  <p className="text-sm font-bold text-green-700 shrink-0">
                    {tCard('save', { amount: centsToEuro(effectiveSavingsCents) })}
                  </p>
                )}
              </button>
              {platformUrls[effectiveCheapestPlatform] ? (
                <a
                  href={platformUrls[effectiveCheapestPlatform]}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-2 flex items-center justify-center gap-2 w-full py-3 rounded-xl text-white font-semibold text-sm bg-[#2E86D8] hover:bg-[#2576c2] transition-colors"
                >
                  {tBasket('order_on', {
                    platform: PLATFORM_LABELS[effectiveCheapestPlatform],
                    amount: centsToEuro(effectiveCheapestTotal),
                  })}
                  <ArrowRight size={16} aria-hidden="true" />
                </a>
              ) : (
                <button
                  onClick={() => setSheetOpen(true)}
                  className="mt-2 flex items-center justify-center gap-2 w-full py-3 rounded-xl text-white font-semibold text-sm bg-[#2E86D8] hover:bg-[#2576c2] transition-colors"
                >
                  {tBasket('order_on', {
                    platform: PLATFORM_LABELS[effectiveCheapestPlatform],
                    amount: centsToEuro(effectiveCheapestTotal),
                  })}
                  <ArrowRight size={16} aria-hidden="true" />
                </button>
              )}
            </div>
          ) : (
            <button
              data-testid="basket-bar"
              onClick={() => setSheetOpen(true)}
              className="w-full max-w-md pointer-events-auto rounded-2xl p-3 flex items-center justify-between transition-transform duration-200 bg-green-50 border border-green-200"
              style={{
                paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom, 0px))',
              }}
            >
              <div>
                <p className="text-[11px] text-green-700">
                  {tBasket('items', { count: itemCount })}
                </p>
                <p className="text-sm font-bold text-stone-900">
                  {tBasket('compare_platforms')}
                </p>
              </div>
              <span className="text-lg font-bold text-green-700">↑</span>
            </button>
          )}
        </div>
      )}

      {/* Compare sheet */}
      {sheetOpen && basket.length > 0 && (
        <CompareSheet
          cheapestPlatform={effectiveCheapestPlatform}
          total={effectiveCheapestTotal}
          eta={cheapestEta}
          savingsCents={effectiveSavingsCents}
          platformUrl={effectiveCheapestPlatform ? (platformUrls[effectiveCheapestPlatform] ?? null) : null}
          sortedByTotal={effectiveSortedByTotal}
          coverages={isFeesOnly ? null : coverages}
          isFeesOnly={isFeesOnly}
          onClose={() => setSheetOpen(false)}
        />
      )}

      {/* Dish detail modal */}
      {selectedItem && (
        <DishModal
          item={selectedItem}
          qty={getQty(selectedItem.name)}
          onAdd={() => addItem(selectedItem)}
          onRemove={() => removeItem(selectedItem)}
          onClose={() => setSelectedItem(null)}
        />
      )}
    </div>
  )
}
