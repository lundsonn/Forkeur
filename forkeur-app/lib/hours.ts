import type { OpeningHours } from '@/lib/queries'

const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'] as const

function toMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}

export type OpenStatus =
  | { status: 'open'; closesAt: string }
  | { status: 'closed'; opensAt: string | null }
  | { status: 'unknown' }

/**
 * Normalize a day's opening_hours entry into a list of [open, close] slots.
 * Accepts both shapes for backward compatibility:
 *   - legacy single-slot: ["11:00", "22:30"]
 *   - new multi-slot:     [["11:00","14:30"], ["18:00","22:30"]]
 * Returns [] for null/undefined/empty/invalid input.
 */
export function normalizeSlots(raw: unknown): [string, string][] {
  if (!Array.isArray(raw) || raw.length === 0) return []

  // Legacy single-slot: first element is a string → ["11:00","22:30"]
  if (typeof raw[0] === 'string') {
    return raw.length === 2 && typeof raw[1] === 'string' ? [[raw[0], raw[1]]] : []
  }

  // New multi-slot: array of [open, close] pairs.
  return (raw as unknown[]).filter(
    (s): s is [string, string] =>
      Array.isArray(s) && s.length === 2 && typeof s[0] === 'string' && typeof s[1] === 'string'
  )
}

/**
 * Compute open/closed status for a given local Date (default: now).
 * opening_hours format (per day): legacy ["11:00","22:30"] or
 * multi-slot [["11:00","14:30"],["18:00","22:30"]] — both supported.
 * Handles midnight-crossing slots (close < open in minutes) per slot.
 */
export function getOpenStatus(hours: OpeningHours | null, now = new Date()): OpenStatus {
  if (!hours) return { status: 'unknown' }

  const dayKey = DAYS[now.getDay()]
  const slots = normalizeSlots(hours[dayKey])
  const currentMin = now.getHours() * 60 + now.getMinutes()

  // OPEN if current time falls within ANY slot today.
  for (const slot of slots) {
    const [open, close] = slot.map(toMinutes)
    const crossesMidnight = close < open
    if (crossesMidnight) {
      if (currentMin >= open || currentMin < close) {
        return { status: 'open', closesAt: slot[1] }
      }
    } else if (currentMin >= open && currentMin < close) {
      return { status: 'open', closesAt: slot[1] }
    }
  }

  // Not open now — does a slot open later today? Pick the EARLIEST future open.
  let earliestOpen: { min: number; label: string } | null = null
  for (const slot of slots) {
    const [open, close] = slot.map(toMinutes)
    const crossesMidnight = close < open
    const opensLaterToday =
      (!crossesMidnight && currentMin < open) ||
      (crossesMidnight && currentMin >= close && currentMin < open)
    if (opensLaterToday && (earliestOpen === null || open < earliestOpen.min)) {
      earliestOpen = { min: open, label: slot[0] }
    }
  }
  if (earliestOpen) {
    return { status: 'closed', opensAt: earliestOpen.label }
  }

  // Closed today — find next opening on a future day.
  for (let i = 1; i <= 7; i++) {
    const nextKey = DAYS[(now.getDay() + i) % 7]
    const nextSlots = normalizeSlots(hours[nextKey])
    if (nextSlots.length > 0) {
      const opensAt = nextSlots[0][0]
      return { status: 'closed', opensAt: i === 1 ? `tomorrow ${opensAt}` : opensAt }
    }
  }

  return { status: 'closed', opensAt: null }
}
