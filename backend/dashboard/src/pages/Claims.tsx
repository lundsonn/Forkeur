import { useEffect, useState } from 'react'
import { getClaims, approveClaim, rejectClaim, type Claim } from '../api'

function isSafeUrl(url: string): boolean {
  try {
    const u = new URL(url)
    return u.protocol === 'https:' || u.protocol === 'http:'
  } catch {
    return false
  }
}

export default function Claims() {
  const [claims, setClaims] = useState<Claim[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [acting, setActing] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await getClaims(false) // pending only
      setClaims(data)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function handleApprove(id: string) {
    if (!window.confirm('Approuver cette demande ? Le lien de commande directe sera publié.')) return
    setActing(id)
    setError(null)
    try {
      await approveClaim(id)
      setClaims((prev) => prev.filter((c) => c.id !== id))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setActing(null)
    }
  }

  async function handleReject(id: string) {
    setActing(id)
    setError(null)
    try {
      await rejectClaim(id)
      setClaims((prev) => prev.filter((c) => c.id !== id))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setActing(null)
    }
  }

  const BADGE: Record<string, { label: string; cls: string }> = {
    add_url:     { label: 'Add URL',      cls: 'bg-orange-50 text-orange-700 border-orange-200' },
    new_listing: { label: 'New listing',  cls: 'bg-blue-50 text-blue-700 border-blue-200' },
    remove:      { label: 'Remove',       cls: 'bg-red-50 text-red-700 border-red-200' },
  }

  return (
    <div>
      <h1 className="text-xl font-bold text-stone-900 mb-6">Owner inquiries</h1>
      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}
      {loading ? (
        <p className="text-stone-400 text-sm">Loading…</p>
      ) : claims.length === 0 ? (
        <p className="text-stone-400 text-sm">No pending inquiries.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {claims.map((claim) => {
            const badge = BADGE[claim.inquiry_type] ?? BADGE.add_url
            const restaurantLabel = claim.restaurants?.name ?? claim.restaurant_name_free ?? claim.restaurant_id ?? '—'
            return (
              <div key={claim.id} className="border border-stone-200 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-[10px] font-semibold uppercase tracking-wide border rounded-full px-2 py-0.5 ${badge.cls}`}>
                    {badge.label}
                  </span>
                  <p className="font-semibold text-stone-900 text-sm">{restaurantLabel}</p>
                </div>
                <p className="text-xs text-stone-500">{claim.owner_email}</p>
                {claim.direct_order_url && (
                  isSafeUrl(claim.direct_order_url) ? (
                    <a
                      href={claim.direct_order_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-orange-600 hover:underline mt-1 block truncate"
                    >
                      {claim.direct_order_url}
                    </a>
                  ) : (
                    <span className="text-xs text-stone-400 mt-1 block truncate">
                      {claim.direct_order_url}
                    </span>
                  )
                )}
                <p className="text-xs text-stone-400 mt-1">
                  {new Date(claim.claimed_at).toLocaleString('fr-BE')}
                </p>
                <div className="flex gap-2 mt-3">
                  <button
                    type="button"
                    disabled={acting === claim.id}
                    onClick={() => handleApprove(claim.id)}
                    className="px-3 py-1.5 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-xs font-semibold disabled:opacity-50 transition-colors"
                  >
                    {claim.inquiry_type === 'add_url' ? 'Approve & publish' : 'Mark handled'}
                  </button>
                  <button
                    type="button"
                    disabled={acting === claim.id}
                    onClick={() => handleReject(claim.id)}
                    className="px-3 py-1.5 rounded-lg bg-stone-100 hover:bg-stone-200 text-stone-700 text-xs font-semibold disabled:opacity-50 transition-colors"
                  >
                    Dismiss
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
