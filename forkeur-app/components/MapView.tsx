'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { Map, Marker } from 'pigeon-maps'
import { osm } from 'pigeon-maps/providers'
import type { RestaurantSummary } from '@/lib/queries'

// Brussels city center
const BRUSSELS_CENTER: [number, number] = [50.85, 4.35]
const DEFAULT_ZOOM = 13

type Props = {
  restaurants: RestaurantSummary[]
  height: string
}

export default function MapView({ restaurants, height }: Props) {
  const router = useRouter()
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  // Only restaurants with valid coordinates
  const pinned = restaurants.filter(
    (r): r is RestaurantSummary & { lat: number; lng: number } =>
      r.lat != null && r.lng != null
  )

  return (
    <div className="relative rounded-xl overflow-hidden border border-stone-200" style={{ height }}>
      <Map
        provider={osm}
        defaultCenter={BRUSSELS_CENTER}
        defaultZoom={DEFAULT_ZOOM}
        attribution={false}
      >
        {pinned.map((r) => {
          const isHovered = hoveredId === r.id
          return (
            <Marker
              key={r.id}
              anchor={[r.lat, r.lng]}
              onClick={() => router.push(`/restaurant/${r.id}`)}
            >
              <div
                className="relative flex flex-col items-center cursor-pointer select-none"
                onMouseEnter={() => setHoveredId(r.id)}
                onMouseLeave={() => setHoveredId(null)}
              >
                {/* Tooltip */}
                {isHovered && (
                  <div
                    className="absolute bottom-full mb-1.5 whitespace-nowrap bg-stone-900 text-white text-[11px] font-medium px-2 py-1 rounded-md pointer-events-none z-50"
                    style={{ transform: 'translateX(-50%)', left: '50%' }}
                  >
                    {r.name}
                  </div>
                )}
                {/* Pin dot */}
                <div
                  className={`w-3 h-3 rounded-full border-2 border-white shadow transition-transform ${
                    isHovered ? 'scale-150' : 'scale-100'
                  }`}
                  style={{ backgroundColor: '#f97316' }}
                />
              </div>
            </Marker>
          )
        })}
      </Map>

      {/* Pin count badge */}
      <div className="absolute bottom-2 right-2 bg-white/90 backdrop-blur-sm text-stone-600 text-[10px] font-medium px-2 py-1 rounded-full border border-stone-200 pointer-events-none">
        {pinned.length} restaurant{pinned.length !== 1 ? 's' : ''}
      </div>
    </div>
  )
}
