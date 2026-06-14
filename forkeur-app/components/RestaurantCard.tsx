'use client'
import { useState } from 'react'
import Image from 'next/image'
import { ChevronUp, ChevronDown } from 'lucide-react'
import { useTranslations } from 'next-intl'
import type { RestaurantSummary } from '@/lib/queries'
import { centsToEuro, PLATFORM_LABELS, type Platform } from '@/lib/basket'
import { savingsVsNext, effectiveTotal } from '@/lib/savings'
import PlatformLogo from './ui/PlatformLogo'
import OpenStatusBadge from './OpenStatusBadge'
import { getOpenStatus } from '@/lib/hours'

type Props = {
  restaurant: RestaurantSummary
  href: string
  isLast?: boolean
  directBadge: string
  maxFee?: number | null
  priority?: boolean
}

export default function RestaurantCard({ restaurant, href, isLast, directBadge, priority }: Props) {
  const { name, cuisine, listings, cheapest, order_url, direct_url_type, image_url } = restaurant
  const tCard = useTranslations('card')
  const [collapsed, setCollapsed] = useState(false)

  const bestListing = listings.find((l) => l.opening_hours != null) ?? listings[0] ?? null
  const openingHours = bestListing?.opening_hours ?? null
  const isAvailable = listings.some((l) => l.is_available)
  const status = getOpenStatus(openingHours)
  const isClosed = !isAvailable || status.status === 'closed'

  const tiles = listings.filter((l) => l.delivery_fee_cents !== null)
  const sortedTiles = [...tiles].sort((a, b) => {
    if (a.platform === 'direct') return -1
    if (b.platform === 'direct') return 1
    const fa = a.delivery_fee_cents ?? 0
    const fb = b.delivery_fee_cents ?? 0
    return fa - fb
  })

  const cheapestFeeCents = cheapest?.delivery_fee_cents ?? null

  return (
    <div
      data-testid="restaurant-card"
      data-id={restaurant.id}
      className={`relative py-4 cursor-pointer select-none ${!isLast ? 'border-b border-stone-100' : ''} ${isClosed ? 'opacity-60' : ''}`}
    >
      {/* Stretched link overlay — sibling, not parent, so nested CTA anchors stay valid HTML */}
      <a href={href} aria-label={name} className="absolute inset-0 z-0" />

      {/* Header */}
      <div className="relative z-10 pointer-events-none flex items-start gap-3 mb-3">
        {image_url && (
          <Image
            src={image_url}
            alt=""
            width={44}
            height={44}
            className="rounded-xl object-cover shrink-0 bg-stone-100"
            priority={priority}
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <p className="text-sm font-semibold text-stone-900 truncate">{name}</p>
            <OpenStatusBadge openingHours={openingHours} isAvailable={isAvailable} />
          </div>
          <p className="text-xs text-stone-500 truncate">{cuisine.join(' · ')}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0 mt-0.5">
          {cheapestFeeCents != null && cheapestFeeCents > 0 && (
            <span className="text-xs text-stone-500">
              from <span className="font-bold text-stone-900">{centsToEuro(cheapestFeeCents)}</span>
            </span>
          )}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setCollapsed((v) => !v) }}
            className="pointer-events-auto text-stone-300 hover:text-stone-500 min-w-[44px] min-h-[44px] flex items-center justify-center transition-colors"
            aria-label={collapsed ? 'Expand' : 'Collapse'}
          >
            {collapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
          </button>
        </div>
      </div>

      {/* Platform rows */}
      {!collapsed && sortedTiles.length > 0 && (
        <div className="relative z-10 pointer-events-none space-y-1.5 mb-3">
          {sortedTiles.map((l) => {
            const isCheapest = l.platform === cheapest?.platform

            // Winner savings label
            const winnerSavings = isCheapest && cheapest
              ? savingsVsNext(listings as Parameters<typeof savingsVsNext>[0])
              : null

            // Loser overpay amount
            const winnerListing = cheapest
              ? listings.find(x => x.platform === cheapest.platform) ?? null
              : null
            const loserDelta = !isCheapest && winnerListing !== null
              ? (() => {
                  const tileEff = effectiveTotal(l as Parameters<typeof effectiveTotal>[0])
                  const winnerEff = effectiveTotal(winnerListing as Parameters<typeof effectiveTotal>[0])
                  if (tileEff === null || winnerEff === null) return null
                  const diff = tileEff - winnerEff
                  return diff > 0 ? diff : null
                })()
              : null

            return (
              <div
                key={l.platform}
                data-testid={`fee-tile-${l.platform}`}
                data-cheapest={isCheapest ? 'true' : undefined}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-xl ${isCheapest ? 'bg-green-50' : 'bg-stone-50'}`}
              >
                <PlatformLogo platform={l.platform} size={16} />
                <span className={`text-xs flex-1 font-medium ${isCheapest ? 'text-green-700' : 'text-stone-600'}`}>
                  {PLATFORM_LABELS[l.platform as Platform]}
                </span>
                <span className="flex flex-col items-end">
                  <span className={`text-xs font-bold tabular-nums ${isCheapest ? 'text-green-700' : 'text-stone-700'}`}>
                    {centsToEuro(l.delivery_fee_cents)}
                  </span>
                  {l.min_order_cents != null && l.min_order_cents > 0 && (
                    <span className={`text-[10px] tabular-nums leading-tight ${isCheapest ? 'text-green-600' : 'text-stone-400'}`}>
                      {tCard('min_order', { amount: centsToEuro(l.min_order_cents) })}
                    </span>
                  )}
                </span>
                {isCheapest ? (
                  <div className="flex flex-col items-end gap-0.5">
                    <span className="text-[10px] font-bold bg-green-500 text-white rounded-full px-1.5 py-0.5 leading-none">
                      {tCard('cheapest_badge')}
                    </span>
                    {winnerSavings !== null && (
                      <span className="text-[10px] text-green-600 tabular-nums font-medium">
                        {`+€${(winnerSavings.cents / 100).toFixed(2)} cheaper`}
                      </span>
                    )}
                  </div>
                ) : loserDelta !== null ? (
                  <span className="text-[10px] text-red-600 tabular-nums font-medium">
                    {`+€${(loserDelta / 100).toFixed(2)} more here`}
                  </span>
                ) : null}
              </div>
            )
          })}
        </div>
      )}

      {/* Direct CTA — website/phone belong on the detail page */}
      {order_url && (direct_url_type === 'ordering' || direct_url_type === 'menu' || direct_url_type === 'website') && (
        <a
          href={order_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="relative z-10 pointer-events-auto flex items-center justify-center gap-1.5 w-full py-2.5 bg-orange-500 text-white text-sm font-semibold rounded-xl hover:bg-orange-600 active:bg-orange-700 transition-colors mb-2"
        >
          {directBadge}
        </a>
      )}

      {/* Compare all */}
      {!collapsed && sortedTiles.length > 1 && (
        <p className="relative z-10 pointer-events-none text-center text-xs text-stone-500 mt-0.5">
          {tCard('compare_all', { count: sortedTiles.length })} ›
        </p>
      )}
    </div>
  )
}
