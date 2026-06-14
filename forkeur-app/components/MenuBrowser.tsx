'use client'
import { useState, useMemo } from 'react'
import { useTranslations } from 'next-intl'
import Image from 'next/image'
import { ArrowRight, X } from 'lucide-react'
import { PLATFORM_COLORS, type Platform } from '@/lib/basket'
import type { MenuItemWithPrices, PlatformListing } from '@/lib/queries'
import PlatformLogo from './ui/PlatformLogo'

const PLATFORM_SHORT: Record<Platform, string> = {
  uber_eats: 'UE',
  deliveroo: 'DE',
  takeaway: 'TW',
  direct: 'DR',
}

export interface BasketEntry {
  name: string
  category: string
  qty: number
}

function cheapestPlatformForItem(
  item: MenuItemWithPrices,
  listings: PlatformListing[],
): Platform | null {
  let best: Platform | null = null
  let bestPrice = Infinity
  for (const listing of listings) {
    const price = item.prices[listing.platform]
    if (price !== null && price < bestPrice) {
      bestPrice = price
      best = listing.platform
    }
  }
  return best
}

interface DishModalProps {
  item: MenuItemWithPrices
  listings: PlatformListing[]
  qty: number
  onAdd: () => void
  onRemove: () => void
  onClose: () => void
  closeLabel: string
}

