import { ExternalLink, List, Globe, Phone } from 'lucide-react'
import { RestaurantSummary } from '@/lib/queries'
import { centsToEuro, PLATFORM_COLORS, type Platform } from '@/lib/basket'
import { getOpenStatus } from '@/lib/hours'
import OpenStatusBadge from './OpenStatusBadge'
import PlatformLogo from './ui/PlatformLogo'

type Props = {
  restaurant: RestaurantSummary
  isLast?: boolean
  directBadge: string
  maxFee?: number | null
}

export default function RestaurantCard({ restaurant, isLast, directBadge, maxFee }: Props) {
  const { name, cuisine, listings, cheapest, order_url, direct_url_type, image_url } = restaurant

  const tiles = listings.filter((l) => l.delivery_fee_cents !== null)

  const cheapestFeeCents = cheapest
    ? listings.find(l => l.platform === cheapest.platform)?.delivery_fee_cents ?? null
    : null

  const showStrikethrough = maxFee != null && cheapestFeeCents != null && (maxFee - cheapestFeeCents) >= 50

  return (
    <div className={`py-4 ${!isLast ? 'border-b border-stone-100' : ''}`}>
      <div className="flex items-start gap-3 mb-3">
        {image_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={image_url}
            alt=""
            className="w-12 h-12 rounded-lg object-cover shrink-0 bg-stone-100"
            onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-stone-900">{name}</p>
              <p className="text-xs text-stone-400 mt-0.5">{cuisine.join(' · ')}</p>
            </div>
            <div className="flex items-center gap-2 ml-4 shrink-0 mt-0.5">
              {cheapestFeeCents != null && (
                <div className="flex items-baseline gap-1">
                  <span className="text-xs text-stone-500">
                    from <span className="font-semibold text-stone-900">€{(cheapestFeeCents / 100).toFixed(2)}</span>
                  </span>
                  {showStrikethrough && (
                    <span
                      className="text-xs text-stone-400 line-through"
                      aria-label={`€${(maxFee! / 100).toFixed(2)} on other platforms`}
                    >
                      €{(maxFee! / 100).toFixed(2)}
                    </span>
                  )}
                </div>
              )}
              <span aria-hidden="true" className="text-stone-300 text-xs">›</span>
            </div>
          </div>
        </div>
      </div>

      {order_url && direct_url_type && (() => {
        const isActionable = direct_url_type === 'ordering' || direct_url_type === 'menu'
        const pillClass = isActionable
          ? 'bg-[#D85A30] text-white hover:bg-[#c04e28]'
          : 'bg-[#888780] text-white hover:bg-[#7a7a73]'
        const Icon =
          direct_url_type === 'ordering' ? ExternalLink
          : direct_url_type === 'menu' ? List
          : direct_url_type === 'website' ? Globe
          : Phone
        return (
          <a
            href={order_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className={`inline-flex items-center gap-1.5 mb-2.5 px-2.5 py-1 rounded-full text-[11px] font-semibold transition-colors ${pillClass}`}
          >
            <Icon size={12} aria-hidden="true" />
            {directBadge}
          </a>
        )
      })()}

      {tiles.length > 0 && (
        <div className={`grid gap-1.5 ${{ 1: 'grid-cols-1', 2: 'grid-cols-2', 3: 'grid-cols-3', 4: 'grid-cols-4' }[tiles.length] ?? 'grid-cols-4'}`}>
          {tiles.map((l) => {
            const isCheapest = l.platform === cheapest?.platform
            const colors = PLATFORM_COLORS[l.platform as Platform]
            return (
              <div
                key={l.platform}
                data-testid={`fee-tile-${l.platform}`}
                data-cheapest={isCheapest ? 'true' : undefined}
                className={`rounded-lg px-2 py-2 text-center transition-opacity bg-stone-50 ${
                  isCheapest ? '' : 'opacity-40'
                } ${getOpenStatus(l.opening_hours).status === 'closed' ? 'grayscale opacity-30' : ''}`}
              >
                <div className="flex justify-center mb-0.5">
                  <PlatformLogo platform={l.platform} size={18} />
                </div>
                <p className="text-sm font-bold text-stone-900">
                  {centsToEuro(l.delivery_fee_cents)}
                </p>
                <OpenStatusBadge openingHours={l.opening_hours} isAvailable={l.is_available} />
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
