import type { ScraperStatus } from '../types'

const PLATFORM_COLORS: Record<string, string> = {
  ubereats: '#06C167',
  deliveroo: '#00CCBC',
  takeaway: '#FF8000',
}

const STATUS_DOT: Record<string, string> = {
  idle: '#d1d5db',
  running: '#3b82f6',
  success: '#06C167',
  failed: '#ef4444',
  blocked: '#f97316',
  partial: '#eab308',
}

interface Props {
  status: ScraperStatus
  onRun: (fullRun?: boolean) => void
  onStop: () => void
  isRunning: boolean
}

export default function ScraperCard({ status, onRun, onStop, isRunning }: Props) {
  const dotColor = STATUS_DOT[status.status] ?? '#d1d5db'
  const platformColor = PLATFORM_COLORS[status.platform] ?? '#d1d5db'
  const last = status.last_run
  const isBad = status.status === 'failed' || status.status === 'blocked'

  const duration = last?.finished_at && last?.started_at
    ? Math.round((new Date(last.finished_at).getTime() - new Date(last.started_at).getTime()) / 1000)
    : null

  return (
    <div className={`bg-white rounded-2xl border p-5 flex flex-col gap-4 ${isBad ? 'border-red-200' : 'border-stone-200'}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: platformColor }} />
          <span className="font-semibold text-stone-900 capitalize">{status.platform}</span>
        </div>
        <span
          className={`w-2 h-2 rounded-full ${isRunning ? 'animate-pulse' : ''}`}
          style={{ backgroundColor: isRunning ? '#3b82f6' : dotColor }}
        />
      </div>

      <div className="min-h-[2.5rem]">
        {last ? (
          <div className="space-y-0.5">
            <div className="text-sm font-medium text-stone-800">{last.records_saved} restaurants</div>
            <div className="text-xs text-stone-400">
              {duration !== null ? `${duration}s · ` : ''}{new Date(last.started_at).toLocaleTimeString()}
            </div>
            {last.error_msg && <div className="text-xs text-red-500 truncate mt-1">{last.error_msg}</div>}
          </div>
        ) : (
          <div className="text-sm text-stone-400">Never run</div>
        )}
      </div>

      {isRunning ? (
        <button
          onClick={onStop}
          className="w-full rounded-xl py-2.5 text-sm font-medium bg-red-500 hover:bg-red-600 text-white transition-colors"
        >
          ⏹ Stop
        </button>
      ) : (
        <div className="flex gap-2">
          <button
            onClick={() => onRun(false)}
            className={`flex-1 rounded-xl py-2.5 text-sm font-medium transition-colors ${
              isBad
                ? 'bg-red-500 hover:bg-red-600 text-white'
                : 'bg-stone-900 hover:bg-stone-800 text-white'
            }`}
          >
            {isBad ? '↺ Retry' : '▶ Quick'}
          </button>
          <button
            onClick={() => onRun(true)}
            title="Scrape restaurants + menus"
            className="flex-1 rounded-xl py-2.5 text-sm font-medium transition-colors bg-orange-500 hover:bg-orange-600 text-white"
          >
            ▶▶ Full
          </button>
        </div>
      )}
    </div>
  )
}
