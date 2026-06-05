import { cache } from 'react'
import { cookies } from 'next/headers'
import { createClient } from '@/utils/supabase/server'
import type { Platform } from '@/lib/basket'
import type { DealItem, DealType } from '@/lib/deals'
import { normalizeTitle } from '@/lib/normalize-title'
export { normalizeTitle }

const STALE_THRESHOLD_MS = 72 * 60 * 60 * 1000

export type RestaurantSummary = {
  id: string
  name: string
  neighborhood: string | null
  cuisine: string[]
  lat: number | null
  lng: number | null
  order_url: string | null
  image_url: string | null
  rating: number | null
  direct_url_type: string | null
  is_chain: boolean
  listings: { platform: Platform; delivery_fee_cents: number | null; eta_min: number | null; is_available: boolean; opening_hours: OpeningHours | null }[]
  cheapest: {
    platform: Platform
    fee_label: string
    savings_cents: number
    delivery_fee_cents: number | null
  } | null
}

export type PromoItem = {
  promo_type: string
  label: string
  value: number | null
}

export type OpeningHours = Record<string, [string, string]> // {mon: ["11:00","22:30"], ...}

export type PlatformListing = {
  id: string
  platform: Platform
  platform_url: string | null
  url_type: string | null
  delivery_fee_cents: number | null
  delivery_fee_label: string | null
  min_order_cents: number | null
  min_order_label: string | null
  eta_label: string | null
  rating: number | null
  last_scraped_at: string | null
  is_available: boolean
  opening_hours: OpeningHours | null
  promotions: PromoItem[]
}

export type MenuItemWithPrices = {
  name: string
  description: string | null
  category: string | null
  image_url: string | null
  prices: Record<Platform, number | null>
  platformTitles?: Record<Platform, string | null>
}

export type RestaurantDetail = {
  id: string
  name: string
  city: string
  cuisine: string[]
  phone: string | null
  order_url: string | null
  direct_url_type: string | null
  image_url: string | null
  listings: PlatformListing[]
  menuItems: MenuItemWithPrices[]
  matchRate: number
}

// Raw Supabase row types — no generated DB types in this project
type RawListingShort = {
  platform: string
  delivery_fee: number | null
  eta_min: number | null
  rating: number | null
  url_type: string | null
  is_available: boolean | null
  opening_hours: OpeningHours | null
  last_scraped_at: string | null
}

type RawRestaurantRow = {
  id: string
  name: string
  cuisine: string | null
  neighborhood: string | null
  lat: number | null
  lng: number | null
  order_url: string | null
  image_url: string | null
  is_chain: boolean
  platform_listings: RawListingShort[]
}

type RawPromoRow = {
  id: string
  promo_type: string
  label: string
  value: number | null
  min_order: number | null
  platform_listings: {
    platform: string
    url: string | null
    rating: number | null
    review_count: number | null
    is_available: boolean
    opening_hours: OpeningHours | null
    restaurants: { id: string; name: string; cuisine: string | null; neighborhood: string | null } | null
  } | null
}

type RawPromoItemRow = { promo_type: string; label: string; value: number | null }

type RawMenuItemRow = {
  title: string
  price: number | null
  catalog_name: string | null
  image_url: string | null
  description: string | null
}

type RawListingDetail = {
  id: string
  platform: string
  url: string | null
  url_type: string | null
  is_available: boolean | null
  opening_hours: OpeningHours | null
  delivery_fee: number | null
  min_order: number | null
  eta_min: number | null
  eta_max: number | null
  rating: number | null
  last_scraped_at: string | null
  menu_items: RawMenuItemRow[]
  promotions: RawPromoItemRow[]
}

