import { useEffect, useState } from 'react'
import { getSchedules, upsertSchedule, deleteSchedule } from '../api'
import type { ScheduleConfig, Platform } from '../types'

const ALL_SCRAPERS: { platform: Platform; label: string; description: string }[] = [
  { platform: 'ubereats',       label: 'UberEats',       description: 'Full restaurant + menu scrape' },
  { platform: 'deliveroo',      label: 'Deliveroo',      description: 'Full restaurant + menu scrape (multi-zone)' },
  { platform: 'takeaway',       label: 'Takeaway',       description: 'Full restaurant + menu scrape' },
  { platform: 'direct',         label: 'Direct',         description: 'Enrich restaurant websites + Google Maps discovery' },
  { platform: 'direct_menu',    label: 'Direct Menu',    description: 'API scrapers for ordering sites (Square, Odoo, Piki)' },
  { platform: 'dom_menu',       label: 'DOM Menu',       description: 'Playwright scraper for menu/website listings' },
  { platform: 'match',          label: 'Match',          description: 'Cross-platform restaurant de-duplication' },
  { platform: 'enrich',         label: 'Enrich',         description: 'Contact enrichment (phone, social links)' },
  { platform: 'website_finder', label: 'Website Finder', description: 'Discover direct ordering websites' },
]

const DEFAULT_CRON: Record<Platform, string> = {
  ubereats:       '0 */6 * * *',
  deliveroo:      '2 */6 * * *',
  takeaway:       '4 */6 * * *',
  direct:         '0 1 * * 1',
  direct_menu:    '30 1 * * 1',
  dom_menu:       '0 2 * * 1',
  match:          '0 20 * * *',
  enrich:         '0 3 * * 1',
  website_finder: '0 4 * * 1',
}
const FALLBACK_CRON = '0 2 * * *'

export default function Schedule() {
  const [schedules, setSchedules] = useState<Record<string, ScheduleConfig>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [adding, setAdding] = useState<Set<string>>(new Set())

  useEffect(() => {
    getSchedules().then(list => {
      const map: Record<string, ScheduleConfig> = {}
      list.forEach(s => { map[s.platform] = s })
      setSchedules(map)
    })
  }, [])

  const save = async (platform: Platform) => {
    const cron = drafts[platform] ?? schedules[platform]?.cron ?? DEFAULT_CRON[platform] ?? FALLBACK_CRON
    const enabled = schedules[platform]?.enabled ?? true
    const updated = await upsertSchedule({ platform, cron, enabled })
    setSchedules(prev => ({ ...prev, [platform]: updated }))
    setAdding(prev => { const n = new Set(prev); n.delete(platform); return n })
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
    setDrafts(prev => { const n = { ...prev }; delete n[platform]; return n })
  }

  const startAdding = (platform: Platform) => {
    setAdding(prev => new Set([...prev, platform]))
    setDrafts(prev => ({ ...prev, [platform]: DEFAULT_CRON[platform] ?? FALLBACK_CRON }))
  }

  const cancelAdding = (platform: Platform) => {
    setAdding(prev => { const n = new Set(prev); n.delete(platform); return n })
    setDrafts(prev => { const n = { ...prev }; delete n[platform]; return n })
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Schedule</h1>
      <div className="flex flex-col gap-4">
        {ALL_SCRAPERS.map(({ platform, label, description }) => {
          const s = schedules[platform]
          const isAdding = adding.has(platform)
          const hasSchedule = !!s

          return (
            <div key={platform} className="bg-white rounded-xl border border-slate-200 p-5">
              <div className="flex items-center justify-between mb-1">
                <div>
                  <span className="font-bold text-slate-800">{label}</span>
                  <span className="ml-2 text-xs text-slate-400">{description}</span>
                </div>
                <div className="flex items-center gap-3">
                  {hasSchedule && (
                    <label className="flex items-center gap-2 text-sm text-slate-500 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={s.enabled}
                        onChange={() => toggle(platform)}
                        className="w-4 h-4"
                      />
                      Enabled
                    </label>
                  )}
                  {!hasSchedule && !isAdding && (
                    <button
                      onClick={() => startAdding(platform)}
                      className="text-sm text-blue-600 border border-blue-200 px-3 py-1.5 rounded-md hover:bg-blue-50"
                    >
                      + Add schedule
                    </button>
                  )}
                </div>
              </div>

              {(hasSchedule || isAdding) && (
                <div className="mt-3 flex gap-2">
                  <input
                    className="flex-1 border border-slate-200 rounded-md px-3 py-2 text-sm font-mono"
                    placeholder={DEFAULT_CRON[platform] ?? FALLBACK_CRON}
                    value={drafts[platform] ?? s?.cron ?? ''}
                    onChange={e => setDrafts(prev => ({ ...prev, [platform]: e.target.value }))}
                  />
                  <button
                    onClick={() => save(platform)}
                    className="bg-blue-600 text-white px-4 py-2 rounded-md text-sm hover:bg-blue-700"
                  >
                    Save
                  </button>
                  {isAdding && !hasSchedule ? (
                    <button
                      onClick={() => cancelAdding(platform)}
                      className="text-slate-500 border border-slate-200 px-3 py-2 rounded-md text-sm hover:bg-slate-50"
                    >
                      Cancel
                    </button>
                  ) : (
                    <button
                      onClick={() => remove(platform)}
                      className="text-red-500 border border-red-200 px-3 py-2 rounded-md text-sm hover:bg-red-50"
                    >
                      Remove
                    </button>
                  )}
                </div>
              )}

              {s?.next_run && (
                <div className="mt-2 text-xs text-slate-400">
                  Next run: {new Date(s.next_run).toLocaleString()}
                </div>
              )}

              {!hasSchedule && !isAdding && (
                <div className="mt-1 text-xs text-slate-400">No schedule configured</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
