import { useEffect, useState } from 'react'
import { getRuns } from '../api'
import type { ScraperRun } from '../types'

const STATUS_BADGE: Record<string, string> = {
  success: 'bg-green-100 text-green-800',
  failed:  'bg-red-100 text-red-800',
  blocked: 'bg-orange-100 text-orange-800',
  running: 'bg-blue-100 text-blue-800',
  partial: 'bg-yellow-100 text-yellow-800',
}

const TRIGGER_BADGE: Record<string, string> = {
  manual: 'bg-purple-100 text-purple-700',
  cron:   'bg-slate-100 text-slate-600',
}

function fmt(ms: number): string {
  if (ms < 60) return `${ms}s`
  const m = Math.floor(ms / 60), s = ms % 60
  return s ? `${m}m${s}s` : `${m}m`
}

function PhasePill({ label, secs }: { label: string; secs: number }) {
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-slate-100 rounded text-xs text-slate-600 mr-1 mb-0.5">
      <span className="font-medium">{label}</span>
      <span>{fmt(Math.round(secs))}</span>
    </span>
  )
}

function RunRow({ run }: { run: ScraperRun }) {
  const [open, setOpen] = useState(false)
  const duration = run.finished_at
    ? Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000)
    : null

  const hasPhases = run.phase_durations && Object.keys(run.phase_durations).length > 0
  const hasItems = run.items_attempted > 0
  const hasRam = run.peak_ram_mb != null

  return (
    <>
      <tr
        className={`hover:bg-slate-50 ${hasPhases ? 'cursor-pointer' : ''}`}
        onClick={() => hasPhases && setOpen(o => !o)}
      >
        <td className="px-4 py-3">
          <span className="font-medium capitalize">{run.platform}</span>
          {run.triggered_by && (
            <span className={`ml-2 px-1.5 py-0.5 rounded text-xs ${TRIGGER_BADGE[run.triggered_by] ?? 'bg-slate-100'}`}>
              {run.triggered_by}
            </span>
          )}
        </td>
        <td className="px-4 py-3">
          <span className={`px-2 py-0.5 rounded text-xs ${STATUS_BADGE[run.status] ?? 'bg-slate-100'}`}>
            {run.status}
          </span>
        </td>
        <td className="px-4 py-3 text-slate-600">{run.records_saved}</td>
        <td className="px-4 py-3 text-slate-500">{duration !== null ? fmt(duration) : '—'}</td>
        <td className="px-4 py-3 text-slate-500 whitespace-nowrap">
          {hasRam ? `${run.peak_ram_mb} MB` : '—'}
        </td>
        <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">
          {hasItems ? (
            <span>
              {run.items_attempted} tried
              {run.items_skipped > 0 && <span className="text-amber-600 ml-1">{run.items_skipped} skip</span>}
              {run.items_failed  > 0 && <span className="text-red-600 ml-1">{run.items_failed} fail</span>}
            </span>
          ) : '—'}
        </td>
        <td className="px-4 py-3 text-slate-400 text-xs">{new Date(run.started_at).toLocaleString()}</td>
        <td className="px-4 py-3 text-red-500 text-xs max-w-xs truncate">{run.error_msg ?? ''}</td>
      </tr>
      {open && hasPhases && (
        <tr className="bg-slate-50">
          <td colSpan={8} className="px-6 pb-3 pt-1">
            <div className="text-xs text-slate-500 mb-1 font-medium">Phase breakdown</div>
            {Object.entries(run.phase_durations!).map(([k, v]) => (
              <PhasePill key={k} label={k} secs={v} />
            ))}
            {run.cooldown_hits > 0 && (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-amber-50 rounded text-xs text-amber-700 mr-1">
                {run.cooldown_hits}× cooldown
              </span>
            )}
            {(run.concurrent_with?.length ?? 0) > 0 && (
              <span className="text-xs text-slate-400 ml-1">concurrent with: {run.concurrent_with.join(', ')}</span>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

export default function History() {
  const [runs, setRuns] = useState<ScraperRun[]>([])
  const [offset, setOffset] = useState(0)
  const [filter, setFilter] = useState<'all' | 'manual' | 'cron'>('all')

  const load = (o: number) => getRuns(50, o).then(setRuns)
  useEffect(() => { load(0) }, [])

  const visible = filter === 'all' ? runs : runs.filter(r => r.triggered_by === filter)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Run History</h1>
        <div className="flex gap-1">
          {(['all', 'manual', 'cron'] as const).map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 text-sm rounded border ${filter === f ? 'bg-slate-800 text-white border-slate-800' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>
      <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Platform</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Records</th>
              <th className="text-left px-4 py-3">Duration</th>
              <th className="text-left px-4 py-3">Peak RAM</th>
              <th className="text-left px-4 py-3">Items</th>
              <th className="text-left px-4 py-3">Started</th>
              <th className="text-left px-4 py-3">Error</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {visible.map(run => <RunRow key={run.id} run={run} />)}
          </tbody>
        </table>
      </div>
      <div className="flex gap-2 mt-4 items-center">
        <button
          onClick={() => { const o = Math.max(0, offset - 50); setOffset(o); load(o) }}
          disabled={offset === 0}
          className="px-3 py-1.5 text-sm border rounded disabled:opacity-40"
        >← Prev</button>
        <span className="text-sm text-slate-500">offset {offset}</span>
        <button
          onClick={() => { const o = offset + 50; setOffset(o); load(o) }}
          className="px-3 py-1.5 text-sm border rounded"
        >Next →</button>
      </div>
    </div>
  )
}
