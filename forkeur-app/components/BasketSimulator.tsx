'use client'
import { useState, useMemo, useEffect, useRef } from 'react'
import { useTranslations } from 'next-intl'
import { useSearchParams, useRouter } from 'next/navigation'
import {
  BasketItem,
  PlatformFees,
  PlatformTotals,
  Platform,
  PLATFORMS,
  calculateAllTotalsWithCoverage,
  findCheapestPlatform,
  findCheapestCompletePlatform,
  computeDirectSavingsCentsFromMenu,
} from '@/lib/basket'
import { MenuItemWithPrices, PlatformListing } from '@/lib/queries'
import MenuBrowser, { type BasketEntry } from './MenuBrowser'
import CompareDecision from './CompareDecision'

type Props = {
  menuItems: MenuItemWithPrices[]
  listings: PlatformListing[]
  phone: string | null
  phoneConfidence?: string | null
  orderChannel?: string | null
  matchRate?: number
  restaurantId?: string
}

export default function BasketSimulator({
  menuItems,
  listings,
  phone,
  orderChannel,
  matchRate = 1,
  restaurantId,
}: Props) {
  const t = useTranslations('BasketSimulator')
  const tBasket = useTranslations('basket')

  const [basket, setBasket] = useState<BasketItem[]>([])
  const [activeTab, setActiveTab] = useState<'menu' | 'compare'>('menu')
  const [showRestoreBanner, setShowRestoreBanner] = useState(false)
  const [savedBasket, setSavedBasket] = useState<BasketItem[] | null>(null)

  const initializedRef = useRef(false)
  const skipNextUrlSyncRef = useRef(false)

  const searchParams = useSearchParams()
  const router = useRouter()

  // On mount: parse ?basket= param and/or show localStorage restore banner
  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true

    const lsKey = restaurantId ? `forkeur-basket-${restaurantId}` : null

    const urlParam = searchParams.get('basket')
    let urlItems: BasketItem[] = []
    if (urlParam) {
      for (const part of urlParam.split(',')) {
        const colonIdx = part.lastIndexOf(':')
        if (colonIdx === -1) continue
        const name = decodeURIComponent(part.slice(0, colonIdx))
        const qty = parseInt(part.slice(colonIdx + 1), 10)
        if (!name || isNaN(qty) || qty < 1) continue
        const found = menuItems.find((m) => m.name === name)
        if (found) urlItems.push({ name: found.name, qty, prices: found.prices })
      }
    }

    if (urlItems.length > 0) {
      skipNextUrlSyncRef.current = true
      setBasket(urlItems)
      return
    }

    if (lsKey) {
      try {
        const raw = localStorage.getItem(lsKey)
        if (raw) {
          const parsed: BasketItem[] = JSON.parse(raw)
          if (Array.isArray(parsed) && parsed.length > 0) {
            setSavedBasket(parsed)
            setShowRestoreBanner(true)
          }
        }
      } catch {
        // ignore malformed localStorage
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Auto-save basket to localStorage on every non-empty change
  useEffect(() => {
    if (!restaurantId || basket.length === 0) return
    try {
      localStorage.setItem(`forkeur-basket-${restaurantId}`, JSON.stringify(basket))
    } catch {
      // ignore storage errors
    }
  }, [basket, restaurantId])

  // Sync basket to URL
  useEffect(() => {
    if (!initializedRef.current) return
    if (skipNextUrlSyncRef.current) {
      skipNextUrlSyncRef.current = false
      return
    }
    if (basket.length === 0) {
      router.replace(window.location.pathname, { scroll: false })
    } else {
      const encoded = basket
        .map((b) => encodeURIComponent(b.name) + ':' + b.qty)
        .join(',')
      router.replace(window.location.pathname + '?basket=' + encoded, { scroll: false })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basket])

  const fees: PlatformFees = useMemo(() => {
    const result: PlatformFees = { uber_eats: null, deliveroo: null, takeaway: null, direct: null }
    for (const l of listings) result[l.platform] = l.delivery_fee_cents
    return result
  }, [listings])

  const tier = matchRate >= 0.7 ? 1 : matchRate >= 0.3 ? 2 : 3

  const feesTotals = useMemo<PlatformTotals>(
    () => Object.fromEntries(PLATFORMS.map((p) => [p, fees[p]])) as PlatformTotals,
    [fees],
  )

  const { totals, coverages } = useMemo(
    () => calculateAllTotalsWithCoverage(basket, fees),
    [basket, fees],
  )

  const cheapestPlatform = useMemo(
    () => findCheapestCompletePlatform(totals, coverages, basket.length > 0),
    [totals, coverages, basket.length],
  )

  const isFeesOnly = tier === 3 && basket.length > 0

  const effectiveCheapestPlatform = useMemo(
    () => (isFeesOnly ? findCheapestPlatform(feesTotals) : cheapestPlatform),
    [isFeesOnly, feesTotals, cheapestPlatform],
  )

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

  const itemCount = basket.reduce((sum, b) => sum + b.qty, 0)

  const items: BasketEntry[] = basket.map((b) => ({
    name: b.name,
    category: menuItems.find((m) => m.name === b.name)?.category ?? '',
    qty: b.qty,
  }))

  function addItem(name: string, category: string) {
    const found = menuItems.find((m) => m.name === name)
    if (!found) return
    void category
    setBasket((prev) => {
      const existing = prev.find((b) => b.name === name)
      if (existing) return prev.map((b) => b.name === name ? { ...b, qty: b.qty + 1 } : b)
      return [...prev, { name, qty: 1, prices: found.prices }]
    })
  }

  function removeItem(name: string) {
    setBasket((prev) => {
      const existing = prev.find((b) => b.name === name)
      if (!existing) return prev
      if (existing.qty <= 1) return prev.filter((b) => b.name !== name)
      return prev.map((b) => b.name === name ? { ...b, qty: b.qty - 1 } : b)
    })
  }

  function handleRestore() {
    if (savedBasket) setBasket(savedBasket)
    setShowRestoreBanner(false)
  }

  function handleDismissRestore() {
    setShowRestoreBanner(false)
  }

  return (
    <div className="relative">
      {showRestoreBanner && savedBasket && (
        <div className="bg-stone-100 border-b border-stone-200 px-4 py-2 flex items-center justify-between text-sm">
          <span className="text-stone-700">{tBasket('restore_usual')}</span>
          <div className="flex gap-2">
            <button onClick={handleRestore} className="text-orange-600 font-medium">
              {tBasket('restore_btn')}
            </button>
            <button onClick={handleDismissRestore} className="text-stone-400">
              {tBasket('restore_dismiss')}
            </button>
          </div>
        </div>
      )}

      <div className="sticky top-0 z-10 flex border-b border-stone-200 bg-white">
        <button
          onClick={() => setActiveTab('menu')}
          className={`flex-1 py-3 text-sm font-medium transition-colors ${
            activeTab === 'menu'
              ? 'border-b-2 border-orange-600 text-orange-600'
              : 'text-stone-500'
          }`}
          data-testid="tab-menu"
        >
          {t('tab.menu')}
        </button>
        <button
          onClick={() => setActiveTab('compare')}
          className={`flex-1 py-3 text-sm font-medium transition-colors flex items-center justify-center gap-1.5 ${
            activeTab === 'compare'
              ? 'border-b-2 border-orange-600 text-orange-600'
              : 'text-stone-500'
          }`}
          data-testid="tab-compare"
        >
          {t('tab.compare')}
          {itemCount > 0 && (
            <span
              className="bg-orange-600 text-white text-xs font-bold rounded-full w-5 h-5 flex items-center justify-center"
              data-testid="compare-badge"
            >
              {itemCount}
            </span>
          )}
        </button>
      </div>

      {activeTab === 'menu' ? (
        <MenuBrowser
          menuItems={menuItems}
          listings={listings}
          basket={items}
          onAdd={addItem}
          onRemove={removeItem}
          onSwitchToCompare={() => setActiveTab('compare')}
        />
      ) : (
        <CompareDecision
          basket={items}
          listings={listings}
          menuItems={menuItems}
          totals={totals}
          coverages={coverages}
          cheapestPlatform={effectiveCheapestPlatform}
          menuDirectSavingsCents={menuDirectSavingsCents}
          phone={phone ?? undefined}
          orderChannel={orderChannel ?? undefined}
          isFeesOnly={isFeesOnly}
        />
      )}
    </div>
  )
}
