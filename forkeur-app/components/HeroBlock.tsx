'use client'

import { useEffect, useState, useMemo } from 'react'
import { useTranslations } from 'next-intl'
import { findBestSavingExample } from '@/lib/savings'
import { PLATFORM_LABELS } from '@/lib/basket'
import type { RestaurantSummary } from '@/lib/queries'
import type { Platform } from '@/lib/basket'

type Props = {
  restaurants: RestaurantSummary[]
  neighborhood: string | null
}

const PLATFORM_COLOR: Record<Platform, string> = {
  uber_eats: 'bg-stone-800',
  deliveroo: 'bg-teal-500',
  takeaway: 'bg-orange-500',
  direct: 'bg-green-600',
}

function fmtFee(cents: number): string {
  if (cents === 0) return '€0'
  if (cents % 100 === 0) return `€${cents / 100}`
  return `€${(cents / 100).toFixed(2)}`
}

type SavingsExample = {
  name: string
  commune: string | null
  rows: { platform: Platform; feeCents: number }[]
  savingCents: number
  winner: Platform
}

function buildExamples(restaurants: RestaurantSummary[]): SavingsExample[] {
  const results: (SavingsExample & { savingCents: number })[] = []

  for (const r of restaurants) {
    if (r.listings.length < 2) continue
    if (!r.listings.some((l) => l.platform === 'direct')) continue
    const rows = r.listings
      .filter((l): l is typeof l & { delivery_fee_cents: number } => l.delivery_fee_cents !== null)
      .map((l) => ({ platform: l.platform, feeCents: l.delivery_fee_cents }))
      .sort((a, b) => a.feeCents - b.feeCents)
    if (rows.length < 2) continue
    const savingCents = rows[1].feeCents - rows[0].feeCents
    if (savingCents < 50) continue
    results.push({ name: r.name, commune: r.commune, rows, savingCents, winner: rows[0].platform })
  }

  return results
    .sort((a, b) => b.savingCents - a.savingCents)
    .slice(0, 5)
}

export default function HeroBlock({ restaurants }: Props) {
  const t = useTranslations()
  const examples = useMemo(() => buildExamples(restaurants), [restaurants])
  const [idx, setIdx] = useState(0)
  const [visible, setVisible] = useState(true)

  useEffect(() => {
    if (examples.length <= 1) return
    const interval = setInterval(() => {
      setVisible(false)
      setTimeout(() => {
        setIdx((i) => (i + 1) % examples.length)
        setVisible(true)
      }, 300)
    }, 7000)
    return () => clearInterval(interval)
  }, [examples.length])

  const ex = examples[idx] ?? null
  const maxFee = ex ? Math.max(...ex.rows.map((r) => r.feeCents)) : 1

  // fallback to old text example if no structured data
  const textExample = useMemo(() => findBestSavingExample(restaurants), [restaurants])

  return (
    <div className="py-4 flex flex-col gap-3">
      <p className="text-sm text-stone-500 text-center">{t('hero.credibility')}</p>

      {ex ? (
        <div
          className="rounded-2xl border border-stone-200 bg-white shadow-sm overflow-hidden transition-opacity duration-300"
          style={{ opacity: visible ? 1 : 0 }}
        >
          {/* header */}
          <div className="px-4 pt-3 pb-2 border-b border-stone-100">
            <p className="text-sm font-bold text-stone-900 truncate">{ex.name}</p>
            {ex.commune && (
              <p className="text-xs text-stone-400 capitalize">{ex.commune.replace(/-/g, ' ')}</p>
            )}
          </div>

          {/* platform rows */}
          <div className="px-4 py-3 space-y-2">
            {ex.rows.map((row) => {
              const isWinner = row.platform === ex.winner
              const barPct = maxFee > 0 ? Math.round((row.feeCents / maxFee) * 100) : 100
              return (
                <div key={row.platform} className="flex items-center gap-2">
                  <span
                    className={`text-xs font-medium w-20 shrink-0 ${isWinner ? 'text-orange-600' : 'text-stone-500'}`}
                  >
                    {PLATFORM_LABELS[row.platform]}
                  </span>
                  <div className="flex-1 h-2 bg-stone-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${isWinner ? 'bg-orange-400' : PLATFORM_COLOR[row.platform]}`}
                      style={{ width: `${barPct}%`, opacity: isWinner ? 1 : 0.4 }}
                    />
                  </div>
                  <span
                    className={`text-xs font-semibold w-12 text-right shrink-0 ${isWinner ? 'text-orange-600' : 'text-stone-400'}`}
                  >
                    {fmtFee(row.feeCents)}
                  </span>
                  <span className="w-3 shrink-0 text-xs">{isWinner ? '✓' : ''}</span>
                </div>
              )
            })}
          </div>

          {/* save badge + dots */}
          <div className="px-4 pb-3 flex items-center justify-between">
            <span className="text-xs font-bold text-green-700 bg-green-50 border border-green-200 px-2.5 py-1 rounded-full">
              {t('discovery.save_label', { amount: fmtFee(ex.savingCents) })}
            </span>
            {examples.length > 1 && (
              <div className="flex gap-1">
                {examples.map((_, i) => (
                  <button
                    key={i}
                    onClick={() => { setVisible(false); setTimeout(() => { setIdx(i); setVisible(true) }, 200) }}
                    className={`w-1.5 h-1.5 rounded-full transition-colors ${i === idx ? 'bg-orange-400' : 'bg-stone-200'}`}
                    aria-label={`Example ${i + 1}`}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      ) : textExample !== null ? (
        <>
          <p className="text-sm font-semibold text-stone-700 text-center">{t('hero.rightNow')}</p>
          <p className="text-center text-stone-900">
            <span className="font-bold">{textExample.restaurant.name}</span>
            {' '}
            <span className="text-green-600 font-semibold">€{(textExample.savingsCents / 100).toFixed(2)}</span>
            {' cheaper on '}
            <span className="font-semibold">{PLATFORM_LABELS[textExample.winner.platform]}</span>
          </p>
        </>
      ) : null}

      <p className="text-xs text-stone-400 text-center">{t('hero.neutrality')}</p>
    </div>
  )
}