type RawRestaurantDetail = {
  id: string
  name: string
  neighborhood: string | null
  cuisine: string | null
  phone: string | null
  order_url: string | null
  image_url: string | null
  platform_listings: RawListingDetail[]
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
      id, name, cuisine, neighborhood, lat, lng, order_url, image_url, is_chain,
      platform_listings ( platform, delivery_fee, eta_min, rating, url_type, is_available, opening_hours, last_scraped_at )
    `)

  if (error) throw new Error(`getRestaurants: ${error.message}`)

  const threshold = new Date(Date.now() - STALE_THRESHOLD_MS)

  const restaurants: RestaurantSummary[] = ((data ?? []) as unknown as RawRestaurantRow[])
    .map((r) => {
      const rawListings = r.platform_listings ?? []

      const freshListings = rawListings.filter((l) =>
        l.last_scraped_at != null && new Date(l.last_scraped_at) >= threshold
      )

      const listings = freshListings.map((l) => ({
        platform: l.platform as Platform,
        delivery_fee_cents: feeCents(l.delivery_fee),
        eta_min: l.eta_min ?? null,
        is_available: l.is_available !== false,
        opening_hours: l.opening_hours ?? null,
      }))

      const directListing = rawListings.find((l) => l.platform === 'direct') ?? null
      const direct_url_type: string | null = directListing?.url_type ?? null

      const bestRating = rawListings.reduce<number | null>((best, l) => {
        if (l.rating == null) return best
        const v = Number(l.rating)
        return best == null || v > best ? v : best
      }, null)

      const available = listings.filter((l) => l.delivery_fee_cents !== null)

      const lat = r.lat != null ? Number(r.lat) : null
      const lng = r.lng != null ? Number(r.lng) : null
      const order_url: string | null = r.order_url ?? null
      const image_url: string | null = r.image_url ?? null
      const neighborhood: string | null = r.neighborhood ?? null

      if (available.length === 0) {
        return {
          id: r.id,
          name: r.name,
          neighborhood,
          cuisine: r.cuisine ? [r.cuisine] : [],
          lat,
          lng,
          order_url,
          image_url,
          rating: bestRating,
          direct_url_type,
          is_chain: r.is_chain ?? false,
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
        neighborhood,
        cuisine: r.cuisine ? [r.cuisine] : [],
        lat,
        lng,
        order_url,
        image_url,
        rating: bestRating,
        direct_url_type,
        is_chain: r.is_chain ?? false,
        listings,
        cheapest: {
          platform: cheapest.platform,
          fee_label: feeLabel(cheapest.delivery_fee_cents !== null ? cheapest.delivery_fee_cents / 100 : null) ?? '?',
          savings_cents:
            (mostExpensive.delivery_fee_cents ?? 0) -
            (cheapest.delivery_fee_cents ?? 0),
          delivery_fee_cents: cheapest.delivery_fee_cents,
        },
      }
    })
    .sort((a, b) => {
      const countA = a.listings.filter((l) => l.delivery_fee_cents !== null).length
      const countB = b.listings.filter((l) => l.delivery_fee_cents !== null).length
      if (countA !== countB) return countB - countA

      // Within same platform-count tier: chains sink to the bottom
      if (a.is_chain !== b.is_chain) return a.is_chain ? 1 : -1

      // Within same tier + chain status: biggest delivery-fee savings first
      return (b.cheapest?.savings_cents ?? 0) - (a.cheapest?.savings_cents ?? 0)
    })

  const cuisines = [
    ...new Set(restaurants.flatMap((r) => r.cuisine).filter(Boolean)),
  ]
    .sort()
    .slice(0, 8)

  return { restaurants, cuisines }
}

export async function getDeals(): Promise<DealItem[]> {
  const supabase = await getSupabase()

  const { data, error } = await supabase
    .from('promotions')
    .select(`
      id, promo_type, label, value, min_order,
      platform_listings (
        platform, url, rating, review_count, is_available, opening_hours,
        restaurants ( id, name, cuisine, neighborhood )
      )
    `)
    .neq('promo_type', 'other')
    .neq('promo_type', 'spend_save')
    .in('platform_listings.platform', ['uber_eats', 'deliveroo', 'takeaway'])

  if (error) throw new Error(`getDeals: ${error.message}`)

  return ((data ?? []) as unknown as RawPromoRow[]).flatMap((p): DealItem[] => {
    const listing = p.platform_listings
    const restaurant = listing?.restaurants
    if (!listing || !restaurant) return []
    return [{
      id: p.id,
      restaurant_id: restaurant.id,
      restaurant_name: restaurant.name,
      platform: listing.platform as Platform,
      cuisine: restaurant.cuisine ? [restaurant.cuisine] : [],
      area: restaurant.neighborhood ?? null,
      rating: listing.rating != null ? Number(listing.rating) : null,
      review_count: listing.review_count != null ? Number(listing.review_count) : null,
      platform_url: typeof listing.url === 'string' ? listing.url : null,
      promo_type: p.promo_type as DealType,
      label: p.label,
      value: p.value != null ? Number(p.value) : null,
      min_order: p.min_order != null ? Number(p.min_order) : null,
      opening_hours: (listing.opening_hours as OpeningHours | null) ?? null,
      is_available: listing.is_available ?? true,
    }]
  })
}

export const getRestaurantWithListings = cache(async (
  id: string
): Promise<RestaurantDetail | null> => {
  const supabase = await getSupabase()

  const { data, error } = await supabase
    .from('restaurants')
    .select(`
      id, name, neighborhood, cuisine, phone, order_url, image_url,
      platform_listings (
        id, platform, url, url_type, is_available, opening_hours,
        delivery_fee, min_order, eta_min, eta_max, rating, last_scraped_at,
        menu_items ( title, price, catalog_name, image_url, description ),
        promotions ( promo_type, label, value )
      )
    `)
    .eq('id', id)
    .single()

  if (error) return null

  const raw = data as unknown as RawRestaurantDetail
  const threshold = new Date(Date.now() - STALE_THRESHOLD_MS)
  const freshRaw = (raw.platform_listings ?? []).filter((l) =>
    l.last_scraped_at != null && new Date(l.last_scraped_at) >= threshold
  )

  const listings: PlatformListing[] = freshRaw.map((l) => ({
    id: l.id,
    platform: l.platform as Platform,
    platform_url: l.url ?? null,
    url_type: l.url_type ?? null,
    delivery_fee_cents: feeCents(l.delivery_fee),
    delivery_fee_label: feeLabel(l.delivery_fee),
    min_order_cents: feeCents(l.min_order),
    min_order_label: l.min_order != null ? `min €${Number(l.min_order).toFixed(2)}` : null,
    eta_label: etaLabel(l.eta_min, l.eta_max),
    rating: l.rating !== null ? parseFloat(String(l.rating)) : null,
    last_scraped_at: l.last_scraped_at ?? null,
    is_available: l.is_available !== false,
    opening_hours: (l.opening_hours as OpeningHours | null) ?? null,
    promotions: (l.promotions ?? [])
      .filter((p) => p.promo_type !== 'other' && p.promo_type !== 'spend_save')
      .map((p): PromoItem => ({
        promo_type: p.promo_type,
        label: p.label,
        value: p.value != null ? Number(p.value) : null,
      })),
  }))

  const itemMap = new Map<string, MenuItemWithPrices>()

  for (const listing of freshRaw) {
    const platform = listing.platform as Platform
    for (const item of listing.menu_items ?? []) {
      const key = normalizeTitle(item.title)
      if (!itemMap.has(key)) {
        itemMap.set(key, {
          name: item.title.replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu, '').trim(),
          description: item.description ?? null,
          category: item.catalog_name?.replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu, '').trim() ?? null,
          image_url: item.image_url ?? null,
          prices: { uber_eats: null, deliveroo: null, takeaway: null, direct: null },
          platformTitles: { uber_eats: null, deliveroo: null, takeaway: null, direct: null },
        })
      }
      const entry = itemMap.get(key)!
      entry.prices[platform] = feeCents(item.price)
      if (entry.platformTitles) {
        entry.platformTitles[platform] = item.title
          .replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu, '')
          .trim()
      }
    }
  }

  const matchableItems = Array.from(itemMap.values()).filter(
    (item) => Object.values(item.prices).filter((p) => p !== null).length >= 2
  ).length
  const matchRate = itemMap.size > 0 ? matchableItems / itemMap.size : 0

  return {
    id: raw.id,
    name: raw.name,
    city: raw.neighborhood ?? 'Brussels',
    cuisine: raw.cuisine ? [raw.cuisine] : [],
    phone: raw.phone ?? null,
    order_url: raw.order_url ?? null,
    // Use unfiltered listings so url_type matches order_url (both come from the restaurants table,
    // not staleness-gated). Without this, a stale direct listing gives url_type=null → wrong label.
    direct_url_type: (raw.platform_listings ?? []).find((l) => l.platform === 'direct')?.url_type ?? null,
    image_url: raw.image_url ?? null,
    listings,
    menuItems: Array.from(itemMap.values()),
    matchRate,
  }
})
