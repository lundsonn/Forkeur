export type Platform =
  | 'ubereats'
  | 'deliveroo'
  | 'takeaway'
  | 'direct'
  | 'direct_menu'
  | 'dom_menu'
  | 'match'
  | 'enrich'
  | 'website_finder'

export type RunStatus = 'running' | 'success' | 'failed' | 'blocked' | 'partial' | 'idle'

export interface ScraperRun {
  id: string
  platform: Platform
  status: RunStatus
  started_at: string
  finished_at: string | null
  records_saved: number
  error_msg: string | null
  triggered_by: 'manual' | 'cron' | null
  peak_ram_mb: number | null
  avg_ram_mb: number | null
  phase_durations: Record<string, number> | null
  cooldown_hits: number
  items_attempted: number
  items_skipped: number
  items_failed: number
  concurrent_with: string[]
}

export interface ScraperStatus {
  platform: Platform
  status: RunStatus
  last_run: ScraperRun | null
}

export interface ScheduleConfig {
  platform: Platform
  cron: string
  enabled: boolean
  next_run: string | null
}

export interface Restaurant {
  id: string
  name: string
  slug: string
  cuisine: string | null
  neighborhood: string | null
  is_chain: boolean
}

export interface MenuItem {
  id: string
  listing_id: string
  title: string
  price: number | null
  catalog_name: string | null
}

export interface WsMessage {
  type: 'log' | 'done' | 'error'
  line?: string
  records?: number
  msg?: string
}
