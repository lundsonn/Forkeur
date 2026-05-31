'use client'
import { Platform, PLATFORM_LABELS, PLATFORM_COLORS, centsToEuro } from '@/lib/basket'

type Props = {
  platform: Platform | null
  total: number | null
  platformUrl: string | null
}

export default function StickyOrderBar({ platform, total, platformUrl }: Props) {
  if (!platform || total === null) return null

  const colors = PLATFORM_COLORS[platform]

  const inner = (
    <div
      className="flex items-center justify-between px-5 py-4 bg-blue-600"
      style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom, 0px))' }}
    >
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${colors.dot}`} />
        <span className="text-sm font-semibold text-white">
          Order on {PLATFORM_LABELS[platform]}
        </span>
      </div>
      <span className="text-sm font-semibold text-white">{centsToEuro(total)}</span>
    </div>
  )

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 flex justify-center pointer-events-none">
      <div className="w-full max-w-md pointer-events-auto">
        {platformUrl ? (
          <a
            href={platformUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="block hover:opacity-90 transition-opacity"
          >
            {inner}
          </a>
        ) : (
          <div className="opacity-60 cursor-not-allowed">{inner}</div>
        )}
      </div>
    </div>
  )
}
