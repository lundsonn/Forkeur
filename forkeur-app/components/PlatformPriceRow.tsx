import { PLATFORMS, PLATFORM_COLORS, type Platform, centsToEuro } from '@/lib/basket'
import type { MenuItemWithPrices } from '@/lib/queries'

const PLATFORM_SHORT: Record<Platform, string> = {
  uber_eats: 'UE',
  deliveroo: 'DE',
  takeaway: 'TW',
}

function cheapestPlatformForItem(prices: Record<Platform, number | null>): Platform | null {
  let cheapest: Platform | null = null
  let min = Infinity
  for (const platform of PLATFORMS) {
    const price = prices[platform]
    if (price !== null && price < min) {
      min = price
      cheapest = platform
    }
  }
  return cheapest
}

type Props = {
  item: MenuItemWithPrices
  qty: number
  onAdd: () => void
  onRemove: () => void
  isLast?: boolean
}

export default function PlatformPriceRow({ item, qty, onAdd, onRemove, isLast }: Props) {
  const cheapest = cheapestPlatformForItem(item.prices)

  return (
    <div className={`py-3.5 ${!isLast ? 'border-b border-stone-100' : ''}`}>
      <div className="flex justify-between items-start mb-2.5">
        <div className="min-w-0 pr-3">
          <p className={`text-sm text-stone-900 ${qty > 0 ? 'font-bold' : 'font-semibold'}`}>
            {item.name}
          </p>
          {item.description && (
            <p className="text-xs text-stone-400 mt-0.5 line-clamp-1">{item.description}</p>
          )}
        </div>

        {qty === 0 ? (
          <button
            onClick={onAdd}
            className="shrink-0 w-7 h-7 rounded-full border border-stone-300 flex items-center justify-center text-stone-600 hover:border-stone-600 hover:text-stone-900 transition-colors text-base leading-none"
            aria-label={`Add ${item.name} to basket`}
          >
            +
          </button>
        ) : (
          <div className="flex items-center gap-1 bg-stone-100 rounded-full px-2 py-0.5">
            <button
              onClick={onRemove}
              className="w-5 h-5 flex items-center justify-center text-stone-500 hover:text-stone-900 transition-colors text-sm leading-none"
              aria-label={`Remove ${item.name} from basket`}
            >
              −
            </button>
            <span className="text-xs font-semibold text-stone-900 min-w-[12px] text-center">
              {qty}
            </span>
            <button
              onClick={onAdd}
              className="w-5 h-5 flex items-center justify-center text-stone-700 hover:text-stone-900 transition-colors text-sm leading-none"
              aria-label={`Add ${item.name} to basket`}
            >
              +
            </button>
          </div>
        )}
      </div>
      <div className="flex gap-2 flex-wrap">
        {PLATFORMS.map((platform) => {
          const price = item.prices[platform]
          const isCheapest = platform === cheapest && price !== null
          const colors = PLATFORM_COLORS[platform]
          return (
            <div key={platform} className="flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${colors.dot}`} />
              <span
                className={`text-xs ${isCheapest ? 'font-semibold text-green-600' : 'text-stone-500'}`}
              >
                {PLATFORM_SHORT[platform]} {centsToEuro(price)}
                {isCheapest && price !== null ? ' ✓' : ''}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
