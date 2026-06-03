'use client'
import React, { useState, useMemo } from 'react'
import { useTranslations } from 'next-intl'
import Image from 'next/image'
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
  computeDirectSavingsCents,
} from '@/lib/basket'
import { MenuItemWithPrices, PlatformListing } from '@/lib/queries'
import CompareSheet from './CompareSheet'

const PLATFORM_SHORT: Record<Platform, string> = {
  uber_eats: 'UE',
  deliveroo: 'DE',
  takeaway: 'TW',
  direct:    'DIR',
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
}

export default function BasketSimulator({ menuItems, listings, phone }: Props) {
  const [basket, setBasket] = useState<BasketItem[]>([])
  const [sheetOpen, setSheetOpen] = useState(false)

  const tBasket = useTranslations('basket')

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

  /**
   * Fee-savings signal: direct listing exists but has no menu items scraped yet.
   * Shows ~€X.XX de frais de plateforme économisés using cheapest non-direct fee.
   */
  const directFeeSavingsCents = useMemo<number | null>(() => {
    const hasDirectListing = listings.some((l) => l.platform === 'direct')
    if (!hasDirectListing) return null

    const hasDirectMenuItems = menuItems.some((item) => item.prices.direct !== null)
    if (hasDirectMenuItems) return null

    // Find cheapest delivery_fee_cents among non-direct platforms
    let cheapestFee: number | null = null
    for (const l of listings) {
      if (l.platform === 'direct') continue
      if (l.delivery_fee_cents === null) continue
      if (cheapestFee === null || l.delivery_fee_cents < cheapestFee) {
        cheapestFee = l.delivery_fee_cents
      }
    }
    return cheapestFee
  }, [listings, menuItems])

  const totals = useMemo(() => calculateAllTotals(basket, fees), [basket, fees])
  const cheapestPlatform = useMemo(() => findCheapestPlatform(totals), [totals])

  const directSavingsCents = useMemo(
    () => computeDirectSavingsCents(basket, fees),
    [basket, fees]
  )

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

  const subtotalCents = useMemo(() => {
    if (!cheapestPlatform || cheapestTotal === null) return 0
    return cheapestTotal - (fees[cheapestPlatform] ?? 0)
  }, [cheapestPlatform, cheapestTotal, fees])

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

  const otherTotals = sortedByTotal
    .filter((x) => x.platform !== cheapestPlatform && x.total !== null)
    .map((x) => x.total!)
  const savingsCents =
    otherTotals.length > 0 && cheapestTotal !== null
      ? Math.max(...otherTotals) - cheapestTotal
      : null

  const cheapestEta = cheapestPlatform
    ? listings.find((l) => l.platform === cheapestPlatform)?.eta_label ?? null
    : null

  // Build per-platform fee info for the header bar
  const platformFeeRows = listings.map((l) => {
    const colors = PLATFORM_COLORS[l.platform]
    const isDirectSavings = l.platform === 'direct' && directFeeSavingsCents !== null
    const feeText = isDirectSavings
      ? null
      : l.delivery_fee_cents === null
        ? null
        : l.delivery_fee_cents === 0
          ? tBasket('free_delivery')
          : tBasket('delivery', { fee: centsToEuro(l.delivery_fee_cents) })
    const minText = isDirectSavings ? null : (l.min_order_label ?? null)
    const isPhone = l.platform === 'direct' && !l.platform_url
    const href = l.platform === 'direct' && phone
      ? `tel:${phone}`
      : l.platform_url ?? null
    return {
      platform: l.platform,
      colors,
      feeText,
      minText,
      href,
      isPhone,
      label: PLATFORM_LABELS[l.platform],
      isDirectSavings,
    }
  })

  return (
    <div className="px-5">
      {/* Platform delivery fee bar */}
      {platformFeeRows.length > 0 && (
        <div className="mb-5 -mx-5 px-5 py-3 bg-stone-50 border-y border-stone-100 flex flex-wrap gap-x-5 gap-y-2">
          {platformFeeRows.map(({ platform, colors, feeText, minText, href, label, isDirectSavings }) => (
            <div key={platform} className="flex items-start gap-1.5 min-w-[120px]">
              <span className={`mt-0.5 w-2 h-2 rounded-full shrink-0 ${colors.dot}`} />
              <div>
                <p className={`text-xs font-semibold ${colors.label}`}>
                  {href ? (
                    <a href={href} target={platform !== 'direct' ? '_blank' : undefined}
                       rel="noopener noreferrer" className="underline underline-offset-2">
                      {label}
                    </a>
                  ) : label}
                </p>
                {feeText && <p className="text-[11px] text-stone-500">{feeText}</p>}
                {minText && <p className="text-[11px] text-stone-400">{minText}</p>}
                {platform === 'direct' && phone && !href?.startsWith('http') && (
                  <p className="text-[11px] text-stone-500">{phone}</p>
                )}
                {isDirectSavings && directFeeSavingsCents !== null && (
                  <div data-testid="direct-fee-savings">
                    <p className="text-[11px] font-semibold text-orange-600">
                      {tBasket('direct_savings', { fee: centsToEuro(directFeeSavingsCents) })}
                    </p>
                    <p className="text-[11px] text-stone-500 mt-0.5">
                      {href ? (
                        <a href={href} target={platform !== 'direct' ? '_blank' : undefined}
                           rel="noopener noreferrer" className="underline underline-offset-2">
                          {tBasket('direct_order_cta')}
                        </a>
                      ) : tBasket('direct_order_cta')}
                    </p>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

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
                  <th key={p} className={`text-center text-[10px] font-semibold tracking-widest uppercase pb-2 w-14 ${PLATFORM_COLORS[p].label}`}>
                    {PLATFORM_SHORT[p]}
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
                          <div className="flex items-center gap-2">
                            {item.image_url && (
                              <Image
                                src={item.image_url}
                                alt=""
                                width={32}
                                height={32}
                                className="rounded shrink-0 object-cover"
                                unoptimized
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
                          </div>
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

      {/* Direct ordering savings banner */}
      {directSavingsCents !== null && basket.length > 0 && (
        <div className="mb-4 p-3.5 rounded-xl bg-orange-50 border border-orange-200">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-bold text-orange-700">
                {tBasket('direct_savings_banner', { amount: centsToEuro(directSavingsCents) })}
              </p>
              <p className="text-xs text-orange-500 mt-0.5">
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
      {basket.length > 0 && cheapestPlatform && cheapestTotal !== null && (
        <div className="fixed bottom-0 left-0 right-0 z-40 flex justify-center pointer-events-none px-5 pb-5">
          <button
            data-testid="basket-bar"
            onClick={() => setSheetOpen(true)}
            className="w-full max-w-md pointer-events-auto bg-stone-900 text-white rounded-2xl px-5 py-3.5 flex items-center justify-between transition-transform duration-200"
            style={{ paddingBottom: 'calc(0.875rem + env(safe-area-inset-bottom, 0px))' }}
          >
            <div>
              <p className="text-xs text-stone-400">
                {tBasket('items', { count: itemCount })} · {centsToEuro(subtotalCents)}
              </p>
              <p className="text-sm font-bold">
                {tBasket('best')}{' '}
                <span className={PLATFORM_COLORS[cheapestPlatform].label}>
                  {PLATFORM_LABELS[cheapestPlatform]}
                </span>{' '}
                {centsToEuro(cheapestTotal)}
              </p>
            </div>
            <span className={`text-lg font-bold ${PLATFORM_COLORS[cheapestPlatform].label}`}>
              ↑
            </span>
          </button>
        </div>
      )}

      {/* Compare sheet */}
      {sheetOpen && cheapestPlatform && cheapestTotal !== null && (
        <CompareSheet
          cheapestPlatform={cheapestPlatform}
          total={cheapestTotal}
          eta={cheapestEta}
          savingsCents={savingsCents}
          platformUrl={platformUrls[cheapestPlatform] ?? null}
          sortedByTotal={sortedByTotal}
          onClose={() => setSheetOpen(false)}
        />
      )}
    </div>
  )
}
