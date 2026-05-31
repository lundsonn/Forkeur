import { useEffect, useState } from 'react'
import { getRestaurants } from '../api'
import type { Restaurant } from '../types'

export default function Data() {
  const [restaurants, setRestaurants] = useState<Restaurant[]>([])
  const [search, setSearch] = useState('')

  const load = (q: string) => getRestaurants({ limit: 100, search: q || undefined }).then(setRestaurants)

  useEffect(() => { load('') }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Data Browser</h1>
      <input
        className="w-full max-w-md border border-slate-200 rounded-md px-3 py-2 text-sm mb-4"
        placeholder="Search restaurants..."
        value={search}
        onChange={e => { setSearch(e.target.value); load(e.target.value) }}
      />
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Name</th>
              <th className="text-left px-4 py-3">Slug</th>
              <th className="text-left px-4 py-3">Cuisine</th>
              <th className="text-left px-4 py-3">Neighborhood</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {restaurants.map(r => (
              <tr key={r.id} className="hover:bg-slate-50">
                <td className="px-4 py-3 font-medium">{r.name}</td>
                <td className="px-4 py-3 text-slate-500 font-mono text-xs">{r.slug}</td>
                <td className="px-4 py-3 text-slate-500">{r.cuisine ?? '—'}</td>
                <td className="px-4 py-3 text-slate-500">{r.neighborhood ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
