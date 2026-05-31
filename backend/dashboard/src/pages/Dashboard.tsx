import { useEffect, useState } from 'react'
import { getScraperStatus, getRuns } from '../api'
import type { ScraperStatus, ScraperRun } from '../types'

const STATUS_BADGE: Record<string, string> = {
  success: 'bg-emerald-50 text-emerald-700',
  failed: 'bg-red-50 text-red-600',
  blocked: 'bg-orange-50 text-orange-600',
  running: 'bg-blue-50 text-blue-600',
  partial: 'bg-yellow-50 text-yellow-700',
  idle: 'bg-stone-100 text-stone-500',
}

export default function Dashboard() {
  const [statuses, setStatuses] = useState<ScraperStatus[]>([])
  const [recentRuns, setRecentRuns] = useState<ScraperRun[]>([])

  useEffect(() => {
    getScraperStatus().then(setStatuses)
    getRuns(10).then(setRecentRuns)
  }, [])

  return (
    <div>
      <h1 className="text-2xl font-semibold text-stone-900 mb-6">Overview</h1>

      <div className="grid grid-cols-3 gap-4 mb-8">
        {statuses.map(s => (
          <div key={s.platform} className="bg-white rounded-2xl border border-stone-200 p-5">
            <div className="text-xs text-stone-400 capitalize mb-2">{s.platform}</div>
            <div className={`inline-block px-2 py-0.5 rounded-md text-xs font-medium ${STATUS_BADGE[s.status]}`}>
              {s.status}
            </div>
            {s.last_run && (
              <div className="mt-2 text-xs text-stone-400">
                {s.last_run.records_saved} restaurants · {new Date(s.last_run.started_at).toLocaleString()}
              </div>
            )}
          </div>
        ))}
      </div>

      <h2 className="text-sm font-medium text-stone-500 uppercase tracking-wide mb-3">Recent runs</h2>
      <div className="bg-white rounded-2xl border border-stone-200 divide-y divide-stone-100">
        {recentRuns.length === 0 && (
          <div className="px-5 py-8 text-sm text-stone-400 text-center">No runs yet</div>
        )}
        {recentRuns.map(run => (
          <div key={run.id} className="flex items-center gap-4 px-5 py-3 text-sm">
            <span className="capitalize w-24 font-medium text-stone-800">{run.platform}</span>
            <span className={`px-2 py-0.5 rounded-md text-xs ${STATUS_BADGE[run.status]}`}>{run.status}</span>
            <span className="text-stone-500">{run.records_saved} restaurants</span>
            <span className="text-stone-400 ml-auto text-xs">{new Date(run.started_at).toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
