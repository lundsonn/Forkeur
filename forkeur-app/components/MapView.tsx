'use client'

import { useState } from 'react'
import { Map, Marker } from 'pigeon-maps'
import { osm } from 'pigeon-maps/providers'
import type { RestaurantSummary } from '@/lib/queries'
import MapPreviewCard from './MapPreviewCard'

// Brussels city center
const BRUSSELS_CENTER: [number, number] = [50.85, 4.35]
const DEFAULT_ZOOM = 13

type Props = {
  restaurants: RestaurantSummary[]
  height: string
}

export default function MapView({ restaurants, height }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const pinned = restaurants.filter(
    (r): r is RestaurantSummary & { lat: number; lng: number } =>
      r.lat != null && r.lng != null
  )

  const selected = pinned.find((r) => r.id === selectedId) ?? null

  function handleMapClick() {
    setSelectedId(null)
  }

  return (
    <div
      className="relative rounded-xl overflow-hidden border border-stone-200"
      style={{ height }}
    >
      <Map
        provider={osm}
        defaultCenter={BRUSSELS_CENTER}
        defaultZoom={DEFAULT_ZOOM}
        attribution={false}
        onClick={handleMapClick}
      >
        {pinned.map((r) => {
          const isActive = selectedId === r.id
          return (
            <Marker
              key={r.id}
              anchor={[r.lat, r.lng]}
              onClick={(e) => {
                e.event?.stopPropagation?.()
                setSelectedId(isActive ? null : r.id)
              }}
            >
              <div
                className="relative flex flex-col items-center cursor-pointer select-none"
                onClick={(e) => e.stopPropagation()}
              >
                {/* Pin dot */}
                <div
                  className="rounded-full border-2 border-white shadow transition-all duration-150"
                  style={{
                    backgroundColor: isActive ? '#1A1A1A' : '#D85A30',
                    width: isActive ? 16 : 12,
                    height: isActive ? 16 : 12,
                  }}
                />
              </div>
            </Marker>
          )
        })}
      </Map>

      {/* Pin count badge */}
      <div className="absolute bottom-2 right-2 bg-white/90 backdrop-blur-sm text-stone-600 text-[10px] font-medium px-2 py-1 rounded-full border border-stone-200 pointer-events-none z-10">
        {pinned.length} restaurant{pinned.length !== 1 ? 's' : ''}
      </div>

      {/* Preview card */}
      {selected && (
        <MapPreviewCard
          restaurant={selected}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  )
}
