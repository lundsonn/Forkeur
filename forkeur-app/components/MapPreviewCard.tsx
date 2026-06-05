'use client'

import Image from 'next/image'
import Link from 'next/link'
import { useState } from 'react'
import { useTranslations } from 'next-intl'
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
  const tMap = useTranslations('map')

  const showImage = !!restaurant.image_url && !imgError
  // cheapest.fee_label is "Free" | "€X.XX" | null
  const rawFeeLabel = restaurant.cheapest?.fee_label ?? null
  const feeLabel =
    rawFeeLabel == null
      ? null
      : rawFeeLabel === 'Free'
        ? tMap('free_delivery')
        : tMap('from', { fee: rawFeeLabel })
  const savingsCents = restaurant.cheapest?.savings_cents ?? 0
  const cheapestFeeCents = restaurant.cheapest?.delivery_fee_cents ?? null
  const maxFeeCents = cheapestFeeCents != null && savingsCents > 0 ? cheapestFeeCents + savingsCents : null
  const showStrikethrough = maxFeeCents != null && savingsCents >= 50

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
        {feeLabel && (
          <div className="flex items-center gap-1.5 mb-3">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: '#1E8A5A' }} />
            <span className="font-medium" style={{ fontSize: 15, color: '#1A1A1A' }}>
              {feeLabel}
            </span>
            {showStrikethrough && maxFeeCents != null && (
              <span
                className="line-through"
                style={{ fontSize: 14, color: '#888780' }}
                aria-label={`€${(maxFeeCents / 100).toFixed(2)} on other platforms`}
              >
                €{(maxFeeCents / 100).toFixed(2)}
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
          {tMap('compare_cta')}
        </Link>
      </div>
    </>
  )
}
