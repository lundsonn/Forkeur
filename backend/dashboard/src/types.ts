export type Platform = 'ubereats' | 'deliveroo' | 'takeaway'

export type RunStatus = 'running' | 'success' | 'failed' | 'blocked' | 'partial' | 'idle'

export interface ScraperRun {
  id: string
  platform: Platform
  status: RunStatus
  started_at: string
  finished_at: string | null
  records_saved: number
  error_msg: string | null
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
