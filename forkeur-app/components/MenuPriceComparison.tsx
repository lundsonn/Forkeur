'use client'

import { useState, useMemo } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useTranslations } from 'next-intl'
import type { MenuItemWithPrices } from '@/lib/queries'
import { PLATFORM_LABELS } from '@/lib/basket'

const AGGREGATOR_PLATFORMS = ['uber_eats', 'deliveroo', 'takeaway'] as const
type AggPlatform = (typeof AGGREGATOR_PLATFORMS)[number]

const PLATFORM_ABBR: Record<AggPlatform, string> = {
  uber_eats: 'UE',
  deliveroo: 'DEL',
  takeaway: 'TA',
}

const PAGE_SIZE = 10

type Props = {
  items: MenuItemWithPrices[]
  matchRate: number
}

export default function MenuPriceComparison({ items, matchRate }: Props) {
  const t = useTranslations('menuPrices')
  const [expanded, setExpanded] = useState(false)
  const [page, setPage] = useState(1)

  const stats = useMemo(() => {
    const comparable = items.filter(
      (item) => AGGREGATOR_PLATFORMS.filter((p) => item.prices[p] !== null).length >= 2
    )
    if (comparable.length === 0) return null

    const itemSavings = comparable.map((item) => {
      const prices = AGGREGATOR_PLATFORMS.map((p) => item.prices[p]).filter(
        (v): v is number => v !== null
      )
      const min = Math.min(...prices)
      const max = Math.max(...prices)
      return { item, savings: max - min, min }
    })

    const totalSavingsCents = itemSavings.reduce((s, x) => s + x.savings, 0)
    const avgSavingsCents = Math.round(totalSavingsCents / comparable.length)
    const allSame = avgSavingsCents === 0

    const wins: Record<AggPlatform, number> = { uber_eats: 0, deliveroo: 0, takeaway: 0 }
    for (const { item, min, savings } of itemSavings) {
      if (savings === 0) continue
      for (const p of AGGREGATOR_PLATFORMS) {
        if (item.prices[p] === min) wins[p]++
      }
    }
    const winnerPlatform = AGGREGATOR_PLATFORMS.reduce((best, p) =>
      wins[p] > wins[best] ? p : best
    )

    const platformStats = AGGREGATOR_PLATFORMS.map((p) => {
      const prices = comparable
        .map((item) => item.prices[p])
        .filter((v): v is number => v !== null)
      if (prices.length === 0) return null
      const avg = Math.round(prices.reduce((s, v) => s + v, 0) / prices.length)
      return { platform: p, avgCents: avg }
    }).filter((s): s is NonNullable<typeof s> => s !== null)

    const maxAvg = Math.max(...platformStats.map((s) => s.avgCents))
    const cheapestAvgPlatform = platformStats.reduce((best, s) =>
      s.avgCents < best.avgCents ? s : best
    ).platform

    const scannerItems = [...itemSavings].sort((a, b) => b.savings - a.savings)

    return {
      comparable,
      avgSavingsCents,
      allSame,
      winnerPlatform,
      winnerCount: wins[winnerPlatform],
      platformStats,
      maxAvg,
      cheapestAvgPlatform,
      scannerItems,
      total: items.length,
    }
  }, [items])

  if (!stats) return null

  const presentPlatforms = AGGREGATOR_PLATFORMS.filter((p) =>
    stats.platformStats.some((s) => s.platform === p)
  )

  const visibleCount = page * PAGE_SIZE
  const visibleItems = stats.scannerItems.slice(0, visibleCount)
  const remaining = stats.scannerItems.length - visibleCount

  function handleToggle() {
    if (expanded) setPage(1)
    setExpanded((e) => !e)
  }

  return (
    <div className="px-5 mb-2 mt-4">
      <div
        style={{
          background: 'var(--color-background-primary, #fff)',
          border: '0.5px solid var(--color-border-tertiary, #e5e5e0)',
          borderRadius: '12px',
          overflow: 'hidden',
        }}
      >
        {/* Summary */}
        <div style={{ padding: '16px' }}>
          <p
            style={{
              fontSize: '11px',
              color: '#888780',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
              fontWeight: 500,
              marginBottom: '10px',
            }}
          >
            {t('section_label')}
          </p>

          {stats.allSame ? (
            <p style={{ fontSize: '13px', fontWeight: 500, color: '#1A1A1A', marginBottom: '12px' }}>
              {t('same_prices')}
            </p>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
                <span
                  style={{
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    background: '#1E8A5A',
                    flexShrink: 0,
                  }}
                />
                <span style={{ fontSize: '13px', fontWeight: 500, color: '#1A1A1A' }}>
                  {stats.comparable.length === 1
                    ? t('one_item_compared')
                    : t('winner', {
                        platform: PLATFORM_LABELS[stats.winnerPlatform as keyof typeof PLATFORM_LABELS],
                        x: stats.winnerCount,
                        y: stats.comparable.length,
                      })}
                </span>
              </div>
              <div
                style={{ display: 'flex', alignItems: 'baseline', gap: '4px', marginBottom: '12px' }}
              >
                <span style={{ fontSize: '20px', fontWeight: 500, color: '#1E8A5A' }}>
                  €{(stats.avgSavingsCents / 100).toFixed(2)}
                </span>
                <span style={{ fontSize: '14px', color: '#888780' }}>{t('avg_savings')}</span>
              </div>
            </>
          )}

          {/* Per-platform bars */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {stats.platformStats.map((ps) => {
              const isCheapest = ps.platform === stats.cheapestAvgPlatform
              const barPct = stats.maxAvg > 0 ? (ps.avgCents / stats.maxAvg) * 100 : 100
              return (
                <div key={ps.platform}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
                    <span style={{ fontSize: '12px', color: '#888780' }}>
                      {PLATFORM_LABELS[ps.platform as keyof typeof PLATFORM_LABELS]}
                    </span>
                    <span
                      style={{
                        fontSize: '12px',
                        fontWeight: 500,
                        color: isCheapest ? '#1E8A5A' : '#1A1A1A',
                      }}
                    >
                      avg €{(ps.avgCents / 100).toFixed(2)}
                    </span>
                  </div>
                  <div style={{ height: '4px', borderRadius: '2px', background: '#EDEDEA' }}>
                    <div
                      style={{
                        width: `${barPct}%`,
                        height: '100%',
                        borderRadius: '2px',
                        background: isCheapest ? '#1E8A5A' : '#1A1A1A',
                      }}
                    />
                  </div>
                </div>
              )
            })}
          </div>

          {/* Tier 2 disclaimer */}
          {matchRate < 0.7 && (
            <p style={{ fontSize: '12px', color: '#888780', marginTop: '10px' }}>
              {t('disclaimer', { x: stats.comparable.length, y: stats.total })}
            </p>
          )}

          {/* Expand button */}
          <button
            onClick={handleToggle}
            style={{
              marginTop: '12px',
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '4px',
              fontSize: '13px',
              color: '#2E86D8',
              border: '0.5px solid #888780',
              borderRadius: '8px',
              padding: '10px',
              background: 'transparent',
              cursor: 'pointer',
            }}
          >
            {t('expand', { count: stats.comparable.length })}
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>

        {/* Scanner */}
        {expanded && (
          <>
            <div style={{ height: '0.5px', background: 'var(--color-border-tertiary, #e5e5e0)' }} />
            <div style={{ padding: '16px' }}>
              {/* Column headers */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  gap: '6px',
                  marginBottom: '4px',
                }}
              >
                {presentPlatforms.map((p) => (
                  <div key={p} style={{ width: '58px', textAlign: 'center' }}>
                    <span
                      style={{
                        fontSize: '11px',
                        color: '#888780',
                        fontWeight: 500,
                        letterSpacing: '0.3px',
                      }}
                    >
                      {PLATFORM_ABBR[p]}
                    </span>
                  </div>
                ))}
              </div>

              {/* Item rows */}
              <div>
                {visibleItems.map(({ item, min, savings }, idx) => {
                  const isLast = idx === visibleItems.length - 1
                  const platformTitleParts = presentPlatforms
                    .filter((p) => {
                      const orig = item.platformTitles?.[p]
                      return orig != null && orig !== item.name
                    })
                    .map((p) => `${PLATFORM_ABBR[p]}: ${item.platformTitles?.[p]}`)
                  const titleSubtitle =
                    platformTitleParts.length > 0 ? platformTitleParts.join(' · ') : null

                  return (
                    <div
                      key={`${item.name}-${idx}`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        paddingTop: '12px',
                        paddingBottom: '12px',
                        borderBottom: isLast
                          ? 'none'
                          : '0.5px solid var(--color-border-tertiary, #e5e5e0)',
                      }}
                    >
                      <div style={{ flex: 1, minWidth: 0, paddingRight: '8px' }}>
                        <p
                          style={{
                            fontSize: '14px',
                            fontWeight: 500,
                            color: '#1A1A1A',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            margin: 0,
                          }}
                        >
                          {item.name}
                        </p>
                        {titleSubtitle && (
                          <p
                            style={{
                              fontSize: '11px',
                              color: '#888780',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                              margin: '2px 0 0',
                            }}
                          >
                            {titleSubtitle}
                          </p>
                        )}
                      </div>

                      <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                        {presentPlatforms.map((p) => {
                          const price = item.prices[p]
                          const isGreen =
                            price !== null &&
                            price === min &&
                            (savings > 0 || stats.allSame)
                          return (
                            <div
                              key={p}
                              style={{
                                width: '58px',
                                textAlign: 'center',
                                padding: '3px 0',
                                borderRadius: '4px',
                                fontSize: '12px',
                                fontWeight: isGreen ? 500 : 400,
                                background: isGreen ? '#E1F5EE' : '#EDEDEA',
                                color: isGreen ? '#085041' : '#888780',
                              }}
                            >
                              {price !== null ? `€${(price / 100).toFixed(2)}` : '—'}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )
                })}
              </div>

              {/* Show more */}
              {remaining > 0 && (
                <button
                  onClick={() => setPage((p) => p + 1)}
                  style={{
                    marginTop: '8px',
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: '13px',
                    color: '#2E86D8',
                    border: '0.5px solid #888780',
                    borderRadius: '8px',
                    padding: '10px',
                    background: 'transparent',
                    cursor: 'pointer',
                  }}
                >
                  {t('show_more', { count: Math.min(PAGE_SIZE, remaining) })}
                </button>
              )}

              {/* Footer */}
              <p
                style={{
                  fontSize: '12px',
                  color: '#888780',
                  textAlign: 'center',
                  marginTop: '10px',
                  padding: '0 0 2px',
                }}
              >
                {t('showing_count', {
                  shown: visibleItems.length,
                  total: stats.scannerItems.length,
                })}
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
