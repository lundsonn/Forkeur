'use client'
import { useState } from 'react'
import { useTranslations } from 'next-intl'
import {
  PLATFORM_COLORS,
  PLATFORM_LABELS,
  centsToEuro,
  type Platform,
  type PlatformCoverages,
} from '@/lib/basket'
import type { MenuItemWithPrices, PlatformListing } from '@/lib/queries'
import type { BasketEntry } from './MenuBrowser'
import PlatformLogo from './ui/PlatformLogo'

export interface CompareDecisionProps {
  basket: BasketEntry[]
  listings: PlatformListing[]
  menuItems: MenuItemWithPrices[]
  totals: Record<Platform, number | null>
  coverages: PlatformCoverages | null
  cheapestPlatform: Platform | null
  menuDirectSavingsCents: number | null
  phone?: string
  orderChannel?: string
  isFeesOnly?: boolean
}

export default function CompareDecision({
  basket,
  listings,
  menuItems,
  totals,
  coverages,
  cheapestPlatform,
  menuDirectSavingsCents,
  phone,
  orderChannel,
  isFeesOnly = false,
}: CompareDecisionProps) {
  const t = useTranslations('BasketSimulator')
  const [expanded, setExpanded] = useState(false)

  const hasItems = basket.some((i) => i.qty > 0)

  if (!hasItems) {
    return (
      <div className="flex flex-col items-center justify-center py-20 px-8 text-center text-stone-500">
        <p className="text-base">{t('emptyCompare')}</p>
      </div>
    )
  }

  const feeMap: Record<Platform, { fee: number | null; eta: string | null; url: string | null }> = {
    uber_eats: { fee: null, eta: null, url: null },
    deliveroo: { fee: null, eta: null, url: null },
    takeaway: { fee: null, eta: null, url: null },
    direct: { fee: null, eta: null, url: null },
  }
  for (const listing of listings) {
    feeMap[listing.platform] = {
      fee: listing.delivery_fee_cents,
      eta: listing.eta_label,
      url: listing.platform_url,
    }
  }

  const platforms = (['uber_eats', 'deliveroo', 'takeaway', 'direct'] as Platform[])
    .filter((p) => totals[p] !== null)
    .sort((a, b) => (totals[a] ?? Infinity) - (totals[b] ?? Infinity))

  const directCoverage = coverages?.direct ?? null
  const directMatchedCount = directCoverage?.priced ?? 0
  const basketItemCount = basket.filter((i) => i.qty > 0).length
  const directThresholdMet = directMatchedCount >= Math.ceil(basketItemCount * 0.5)

  function getMissingNames(platform: Platform): string[] {
    const coverage = coverages?.[platform]
    if (!coverage || coverage.complete) return []
    return basket
      .filter((b) => b.qty > 0 && (menuItems.find((m) => m.name === b.name)?.prices[platform] ?? null) === null)
      .map((b) => b.name)
  }

  // Winner card derived values
  const winner = cheapestPlatform
  const winnerTotal = winner !== null ? (totals[winner] ?? null) : null
  const winnerFee = winner !== null ? (feeMap[winner].fee ?? 0) : 0
  const winnerEta = winner !== null ? feeMap[winner].eta : null
  const winnerUrl = winner !== null ? feeMap[winner].url : null

  // Next-best for savings hero
  const nonWinnerPlatforms = platforms.filter(
    (p) => p !== winner && !(p === 'direct' && !directThresholdMet),
  )
  const nextBestPlatform = nonWinnerPlatforms[0] ?? null
  const nextBestTotal = nextBestPlatform !== null ? (totals[nextBestPlatform] ?? null) : null

  const savingsCents =
    winnerTotal !== null && nextBestTotal !== null ? nextBestTotal - winnerTotal : null
  const savingsPct =
    savingsCents !== null && nextBestTotal !== null && nextBestTotal > 0
      ? Math.round((savingsCents / nextBestTotal) * 100)
      : null

  const canShowSavings = !isFeesOnly && savingsCents !== null && savingsCents > 0

  // Coverage chip
  function getCoverageChip(): string {
    if (isFeesOnly) return t('feesOnlyFallback')
    const allComplete = platforms.every((p) => coverages?.[p]?.complete === true)
    if (allComplete) return t('coverageComplete')
    if (winner) {
      const wCov = coverages?.[winner]
      if (wCov && !wCov.complete) {
        const missing = getMissingNames(winner)
        if (missing.length > 0) {
          return t('coveragePartialFull', {
            matched: wCov.priced,
            total: wCov.total,
            missing: missing.slice(0, 2).join(', ') + (missing.length > 2 ? ` +${missing.length - 2}` : ''),
          })
        }
        return t('coveragePartialShort', { matched: wCov.priced, total: wCov.total })
      }
    }
    return t('coverageComplete')
  }

  return (
    <div className="px-4 py-4 space-y-3">
      {/* Direct savings callout — must precede all platform-card-* in DOM */}
      {menuDirectSavingsCents !== null && menuDirectSavingsCents > 0 && (
        <div
          className="bg-orange-50 border border-orange-200 rounded-lg px-4 py-2 text-orange-700 text-sm font-medium"
          data-testid="direct-savings"
        >
          {t('directSavings', { amount: centsToEuro(menuDirectSavingsCents) })}
        </div>
      )}

      {/* Winner card */}
      {winner && winnerTotal !== null && (
        <div
          className="border-2 border-orange-500 rounded-xl p-4 bg-white shadow-sm"
          data-testid={`platform-card-${winner}`}
        >
          {/* Header row */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${PLATFORM_COLORS[winner].dot}`} />
              <span className="font-semibold text-stone-800 text-sm">{PLATFORM_LABELS[winner]}</span>
              <span
                className="bg-orange-600 text-white text-xs font-bold px-2 py-0.5 rounded"
                data-testid="best-badge"
              >
                {t('winnerLabel')}
              </span>
            </div>
            {winnerUrl && (
              <a
                href={winnerUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-1.5 rounded-lg whitespace-nowrap ml-2 transition-colors"
                data-testid="winner-cta"
              >
                {t('orderOn', { platform: PLATFORM_LABELS[winner] })}
              </a>
            )}
          </div>

          {/* Total price hero */}
          <p className="text-3xl font-bold text-stone-900 leading-none">
            {centsToEuro(winnerTotal)}
          </p>
          <p className="text-xs text-stone-400 mt-0.5 mb-3">{t('totalLabel')}</p>

          {/* Savings hero — only when real basket totals available */}
          {canShowSavings && savingsCents !== null && savingsPct !== null && nextBestPlatform !== null && nextBestTotal !== null && (
            <div className="bg-green-50 border border-green-200 rounded-lg px-3 py-2 mb-3">
              <p className="text-sm font-semibold text-green-800">
                {t('savingsLine1', { saving: centsToEuro(savingsCents), pct: savingsPct })}
              </p>
              <p className="text-xs text-green-700 mt-0.5">
                {t('savingsLine2', { platform: PLATFORM_LABELS[nextBestPlatform] })}
              </p>
              {/* Strikethrough alternatives */}
              <p className="text-xs text-stone-500 mt-1.5">
                <span className="font-medium text-stone-600">{t('nextBestLabel')}</span>{' '}
                {nonWinnerPlatforms.map((p, i) => (
                  <span key={p}>
                    {i > 0 && ' · '}
                    <span className="line-through">{centsToEuro(totals[p]!)} {PLATFORM_LABELS[p]}</span>
                  </span>
                ))}
              </p>
            </div>
          )}

          {/* Coverage chip + ETA */}
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <span className="inline-flex items-center bg-stone-100 text-stone-600 text-xs px-2 py-0.5 rounded-full">
              {getCoverageChip()}
            </span>
            {winnerEta && (
              <span className="text-xs text-stone-500">{winnerEta}</span>
            )}
          </div>

          {/* Expand / collapse toggle */}
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-xs text-stone-500 underline underline-offset-2 hover:text-stone-700 transition-colors"
          >
            {expanded ? t('hideDetails') : t('showDetails')}
          </button>
        </div>
      )}

      {/* Evidence section — always in DOM for testIds, CSS hidden when collapsed */}
      <div className={expanded ? 'space-y-2' : 'hidden'}>
        <p className="text-xs font-bold text-stone-400 tracking-widest px-1">
          {t('allPlatformsTitle')}
        </p>

        {/* Winner fee breakdown row */}
        {winner && winnerTotal !== null && (
          <div className="border border-stone-200 rounded-lg p-3 bg-stone-50">
            <p className="text-xs font-semibold text-stone-600 mb-2">
              {t('feeBreakdownTitle', { platform: PLATFORM_LABELS[winner] })}
            </p>
            <div className="space-y-1 text-xs text-stone-600">
              <div className="flex justify-between">
                <span>{t('feeItems')}</span>
                <span>{centsToEuro(winnerTotal - winnerFee)}</span>
              </div>
              <div className="flex justify-between">
                <span>{t('feeDelivery')}</span>
                <span>{winnerFee > 0 ? centsToEuro(winnerFee) : '—'}</span>
              </div>
              <div className="flex justify-between font-semibold text-stone-800 border-t border-stone-200 pt-1 mt-1">
                <span>{t('feeTotal')}</span>
                <span>{centsToEuro(winnerTotal)}</span>
              </div>
            </div>
            <p className="text-xs text-stone-500 mt-2">
              {t('whyWinner', { platform: PLATFORM_LABELS[winner] })}
            </p>
          </div>
        )}

        {/* Non-winner platform rows */}
        {nonWinnerPlatforms.map((platform) => {
          const total = totals[platform]!
          const { fee, eta } = feeMap[platform]
          const delta = winnerTotal !== null ? total - winnerTotal : null
          const missingNames = getMissingNames(platform)

          if (platform === 'direct' && !directThresholdMet) {
            return (
              <div
                key={platform}
                className="border border-stone-200 rounded-lg p-3 opacity-60"
                data-testid={`platform-card-${platform}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`w-2 h-2 rounded-full ${PLATFORM_COLORS[platform].dot}`} />
                  <span className="font-semibold text-stone-500 text-sm">{PLATFORM_LABELS[platform]}</span>
                </div>
                <p className="text-xs text-stone-400">
                  {t('directPartialCoverage', { matched: directMatchedCount, total: basketItemCount })}
                </p>
                {phone && <p className="text-xs text-stone-400 mt-1">📞 {phone}</p>}
              </div>
            )
          }

          return (
            <div
              key={platform}
              className="border border-stone-200 rounded-lg p-3"
              data-testid={`platform-card-${platform}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${PLATFORM_COLORS[platform].dot}`} />
                  <span className="font-semibold text-stone-700 text-sm">{PLATFORM_LABELS[platform]}</span>
                </div>
                <div className="text-right">
                  <p className="font-bold text-stone-800 text-sm">{centsToEuro(total)}</p>
                  {delta !== null && delta > 0 && (
                    <p className="text-xs text-red-500" data-testid="delta-text">
                      {t('deltaVsBest', { amount: centsToEuro(delta) })}
                    </p>
                  )}
                </div>
              </div>
              <p className="text-xs text-stone-400 mt-1">
                {fee !== null ? `Delivery ${centsToEuro(fee)}` : 'Free delivery'}
                {eta ? ` · ${eta}` : ''}
              </p>
              {missingNames.length > 0 && (
                <p className="text-xs text-amber-600 mt-1" data-testid="missing-items">
                  {t('missingItems', {
                    items:
                      missingNames.slice(0, 2).join(', ') +
                      (missingNames.length > 2 ? ` + ${missingNames.length - 2} more` : ''),
                  })}
                </p>
              )}
              {platform === 'direct' && phone && orderChannel !== 'covered_platform' && (
                <a
                  href={`tel:${phone}`}
                  className="mt-2 inline-block text-xs text-violet-700 font-medium"
                  data-testid="direct-phone-cta"
                >
                  📞 {phone}
                </a>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
