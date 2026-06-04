import type { ScraperStatus, ScraperRun, ScheduleConfig, Restaurant, MenuItem } from './types'

const BASE = '/api'

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('admin_token') ?? ''
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(url, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers as Record<string, string> ?? {}) },
  })
  if (res.status === 401) {
    localStorage.removeItem('admin_token')
    window.location.reload()
  }
  return res
}

export async function getScraperStatus(): Promise<ScraperStatus[]> {
  const res = await apiFetch(`${BASE}/scrapers/status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface RunOptions {
  test_mode?: boolean
  scrape_menus?: boolean
  max_menus?: number
}

export async function triggerRun(platform: string, options: RunOptions = {}): Promise<{ run_id: string }> {
  const res = await apiFetch(`${BASE}/scrapers/${platform}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function stopRun(platform: string): Promise<void> {
  const res = await apiFetch(`${BASE}/scrapers/${platform}/stop`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export async function getRuns(limit = 50, offset = 0): Promise<ScraperRun[]> {
  const res = await apiFetch(`${BASE}/runs?limit=${limit}&offset=${offset}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getSchedules(): Promise<ScheduleConfig[]> {
  const res = await apiFetch(`${BASE}/schedules`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function upsertSchedule(config: Omit<ScheduleConfig, 'next_run'>): Promise<ScheduleConfig> {
  const res = await apiFetch(`${BASE}/schedules`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteSchedule(platform: string): Promise<void> {
  await apiFetch(`${BASE}/schedules/${platform}`, { method: 'DELETE' })
}

export async function getRestaurants(params?: { limit?: number; offset?: number; search?: string }): Promise<Restaurant[]> {
  const q = new URLSearchParams()
  if (params?.limit) q.set('limit', String(params.limit))
  if (params?.offset) q.set('offset', String(params.offset))
  if (params?.search) q.set('search', params.search)
  const res = await apiFetch(`${BASE}/data/restaurants?${q}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getMenuItems(listingId: string): Promise<MenuItem[]> {
  const res = await apiFetch(`${BASE}/data/menu-items/${listingId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface Claim {
  id: string
  restaurant_id: string | null
  owner_email: string
  direct_order_url: string | null
  inquiry_type: 'add_url' | 'new_listing' | 'remove'
  restaurant_name_free: string | null
  verified: boolean
  claimed_at: string
  restaurants?: { name: string } | null
}

export async function getClaims(verified?: boolean): Promise<Claim[]> {
  const qs = verified !== undefined ? `?verified=${verified}` : ''
  const res = await apiFetch(`${BASE}/claims${qs}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function approveClaim(id: string): Promise<void> {
  const res = await apiFetch(`${BASE}/claims/${id}/approve`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}

export async function rejectClaim(id: string): Promise<void> {
  const res = await apiFetch(`${BASE}/claims/${id}/reject`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
}
