import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import Link from 'next/link'
import { getRestaurantWithListings } from '@/lib/queries'
import BasketSimulator from '@/components/BasketSimulator'

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>
}): Promise<Metadata> {
  const { id } = await params
  const data = await getRestaurantWithListings(id)
  return {
    title: data?.name ?? "Restaurant",
  }
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const data = await getRestaurantWithListings(id)

  if (!data) notFound()

  const bestRating = data.listings
    .map((l) => l.rating)
    .filter((r): r is number => r !== null)
    .sort((a, b) => b - a)[0] ?? null

  return (
    <div className="max-w-md mx-auto">
      {/* Nav */}
      <div className="flex items-center px-5 pt-5 pb-3">
        <Link href="/" className="text-stone-500 hover:text-stone-800 text-lg mr-auto">‹</Link>
        <span className="font-bold text-sm tracking-tight absolute left-1/2 -translate-x-1/2">
          fork<span className="text-orange-500">eur</span>
        </span>
      </div>

      {/* Restaurant info */}
      <div className="px-5 pb-4">
        <h1 className="text-2xl font-bold text-stone-900 mt-2">{data.name}</h1>
        <p className="text-sm text-stone-400 mt-1">
          {data.cuisine.join(' · ')} · {data.city}
          {bestRating !== null && ` · ★ ${bestRating.toFixed(1)}`}
        </p>
        {data.order_url && (
          <a
            href={data.order_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-orange-500 hover:bg-orange-600 text-white font-semibold text-sm transition-colors"
          >
            Commander directement · sans frais de plateforme
          </a>
        )}
      </div>

      <BasketSimulator menuItems={data.menuItems} listings={data.listings} phone={data.phone} />
    </div>
  )
}
