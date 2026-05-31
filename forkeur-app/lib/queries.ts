import { cookies } from 'next/headers'
import { createClient } from '@/utils/supabase/server'
import type { Platform } from '@/lib/basket'

export type RestaurantSummary = {
  id: string
  name: string
  cuisine: string[]
  lat: number | null
  lng: number | null
  listings: { platform: Platform; delivery_fee_cents: number | null }[]
  cheapest: {
    platform: Platform
    fee_label: string
    savings_cents: number
  } | null
}

export type PlatformListing = {
  id: string
  platform: Platform
  platform_url: string | null
  delivery_fee_cents: number | null
  delivery_fee_label: string | null
  eta_label: string | null
  rating: number | null
}

export type MenuItemWithPrices = {
  name: string
  description: string | null
  category: string | null
  image_url: string | null
  prices: Record<Platform, number | null>
}

export type RestaurantDetail = {
  id: string
  name: string
  city: string
  cuisine: string[]
  listings: PlatformListing[]
  menuItems: MenuItemWithPrices[]
}

async function getSupabase() {
  const cookieStore = await cookies()
  return createClient(cookieStore)
}

function feeCents(fee: number | null): number | null {
  return fee != null ? Math.round(fee * 100) : null
}

function feeLabel(fee: number | null): string | null {
  if (fee == null) return null
  return fee === 0 ? 'Free' : `€${fee.toFixed(2)}`
}

function etaLabel(min: number | null, max: number | null): string | null {
  if (min == null) return null
  return max != null && max !== min ? `${min}–${max} min` : `${min} min`
}

export async function getRestaurants(): Promise<{
  restaurants: RestaurantSummary[]
  cuisines: string[]
}> {
  const supabase = await getSupabase()

  const { data, error } = await supabase
    .from('restaurants')
    .select(`
      id, name, cuisine, lat, lng,
      platform_listings ( platform, delivery_fee )
    `)

  if (error) throw new Error(`getRestaurants: ${error.message}`)

  const restaurants: RestaurantSummary[] = (data ?? [])
    .map((r) => {
      const rawListings = (r.platform_listings ?? []) as {
        platform: string
        delivery_fee: number | null
      }[]

      const listings = rawListings.map((l) => ({
        platform: l.platform as Platform,
        delivery_fee_cents: feeCents(l.delivery_fee),
      }))

      const available = listings.filter((l) => l.delivery_fee_cents !== null)

      const lat = r.lat != null ? Number(r.lat) : null
      const lng = r.lng != null ? Number(r.lng) : null

      if (available.length === 0) {
        return {
          id: r.id,
          name: r.name,
          cuisine: r.cuisine ? [r.cuisine] : [],
          lat,
          lng,
          listings,
          cheapest: null,
        }
      }

      const sorted = [...available].sort(
        (a, b) => a.delivery_fee_cents! - b.delivery_fee_cents!
      )
      const cheapest = sorted[0]
      const mostExpensive = sorted[sorted.length - 1]

      return {
        id: r.id,
        name: r.name,
        cuisine: r.cuisine ? [r.cuisine] : [],
        lat,
        lng,
        listings,
        cheapest: {
          platform: cheapest.platform,
          fee_label: feeLabel(cheapest.delivery_fee_cents !== null ? cheapest.delivery_fee_cents / 100 : null) ?? '?',
          savings_cents:
            (mostExpensive.delivery_fee_cents ?? 0) -
            (cheapest.delivery_fee_cents ?? 0),
        },
      }
    })
    .sort((a, b) => (b.cheapest?.savings_cents ?? 0) - (a.cheapest?.savings_cents ?? 0))

  const cuisines = [
    ...new Set(restaurants.flatMap((r) => r.cuisine).filter(Boolean)),
  ]
    .sort()
    .slice(0, 8)

  return { restaurants, cuisines }
}

export async function getRestaurantWithListings(
  id: string
): Promise<RestaurantDetail | null> {
  const supabase = await getSupabase()

  const { data, error } = await supabase
    .from('restaurants')
    .select(`
      id, name, neighborhood, cuisine,
      platform_listings (
        id, platform, url,
        delivery_fee, eta_min, eta_max, rating,
        menu_items ( title, price, catalog_name )
      )
    `)
    .eq('id', id)
    .single()

  if (error) return null

  const listings: PlatformListing[] = (data.platform_listings ?? []).map((l: any) => ({
    id: l.id,
    platform: l.platform as Platform,
    platform_url: l.url ?? null,
    delivery_fee_cents: feeCents(l.delivery_fee),
    delivery_fee_label: feeLabel(l.delivery_fee),
    eta_label: etaLabel(l.eta_min, l.eta_max),
    rating: l.rating !== null ? parseFloat(String(l.rating)) : null,
  }))

  const itemMap = new Map<string, MenuItemWithPrices>()

  for (const listing of (data.platform_listings ?? []) as any[]) {
    const platform = listing.platform as Platform
    for (const item of listing.menu_items ?? []) {
      const key = item.title
      if (!itemMap.has(key)) {
        itemMap.set(key, {
          name: item.title,
          description: null,
          category: item.catalog_name ?? null,
          image_url: null,
          prices: { uber_eats: null, deliveroo: null, takeaway: null },
        })
      }
      itemMap.get(key)!.prices[platform] = feeCents(item.price)
    }
  }

  return {
    id: data.id,
    name: data.name,
    city: data.neighborhood ?? 'Brussels',
    cuisine: data.cuisine ? [data.cuisine] : [],
    listings,
    menuItems: Array.from(itemMap.values()),
  }
}
