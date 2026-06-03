'use client'
import { useRef } from 'react'
import { Platform, PLATFORM_LABELS, PLATFORM_COLORS, centsToEuro } from '@/lib/basket'
import { useTranslations } from 'next-intl'

type SortedEntry = {
  platform: Platform
  total: number | null
  eta: string | null
}

type Props = {
  cheapestPlatform: Platform
  total: number
  eta: string | null
  savingsCents: number | null
  platformUrl: string | null
  sortedByTotal: SortedEntry[]
  onClose: () => void
}

export default function CompareSheet({
  cheapestPlatform,
  total,
  eta,
  savingsCents,
  platformUrl,
  sortedByTotal,
  onClose,
}: Props) {
  const colors = PLATFORM_COLORS[cheapestPlatform]
  const swipeRef = useRef<{ startY: number } | null>(null)
  const tCompare = useTranslations('compare')

  const cta = (
    <div className="bg-blue-600 text-white rounded-xl px-5 py-3.5 text-center font-semibold text-sm">
      {tCompare('order_on', { platform: PLATFORM_LABELS[cheapestPlatform] })}
    </div>
  )

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end pointer-events-none">
      {/* Backdrop */}
      <div
        data-testid="sheet-backdrop"
        className="absolute inset-0 bg-black/40 pointer-events-auto"
        onClick={onClose}
      />

      {/* Sheet */}
      <div
        className="relative bg-white rounded-t-2xl max-w-md w-full mx-auto pb-safe pointer-events-auto"
        onPointerDown={(e) => { swipeRef.current = { startY: e.clientY } }}
        onPointerMove={(e) => {
          if (!swipeRef.current) return
          if (e.clientY - swipeRef.current.startY > 80) { onClose(); swipeRef.current = null }
        }}
        onPointerUp={() => { swipeRef.current = null }}
        onPointerCancel={() => { swipeRef.current = null }}
      >
        {/* Drag handle */}
        <div className="flex justify-center pt-3 pb-4">
          <div className="w-10 h-1 bg-stone-200 rounded-full" />
        </div>

        <div className="px-5 pb-8">
          {/* Winner card */}
          <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-3">
            {tCompare('best_now')}
          </p>
          <div className="flex items-center gap-2 mb-1">
            <span className={`w-2.5 h-2.5 rounded-full ${colors.dot}`} />
            <p className="text-2xl font-bold text-stone-900">
              {PLATFORM_LABELS[cheapestPlatform]}
            </p>
          </div>
          <p className="text-sm text-stone-500 mb-4">{tCompare('subtitle')}</p>

          {/* Metrics */}
          <div className="flex gap-6 mb-5">
            <div>
              <p className="text-xl font-bold text-stone-900">{centsToEuro(total)}</p>
              <p className="text-[10px] text-stone-400 uppercase tracking-wide mt-0.5">{tCompare('total')}</p>
            </div>
            {eta && (
              <div>
                <p className="text-xl font-bold text-stone-900">{eta}</p>
                <p className="text-[10px] text-stone-400 uppercase tracking-wide mt-0.5">{tCompare('delivery')}</p>
              </div>
            )}
            {savingsCents !== null && savingsCents > 0 && (
              <div>
                <p className="text-xl font-bold text-green-600">{centsToEuro(savingsCents)}</p>
                <p className="text-[10px] text-stone-400 uppercase tracking-wide mt-0.5">{tCompare('you_save')}</p>
              </div>
            )}
          </div>

          {/* All three */}
          <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-2 pt-4 border-t border-stone-100">
            {tCompare('all_live')}
          </p>
          {sortedByTotal.map(({ platform, total: rowTotal, eta: e }) => {
            const isBest = platform === cheapestPlatform
            const c = PLATFORM_COLORS[platform]
            return (
              <div
                key={platform}
                className="flex items-center justify-between py-2.5 border-b border-stone-100 last:border-0"
              >
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${c.dot}`} />
                  <span className={`text-sm ${isBest ? 'text-stone-900' : 'text-stone-500'}`}>
                    {PLATFORM_LABELS[platform]}
                  </span>
                  {isBest && (
                    <span className="text-[10px] border border-stone-300 rounded-full px-1.5 py-0.5 text-stone-500 leading-none">
                      {tCompare('best_badge')}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-4">
                  {e && <span className="text-xs text-stone-400">{e}</span>}
                  <span className={`text-sm font-semibold ${isBest ? 'text-stone-900' : 'text-stone-500'}`}>
                    {centsToEuro(rowTotal)}
                  </span>
                </div>
              </div>
            )
          })}

          <p className="text-xs text-stone-400 mt-3 mb-5">
            {tCompare('why', { platform: PLATFORM_LABELS[cheapestPlatform] })}
          </p>

          {/* CTA */}
          {platformUrl ? (
            <a
              href={platformUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={tCompare('order_on', { platform: PLATFORM_LABELS[cheapestPlatform] })}
            >
              {cta}
            </a>
          ) : (
            <div aria-disabled="true" className="opacity-60 cursor-not-allowed">{cta}</div>
          )}
        </div>
      </div>
    </div>
  )
}
