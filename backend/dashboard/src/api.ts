import type { ScraperStatus, ScraperRun, ScheduleConfig, Restaurant, MenuItem } from './types'

const BASE = '/api'

export async function getScraperStatus(): Promise<ScraperStatus[]> {
  const res = await fetch(`${BASE}/scrapers/status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface RunOptions {
  test_mode?: boolean
  scrape_menus?: boolean
  max_menus?: number
}

export async function triggerRun(platform: string, options: RunOptions = {}): Promise<{ run_id: string }> {
  const res = await fetch(`${BASE}/scrapers/${platform}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function stopRun(platform: string): Promise<void> {
  const res = await fetch(`${BASE}/scrapers/${platform}/stop`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export async function getRuns(limit = 50, offset = 0): Promise<ScraperRun[]> {
  const res = await fetch(`${BASE}/runs?limit=${limit}&offset=${offset}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getSchedules(): Promise<ScheduleConfig[]> {
  const res = await fetch(`${BASE}/schedules`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function upsertSchedule(config: Omit<ScheduleConfig, 'next_run'>): Promise<ScheduleConfig> {
  const res = await fetch(`${BASE}/schedules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteSchedule(platform: string): Promise<void> {
  await fetch(`${BASE}/schedules/${platform}`, { method: 'DELETE' })
}

export async function getRestaurants(params?: { limit?: number; offset?: number; search?: string }): Promise<Restaurant[]> {
  const q = new URLSearchParams()
  if (params?.limit) q.set('limit', String(params.limit))
  if (params?.offset) q.set('offset', String(params.offset))
  if (params?.search) q.set('search', params.search)
  const res = await fetch(`${BASE}/data/restaurants?${q}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getMenuItems(listingId: string): Promise<MenuItem[]> {
  const res = await fetch(`${BASE}/data/menu-items/${listingId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
