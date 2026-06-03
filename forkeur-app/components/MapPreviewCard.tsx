'use client'

import Image from 'next/image'
import Link from 'next/link'
import { useState } from 'react'
import type { RestaurantSummary } from '@/lib/queries'

const CUISINE_ICONS: Record<string, string> = {
  pizza: '🍕',
  sushi: '🍣',
  burger: '🍔',
  thai: '🍜',
  indian: '🍛',
  chinese: '🥡',
  japanese: '🍱',
  italian: '🍝',
  mexican: '🌮',
  vietnamese: '🍜',
  greek: '🥙',
  turkish: '🥙',
  kebab: '🥙',
  salad: '🥗',
  sandwich: '🥪',
  breakfast: '🍳',
  bakery: '🥐',
  dessert: '🍰',
}

function cuisineIcon(cuisines: string[]): string {
  for (const c of cuisines) {
    const lower = c.toLowerCase()
    for (const [key, icon] of Object.entries(CUISINE_ICONS)) {
      if (lower.includes(key)) return icon
    }
  }
  return '🍽️'
}

type Props = {
  restaurant: RestaurantSummary
  onClose: () => void
}

export default function MapPreviewCard({ restaurant, onClose }: Props) {
  const [imgError, setImgError] = useState(false)

  const showImage = !!restaurant.image_url && !imgError
  // cheapest.fee_label is "Free" | "€X.XX" | null
  const rawFeeLabel = restaurant.cheapest?.fee_label ?? null
  const feeLabel =
    rawFeeLabel == null
      ? null
      : rawFeeLabel === 'Free'
        ? 'Free delivery'
        : `from ${rawFeeLabel}`
  const savingsCents = restaurant.cheapest?.savings_cents ?? 0
  const savingsLabel = savingsCents > 0 ? `Save €${(savingsCents / 100).toFixed(2)}` : null

  return (
    <>
      {/* Tap backdrop → dismiss */}
      <div
        className="absolute inset-0 z-10"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Preview card */}
      <div
        className="absolute bottom-0 left-0 right-0 z-20 bg-white px-4 pt-3 pb-5 map-preview-slide-up"
        style={{
          borderRadius: '16px 16px 0 0',
          boxShadow: '0 -4px 24px rgba(0,0,0,0.13)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Drag handle (cosmetic) */}
        <div className="flex justify-center mb-3">
          <div className="w-8 h-1 rounded-full" style={{ backgroundColor: '#E0DED9' }} />
        </div>

        {/* Content row */}
        <div className="flex gap-3 mb-3">
          {/* Thumbnail */}
          <div
            className="shrink-0 w-14 h-14 rounded-xl overflow-hidden flex items-center justify-center"
            style={{ backgroundColor: '#EDEDEA' }}
          >
            {showImage ? (
              <Image
                src={restaurant.image_url!}
                alt={restaurant.name}
                width={56}
                height={56}
                className="w-full h-full object-cover"
                unoptimized
                onError={() => setImgError(true)}
              />
            ) : (
              <span className="text-2xl">{cuisineIcon(restaurant.cuisine)}</span>
            )}
          </div>

          {/* Name + cuisine + rating */}
          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <p
                className="font-medium leading-snug truncate"
                style={{ fontSize: 16, color: '#1A1A1A' }}
              >
                {restaurant.name}
              </p>
              {restaurant.rating != null && (
                <div
                  className="shrink-0 flex items-center gap-0.5 font-medium"
                  style={{ fontSize: 13, color: '#1A1A1A' }}
                >
                  <span style={{ color: '#D85A30' }}>★</span>
                  {restaurant.rating.toFixed(1)}
                </div>
              )}
            </div>
            <p
              className="truncate mt-0.5"
              style={{ fontSize: 13, color: '#888780' }}
            >
              {[restaurant.cuisine[0], restaurant.neighborhood]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </div>
        </div>

        {/* Price + savings row */}
        {(feeLabel || savingsLabel) && (
          <div className="flex items-center justify-between mb-3">
            {feeLabel && (
              <div className="flex items-center gap-1.5">
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: '#1E8A5A' }}
                />
                <span className="font-medium" style={{ fontSize: 15, color: '#1A1A1A' }}>
                  {feeLabel}
                </span>
              </div>
            )}
            {savingsLabel && (
              <span
                className="font-medium px-2 py-0.5 rounded-full"
                style={{ fontSize: 12, color: '#1E8A5A', backgroundColor: '#E8F5EE' }}
              >
                {savingsLabel}
              </span>
            )}
          </div>
        )}

        {/* CTA */}
        <Link
          href={`/restaurant/${restaurant.id}`}
          className="block w-full text-center text-white font-medium py-3 rounded-lg text-sm"
          style={{ backgroundColor: '#1A1A1A' }}
        >
          Compare prices →
        </Link>
      </div>
    </>
  )
}
