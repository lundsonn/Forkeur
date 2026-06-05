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
 * Compute open/closed status for a given local Date (default: now).
 * opening_hours format: { mon: ["11:00", "22:30"], ... }
 * Handles midnight-crossing slots (close < open in minutes).
 */
export function getOpenStatus(hours: OpeningHours | null, now = new Date()): OpenStatus {
  if (!hours) return { status: 'unknown' }

  const dayKey = DAYS[now.getDay()]
  const slot = hours[dayKey]
  const currentMin = now.getHours() * 60 + now.getMinutes()

  if (slot) {
    const [open, close] = slot.map(toMinutes)
    const crossesMidnight = close < open

    if (crossesMidnight) {
      if (currentMin >= open || currentMin < close) {
        const closesAt = slot[1]
        return { status: 'open', closesAt }
      }
    } else {
      if (currentMin >= open && currentMin < close) {
        return { status: 'open', closesAt: slot[1] }
      }
    }
  }

  // Today's slot exists but hasn't started yet → opens later today
  if (slot) {
    const [open, close] = slot.map(toMinutes)
    const crossesMidnight = close < open
    if ((!crossesMidnight && currentMin < open) || (crossesMidnight && currentMin >= close && currentMin < open)) {
      return { status: 'closed', opensAt: slot[0] }
    }
  }

  // Closed today — find next opening
  for (let i = 1; i <= 7; i++) {
    const nextKey = DAYS[(now.getDay() + i) % 7]
    const nextSlot = hours[nextKey]
    if (nextSlot) {
      return { status: 'closed', opensAt: i === 1 ? `tomorrow ${nextSlot[0]}` : nextSlot[0] }
    }
  }

  return { status: 'closed', opensAt: null }
}
