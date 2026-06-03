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

  return (
    <div>
      <h1 className="text-xl font-bold text-stone-900 mb-6">Claims</h1>
      {error && <p className="text-red-600 text-sm mb-4">{error}</p>}
      {loading ? (
        <p className="text-stone-400 text-sm">Loading…</p>
      ) : claims.length === 0 ? (
        <p className="text-stone-400 text-sm">No pending claims.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {claims.map((claim) => (
            <div key={claim.id} className="border border-stone-200 rounded-xl p-4">
              <p className="font-semibold text-stone-900 text-sm">
                {claim.restaurants?.name ?? claim.restaurant_id}
              </p>
              <p className="text-xs text-stone-500 mt-0.5">{claim.owner_email}</p>
              {isSafeUrl(claim.direct_order_url) ? (
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
              )}
              <p className="text-xs text-stone-400 mt-1">
                {new Date(claim.claimed_at).toLocaleString('fr-BE')}
              </p>
              <div className="flex gap-2 mt-3">
                <button
                  disabled={acting === claim.id}
                  onClick={() => handleApprove(claim.id)}
                  className="px-3 py-1.5 rounded-lg bg-orange-500 hover:bg-orange-600 text-white text-xs font-semibold disabled:opacity-50 transition-colors"
                >
                  Approve
                </button>
                <button
                  disabled={acting === claim.id}
                  onClick={() => handleReject(claim.id)}
                  className="px-3 py-1.5 rounded-lg bg-stone-100 hover:bg-stone-200 text-stone-700 text-xs font-semibold disabled:opacity-50 transition-colors"
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
