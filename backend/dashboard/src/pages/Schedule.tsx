import { useEffect, useState } from 'react'
import { getSchedules, upsertSchedule, deleteSchedule } from '../api'
import type { ScheduleConfig, Platform } from '../types'

const PLATFORMS: Platform[] = ['ubereats', 'deliveroo', 'takeaway']

const DEFAULT_CRON: Record<Platform, string> = {
  ubereats: '0 */6 * * *',
  deliveroo: '0 */6 * * *',
  takeaway: '0 */6 * * *',
}

export default function Schedule() {
  const [schedules, setSchedules] = useState<Record<string, ScheduleConfig>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  useEffect(() => {
    getSchedules().then(list => {
      const map: Record<string, ScheduleConfig> = {}
      list.forEach(s => { map[s.platform] = s })
      setSchedules(map)
    })
  }, [])

  const save = async (platform: Platform) => {
    const cron = drafts[platform] ?? schedules[platform]?.cron ?? DEFAULT_CRON[platform]
    const enabled = schedules[platform]?.enabled ?? true
    const updated = await upsertSchedule({ platform, cron, enabled })
    setSchedules(prev => ({ ...prev, [platform]: updated }))
  }

  const toggle = async (platform: Platform) => {
    const s = schedules[platform]
    if (!s) return
    const updated = await upsertSchedule({ platform, cron: s.cron, enabled: !s.enabled })
    setSchedules(prev => ({ ...prev, [platform]: updated }))
  }

  const remove = async (platform: Platform) => {
    await deleteSchedule(platform)
    setSchedules(prev => { const n = { ...prev }; delete n[platform]; return n })
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Schedule</h1>
      <div className="flex flex-col gap-4">
        {PLATFORMS.map(platform => {
          const s = schedules[platform]
          return (
            <div key={platform} className="bg-white rounded-xl border border-slate-200 p-5">
              <div className="flex items-center justify-between mb-3">
                <span className="font-bold capitalize text-slate-800">{platform}</span>
                {s && (
                  <label className="flex items-center gap-2 text-sm text-slate-500">
                    <input
                      type="checkbox"
                      checked={s.enabled}
                      onChange={() => toggle(platform)}
                      className="w-4 h-4"
                    />
                    Enabled
                  </label>
                )}
              </div>
              <div className="flex gap-2">
                <input
                  className="flex-1 border border-slate-200 rounded-md px-3 py-2 text-sm font-mono"
                  placeholder={DEFAULT_CRON[platform]}
                  value={drafts[platform] ?? s?.cron ?? ''}
                  onChange={e => setDrafts(prev => ({ ...prev, [platform]: e.target.value }))}
                />
                <button
                  onClick={() => save(platform)}
                  className="bg-blue-600 text-white px-4 py-2 rounded-md text-sm hover:bg-blue-700"
                >
                  Save
                </button>
                {s && (
                  <button
                    onClick={() => remove(platform)}
                    className="text-red-500 border border-red-200 px-3 py-2 rounded-md text-sm hover:bg-red-50"
                  >
                    Remove
                  </button>
                )}
              </div>
              {s?.next_run && (
                <div className="mt-2 text-xs text-slate-400">
                  Next run: {new Date(s.next_run).toLocaleString()}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
