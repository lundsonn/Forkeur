import { RestaurantSummary } from '@/lib/queries'
import { centsToEuro, PLATFORM_COLORS, type Platform } from '@/lib/basket'

type Props = {
  restaurant: RestaurantSummary
  isLast?: boolean
}

export default function RestaurantCard({ restaurant, isLast }: Props) {
  const { name, cuisine, listings, cheapest } = restaurant

  const sortedListings = [...listings]
    .filter((l) => l.delivery_fee_cents !== null)
    .sort((a, b) => a.delivery_fee_cents! - b.delivery_fee_cents!)

  return (
    <div className={`py-4 ${!isLast ? 'border-b border-stone-100' : ''}`}>
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-stone-900">{name}</p>
          <p className="text-xs text-stone-400 mt-0.5">{cuisine.join(' · ')}</p>
        </div>
        <span className="text-stone-300 text-xs ml-4 shrink-0 mt-0.5">›</span>
      </div>
      {sortedListings.length > 0 && (
        <div className="flex gap-3 mt-2">
          {sortedListings.map((l) => {
            const isCheapest = l.platform === cheapest?.platform
            const colors = PLATFORM_COLORS[l.platform as Platform]
            return (
              <span
                key={l.platform}
                className={`flex items-center gap-1 text-xs ${
                  isCheapest
                    ? 'font-semibold text-stone-900'
                    : 'text-stone-400'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${colors.dot}`} />
                {centsToEuro(l.delivery_fee_cents)}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}