function DishModal({ item, listings, qty, onAdd, onRemove, onClose, closeLabel }: DishModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-end" role="dialog" aria-modal="true">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        data-testid="dish-modal-backdrop"
      />
      <div className="relative w-full bg-white rounded-t-2xl p-4 max-h-[80vh] overflow-y-auto">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 rounded-full bg-stone-100"
          aria-label={closeLabel}
        >
          <X size={18} />
        </button>

        {item.image_url && (
          <div className="relative w-full h-48 rounded-xl overflow-hidden mb-4">
            <Image src={item.image_url} alt={item.name} fill className="object-cover" />
          </div>
        )}

        <h3 className="text-lg font-bold text-stone-900 mb-1">{item.name}</h3>
        {item.description && <p className="text-sm text-stone-500 mb-3">{item.description}</p>}

        <div className="space-y-1 mb-4">
          {listings.map((listing) => {
            const price = item.prices[listing.platform]
            if (price === null) return null
            return (
              <div key={listing.platform} className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${PLATFORM_COLORS[listing.platform].dot}`} />
                  {PLATFORM_SHORT[listing.platform]}
                </span>
                <span className="text-stone-700">€{(price / 100).toFixed(2)}</span>
              </div>
            )
          })}
        </div>

        <div className="flex items-center justify-center gap-4">
          <button
            onClick={onRemove}
            disabled={qty === 0}
            className="w-10 h-10 rounded-full bg-stone-100 flex items-center justify-center text-lg font-bold disabled:opacity-30"
            aria-label={`Remove ${item.name} from basket`}
          >
            −
          </button>
          <span className="w-8 text-center font-semibold text-stone-900">{qty}</span>
          <button
            onClick={onAdd}
            className="w-10 h-10 rounded-full bg-orange-600 text-white flex items-center justify-center text-lg font-bold"
            aria-label={`Add ${item.name} to basket`}
          >
            +
          </button>
        </div>
      </div>
    </div>
  )
}

export interface MenuBrowserProps {
  menuItems: MenuItemWithPrices[]
  listings: PlatformListing[]
  basket: BasketEntry[]
  onAdd: (name: string, category: string) => void
  onRemove: (name: string) => void
  onSwitchToCompare: () => void
}

export default function MenuBrowser({
  menuItems,
  listings,
  basket,
  onAdd,
  onRemove,
  onSwitchToCompare,
}: MenuBrowserProps) {
  const t = useTranslations('BasketSimulator')
  const [search, setSearch] = useState('')
  const [selectedItem, setSelectedItem] = useState<MenuItemWithPrices | null>(null)

  const getQty = (name: string, category: string) =>
    basket.find((i) => i.name === name && (i.category ?? 'Other') === (category ?? 'Other'))?.qty ?? 0

  const itemCount = basket.reduce((sum, i) => sum + i.qty, 0)

  const grouped = useMemo(() => {
    const q = search.toLowerCase()
    const filtered = q
      ? menuItems.filter((m) => m.name.toLowerCase().includes(q))
      : menuItems
    const map = new Map<string, MenuItemWithPrices[]>()
    for (const item of filtered) {
      const cat = item.category ?? 'Other'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(item)
    }
    return map
  }, [menuItems, search])

  const platformCols = useMemo(
    () => listings.slice().sort((a, b) => a.platform.localeCompare(b.platform)),
    [listings]
  )

  return (
    <>
      {/* Search */}
      <div className="px-4 pt-3 pb-2">
        <input
          type="search"
          placeholder={t('searchPlaceholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full border border-stone-200 rounded-lg px-3 py-2 text-sm text-stone-800 placeholder:text-stone-400 focus:outline-none focus:ring-2 focus:ring-orange-500"
        />
      </div>

      {/* Menu table */}
      <div className="px-4 pb-32">
        {[...grouped.entries()].map(([category, items]) => (
          <div key={category} className="mb-6">
            <h3 className="text-xs font-semibold uppercase tracking-widest text-stone-400 mb-2">
              {category}
            </h3>

            {/* Column headers */}
            <div className="grid gap-2 mb-1" style={{ gridTemplateColumns: `1fr repeat(${platformCols.length}, 2.5rem) 5rem` }}>
              <span />
              {platformCols.map((l) => (
                <span key={l.platform} className="text-center">
                  <PlatformLogo platform={l.platform} size={16} />
                </span>
              ))}
              <span />
            </div>

            {items.map((item) => {
              const qty = getQty(item.name, item.category ?? 'Other')
              const cheapest = cheapestPlatformForItem(item, listings)
              return (
                <div
                  key={`${item.name}__${item.category ?? ''}`}
                  className="grid items-center gap-2 py-1.5 border-b border-stone-100 last:border-0"
                  style={{ gridTemplateColumns: `1fr repeat(${platformCols.length}, 2.5rem) 5rem` }}
                >
                  <button
                    onClick={() => setSelectedItem(item)}
                    className="text-left text-sm text-stone-800 truncate"
                  >
                    {item.name}
                  </button>

                  {platformCols.map((l) => {
                    const price = item.prices[l.platform]
                    const isCheapest = cheapest === l.platform
                    return (
                      <span
                        key={l.platform}
                        className={`text-center text-xs ${isCheapest ? 'text-green-600 font-semibold' : 'text-stone-500'}`}
                      >
                        {price !== null ? `€${(price / 100).toFixed(2)}` : '—'}
                      </span>
                    )
                  })}

                  <div className="flex items-center justify-end gap-1">
                    {qty > 0 && (
                      <button
                        onClick={() => onRemove(item.name)}
                        className="w-6 h-6 rounded-full bg-stone-100 flex items-center justify-center text-sm font-bold text-stone-600"
                        aria-label={`Remove ${item.name} from basket`}
                      >
                        −
                      </button>
                    )}
                    {qty > 0 && (
                      <span className="w-4 text-center text-sm font-semibold text-stone-800">
                        {qty}
                      </span>
                    )}
                    <button
                      onClick={() => onAdd(item.name, item.category ?? 'Other')}
                      className="w-6 h-6 rounded-full bg-orange-600 text-white flex items-center justify-center text-sm font-bold"
                      aria-label={`Add ${item.name} to basket`}
                    >
                      +
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        ))}
      </div>

      {/* Floating compare pill */}
      {itemCount > 0 && (
        <button
          onClick={onSwitchToCompare}
          className="fixed bottom-20 right-4 z-50 bg-orange-600 text-white px-4 py-2 rounded-full shadow-lg flex items-center gap-2 text-sm font-semibold"
          data-testid="compare-float"
        >
          {t('compareFloat', { count: itemCount })}
          <ArrowRight size={16} />
        </button>
      )}

      {/* Dish modal */}
      {selectedItem && (
        <DishModal
          item={selectedItem}
          listings={listings}
          qty={getQty(selectedItem.name, selectedItem.category ?? 'Other')}
          onAdd={() => onAdd(selectedItem.name, selectedItem.category ?? 'Other')}
          onRemove={() => onRemove(selectedItem.name)}
          onClose={() => setSelectedItem(null)}
          closeLabel={t('closeModal')}
        />
      )}
    </>
  )
}
