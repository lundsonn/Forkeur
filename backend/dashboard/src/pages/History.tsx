import { useEffect, useState } from 'react'
import { getRuns } from '../api'
import type { ScraperRun } from '../types'

const STATUS_BADGE: Record<string, string> = {
  success: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  blocked: 'bg-orange-100 text-orange-800',
  running: 'bg-blue-100 text-blue-800',
  partial: 'bg-yellow-100 text-yellow-800',
}

export default function History() {
  const [runs, setRuns] = useState<ScraperRun[]>([])
  const [offset, setOffset] = useState(0)

  const load = (o: number) => getRuns(50, o).then(setRuns)

  useEffect(() => { load(0) }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Run History</h1>
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Platform</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Records</th>
              <th className="text-left px-4 py-3">Duration</th>
              <th className="text-left px-4 py-3">Started</th>
              <th className="text-left px-4 py-3">Error</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {runs.map(run => {
              const duration = run.finished_at
                ? Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000)
                : null
              return (
                <tr key={run.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium capitalize">{run.platform}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs ${STATUS_BADGE[run.status] ?? 'bg-slate-100'}`}>
                      {run.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{run.records_saved}</td>
                  <td className="px-4 py-3 text-slate-500">{duration !== null ? `${duration}s` : '—'}</td>
                  <td className="px-4 py-3 text-slate-400">{new Date(run.started_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-red-500 text-xs max-w-xs truncate">{run.error_msg ?? ''}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="flex gap-2 mt-4">
        <button
          onClick={() => { const o = Math.max(0, offset - 50); setOffset(o); load(o) }}
          disabled={offset === 0}
          className="px-3 py-1.5 text-sm border rounded disabled:opacity-40"
        >← Prev</button>
        <button
          onClick={() => { const o = offset + 50; setOffset(o); load(o) }}
          className="px-3 py-1.5 text-sm border rounded"
        >Next →</button>
      </div>
    </div>
  )
}
