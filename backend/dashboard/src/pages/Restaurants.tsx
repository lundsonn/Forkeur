import { useEffect, useState, useCallback } from 'react'
import { getRestaurants, setChain } from '../api'
import type { Restaurant } from '../types'

const PAGE_SIZE = 100

export default function Restaurants() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([])
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'chain' | 'independent'>('all')

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    setLoading(true)
    setError(null)
    getRestaurants({ limit: PAGE_SIZE, search: debouncedSearch || undefined })
      .then(setRestaurants)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [debouncedSearch])

  const toggle = useCallback(async (r: Restaurant) => {
    const next = !r.is_chain
    setToggling((s) => new Set(s).add(r.id))
    try {
      await setChain(r.id, next)
      setRestaurants((prev) =>
        prev.map((x) => (x.id === r.id ? { ...x, is_chain: next } : x))
      )
    } catch (e) {
      setError(String(e))
    } finally {
      setToggling((s) => {
        const next = new Set(s)
        next.delete(r.id)
        return next
      })
    }
  }, [])

  const visible = restaurants.filter((r) => {
    if (filter === 'chain') return r.is_chain
    if (filter === 'independent') return !r.is_chain
    return true
  })

  const chainCount = restaurants.filter((r) => r.is_chain).length

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-stone-900">Restaurants</h1>
          <p className="text-sm text-stone-400 mt-0.5">
            {chainCount} chain{chainCount !== 1 ? 's' : ''} flagged
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Search by name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="border border-stone-200 rounded-lg px-3 py-2 text-sm w-64 outline-none focus:border-stone-400"
        />
        <div className="flex gap-1">
          {(['all', 'chain', 'independent'] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                filter === f
                  ? 'bg-stone-900 text-white'
                  : 'bg-stone-100 text-stone-500 hover:text-stone-900'
              }`}
            >
              {f === 'all' ? 'All' : f === 'chain' ? 'Chains' : 'Independent'}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mb-4 px-4 py-2 rounded-lg bg-red-50 text-red-700 text-sm">{error}</div>
      )}

      {loading ? (
        <div className="text-sm text-stone-400">Loading…</div>
      ) : (
        <div className="border border-stone-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-stone-200 bg-stone-50">
                <th className="text-left px-4 py-2.5 font-medium text-stone-500">Name</th>
                <th className="text-left px-4 py-2.5 font-medium text-stone-500">Area</th>
                <th className="text-left px-4 py-2.5 font-medium text-stone-500">Cuisine</th>
                <th className="text-right px-4 py-2.5 font-medium text-stone-500">Chain</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.id} className="border-b border-stone-100 last:border-0 hover:bg-stone-50">
                  <td className="px-4 py-2.5 font-medium text-stone-900">{r.name}</td>
                  <td className="px-4 py-2.5 text-stone-500">{r.neighborhood ?? '—'}</td>
                  <td className="px-4 py-2.5 text-stone-500">{r.cuisine ?? '—'}</td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      type="button"
                      onClick={() => toggle(r)}
                      disabled={toggling.has(r.id)}
                      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none disabled:opacity-50 ${
                        r.is_chain ? 'bg-orange-500' : 'bg-stone-200'
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition duration-200 ${
                          r.is_chain ? 'translate-x-4' : 'translate-x-0'
                        }`}
                      />
                    </button>
                  </td>
                </tr>
              ))}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-stone-400">
                    No restaurants found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
