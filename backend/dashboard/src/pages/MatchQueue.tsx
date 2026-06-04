import { useEffect, useState } from 'react'
import { getMatchQueue, resolveMatch, type MatchDecision } from '../api'

function fmt(n: number | undefined): string {
  if (n === undefined || n === null) return '—'
  return n.toFixed(3)
}

function fmtBool(v: boolean | undefined): string {
  if (v === undefined || v === null) return '—'
  return v ? 'yes' : 'no'
}

function fmtDist(m: number | undefined): string {
  if (m === undefined || m === null) return '—'
  return `${Math.round(m)} m`
}

export default function MatchQueue() {
  const [decisions, setDecisions] = useState<MatchDecision[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [acting, setActing] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await getMatchQueue()
      setDecisions(data)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function handleResolve(id: string, approve: boolean) {
    const label = approve ? 'Approve & merge' : 'Reject'
    if (!window.confirm(`${label} this match decision?`)) return
    setActing(id)
    setError(null)
    try {
      await resolveMatch(id, approve)
      setDecisions((prev) => prev.filter((d) => d.id !== id))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setActing(null)
    }
  }

  return (
    <div>
      <h1 className="text-xl font-bold text-stone-900 mb-6">Match review queue</h1>
      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}
      {loading ? (
        <p className="text-stone-400 text-sm">Loading…</p>
      ) : decisions.length === 0 ? (
        <p className="text-stone-400 text-sm">No pending match decisions.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {decisions.map((d) => {
            const f = d.features ?? {}
            return (
              <div key={d.id} className="border border-stone-200 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[10px] font-semibold uppercase tracking-wide border rounded-full px-2 py-0.5 bg-orange-50 text-orange-700 border-orange-200">
                    queued
                  </span>
                  <span className="font-semibold text-stone-900 text-sm">
                    Score: {d.score.toFixed(3)}
                  </span>
                </div>

                {/* Survivor / Loser — names from features, UUIDs as secondary text */}
                <div className="grid grid-cols-2 gap-x-4 mb-3">
                  <div>
                    <p className="text-[10px] font-semibold text-stone-400 uppercase tracking-wide mb-0.5">Survivor</p>
                    <p className="text-sm font-semibold text-stone-900 truncate">
                      {f.survivor_name ?? d.survivor_id}
                    </p>
                    {f.survivor_name && (
                      <p className="text-[10px] text-stone-400 font-mono truncate">{d.survivor_id}</p>
                    )}
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold text-stone-400 uppercase tracking-wide mb-0.5">Loser</p>
                    <p className="text-sm font-semibold text-stone-900 truncate">
                      {f.loser_name ?? d.loser_id}
                    </p>
                    {f.loser_name && (
                      <p className="text-[10px] text-stone-400 font-mono truncate">{d.loser_id}</p>
                    )}
                  </div>
                </div>

                {/* Key features from the jsonb column */}
                <div className="grid grid-cols-4 gap-x-4 gap-y-1 mb-3">
                  <div>
                    <p className="text-[10px] font-semibold text-stone-400 uppercase tracking-wide">name_sim</p>
                    <p className="text-xs text-stone-700">{fmt(f.name_sim as number)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold text-stone-400 uppercase tracking-wide">website_match</p>
                    <p className="text-xs text-stone-700">{fmtBool(f.website_match as boolean)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold text-stone-400 uppercase tracking-wide">phone_match</p>
                    <p className="text-xs text-stone-700">{fmtBool(f.phone_match as boolean)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-semibold text-stone-400 uppercase tracking-wide">geo_dist</p>
                    <p className="text-xs text-stone-700">{fmtDist(f.geo_dist as number)}</p>
                  </div>
                </div>

                <p className="text-xs text-stone-400 mb-3">
                  {new Date(d.created_at).toLocaleString('fr-BE')}
                </p>

                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={acting === d.id}
                    onClick={() => handleResolve(d.id, true)}
                    className="px-3 py-1.5 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-xs font-semibold disabled:opacity-50 transition-colors"
                  >
                    Approve &amp; merge
                  </button>
                  <button
                    type="button"
                    disabled={acting === d.id}
                    onClick={() => handleResolve(d.id, false)}
                    className="px-3 py-1.5 rounded-lg bg-stone-100 hover:bg-stone-200 text-stone-700 text-xs font-semibold disabled:opacity-50 transition-colors"
                  >
                    Reject
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
