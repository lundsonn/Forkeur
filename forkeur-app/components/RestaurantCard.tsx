import { RestaurantSummary } from '@/lib/queries'
import { centsToEuro, PLATFORM_COLORS, type Platform } from '@/lib/basket'

const PLATFORM_SHORT: Record<Platform, string> = {
  uber_eats: 'UE',
  deliveroo: 'DE',
  takeaway: 'TW',
  direct:    'DIR',
}

type Props = {
  restaurant: RestaurantSummary
  isLast?: boolean
  directBadge: string
}

export default function RestaurantCard({ restaurant, isLast, directBadge }: Props) {
  const { name, cuisine, listings, cheapest, order_url, direct_url_type } = restaurant

  const tiles = listings.filter((l) => l.delivery_fee_cents !== null)

  return (
    <div className={`py-4 ${!isLast ? 'border-b border-stone-100' : ''}`}>
      <div className="flex items-start justify-between mb-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-stone-900">{name}</p>
          <p className="text-xs text-stone-400 mt-0.5">{cuisine.join(' · ')}</p>
        </div>
        <span aria-hidden="true" className="text-stone-300 text-xs ml-4 shrink-0 mt-0.5">›</span>
      </div>

      {order_url && direct_url_type && (
        <a
          href={order_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1 mb-2.5 px-2.5 py-1 rounded-full bg-orange-50 border border-orange-200 text-orange-600 text-[11px] font-semibold hover:bg-orange-100 transition-colors"
        >
          {directBadge}
        </a>
      )}

      {tiles.length > 0 && (
        <div className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${tiles.length}, 1fr)` }}>
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
                }`}
              >
                <p className={`text-[10px] font-semibold uppercase tracking-wide mb-0.5 ${colors.label}`}>
                  {PLATFORM_SHORT[l.platform as Platform]}
                </p>
                <p className="text-sm font-bold text-stone-900">
                  {centsToEuro(l.delivery_fee_cents)}
                </p>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
