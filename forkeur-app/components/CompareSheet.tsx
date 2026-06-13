'use client'
import { useRef } from 'react'
import { Platform, PLATFORM_LABELS, PLATFORM_COLORS, PlatformCoverages, centsToEuro } from '@/lib/basket'
import { useTranslations } from 'next-intl'

type SortedEntry = {
  platform: Platform
  total: number | null
  eta: string | null
}

type Props = {
  cheapestPlatform: Platform | null
  total: number | null
  eta: string | null
  savingsCents: number | null
  platformUrl: string | null
  sortedByTotal: SortedEntry[]
  coverages: PlatformCoverages | null
  isFeesOnly?: boolean
  onClose: () => void
}

export default function CompareSheet({
  cheapestPlatform,
  total,
  eta,
  savingsCents,
  platformUrl,
  sortedByTotal,
  coverages,
  isFeesOnly = false,
  onClose,
}: Props) {
  const swipeRef = useRef<{ startY: number } | null>(null)
  const tCompare = useTranslations('compare')

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
          {/* Winner card or neutral state */}
          {cheapestPlatform ? (
            <>
              <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-3">
                {tCompare('best_now')}
              </p>
              <div className="flex items-center gap-2 mb-1">
                <span className={`w-2.5 h-2.5 rounded-full ${PLATFORM_COLORS[cheapestPlatform].dot}`} />
                <p className="text-2xl font-bold text-stone-900">
                  {PLATFORM_LABELS[cheapestPlatform]}
                </p>
              </div>
              <p className="text-sm text-stone-500 mb-4">
                {isFeesOnly ? tCompare('subtitle_fees') : tCompare('subtitle')}
              </p>

              {/* Metrics */}
              <div className="flex gap-6 mb-5">
                <div>
                  <p className="text-xl font-bold text-stone-900">{centsToEuro(total)}</p>
                  <p className="text-[10px] text-stone-400 uppercase tracking-wide mt-0.5">{isFeesOnly ? tCompare('delivery_fee') : tCompare('total')}</p>
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
            </>
          ) : (
            <>
              <p className="text-2xl font-bold mb-1" style={{ color: '#1A1A1A' }}>
                {tCompare('no_winner_heading')}
              </p>
              <p className="text-sm text-stone-500 mb-5">{tCompare('no_winner_subline')}</p>
            </>
          )}

          {/* All platforms */}
          <p className="text-[10px] font-semibold tracking-widest text-stone-400 uppercase mb-2 pt-4 border-t border-stone-100">
            {sortedByTotal.length === 3 ? tCompare('all_live') : tCompare('live_prices')}
          </p>
          {sortedByTotal.map(({ platform, total: rowTotal, eta: e }) => {
            const isBest = platform === cheapestPlatform
            const c = PLATFORM_COLORS[platform]
            const coverage = coverages?.[platform]
            const isIncomplete =
              coverage !== null &&
              coverage !== undefined &&
              !coverage.complete &&
              coverage.total > 0
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
                <div className="flex flex-col items-end gap-0.5">
                  <div className="flex items-center gap-4">
                    {e && <span className="text-xs text-stone-500">{e}</span>}
                    <span
                      className={`text-sm ${
                        isIncomplete
                          ? 'font-normal'
                          : isBest
                            ? 'font-semibold text-stone-900'
                            : 'font-semibold text-stone-500'
                      }`}
                      style={isIncomplete ? { color: '#888780' } : undefined}
                    >
                      {centsToEuro(rowTotal)}
                    </span>
                  </div>
                  {isIncomplete && coverage && (
                    <span className="text-[11px]" style={{ color: '#888780' }}>
                      {tCompare('partial_coverage', { priced: coverage.priced, total: coverage.total })}
                    </span>
                  )}
                </div>
              </div>
            )
          })}

          {cheapestPlatform && (
            <p className="text-xs text-stone-500 mt-3 mb-5">
              {isFeesOnly
                ? tCompare('why_fees', { platform: PLATFORM_LABELS[cheapestPlatform] })
                : tCompare('why', { platform: PLATFORM_LABELS[cheapestPlatform] })}
            </p>
          )}

          {/* CTA */}
          <div className={cheapestPlatform ? '' : 'mt-5'}>
            {cheapestPlatform ? (
              platformUrl ? (
                <a
                  href={platformUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={tCompare('order_on', { platform: PLATFORM_LABELS[cheapestPlatform] })}
                >
                  <div className="text-white rounded-xl px-5 py-3.5 text-center font-semibold text-sm" style={{ backgroundColor: '#2E86D8' }}>
                    {tCompare('order_on', { platform: PLATFORM_LABELS[cheapestPlatform] })}
                  </div>
                </a>
              ) : (
                <div aria-disabled="true" className="opacity-60 cursor-not-allowed">
                  <div className="text-white rounded-xl px-5 py-3.5 text-center font-semibold text-sm" style={{ backgroundColor: '#2E86D8' }}>
                    {tCompare('order_on', { platform: PLATFORM_LABELS[cheapestPlatform] })}
                  </div>
                </div>
              )
            ) : (
              <button
                onClick={onClose}
                className="w-full rounded-xl px-5 py-3.5 text-center font-semibold text-sm border"
                style={{ borderColor: '#888780', color: '#888780' }}
              >
                {tCompare('compare_cta')}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
