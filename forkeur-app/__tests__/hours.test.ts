import { describe, it, expect } from 'vitest'
import { getOpenStatus, normalizeSlots } from '../lib/hours'

// 2026-06-15 is a Monday. Construct local times on that day so DAYS[getDay()] === 'mon'.
const monAt = (h: number, m = 0) => new Date(2026, 5, 15, h, m)

describe('normalizeSlots', () => {
  it('wraps a legacy single-slot into one pair', () => {
    expect(normalizeSlots(['11:00', '22:30'])).toEqual([['11:00', '22:30']])
  })

  it('passes through a multi-slot list', () => {
    expect(normalizeSlots([['11:00', '14:30'], ['18:00', '22:30']])).toEqual([
      ['11:00', '14:30'],
      ['18:00', '22:30'],
    ])
  })

  it('returns [] for null/undefined/empty', () => {
    expect(normalizeSlots(null)).toEqual([])
    expect(normalizeSlots(undefined)).toEqual([])
    expect(normalizeSlots([])).toEqual([])
  })

  it('filters invalid slots out of a multi-slot list', () => {
    expect(normalizeSlots([['11:00', '14:30'], ['18:00'], 'nope'])).toEqual([['11:00', '14:30']])
  })
})

describe('getOpenStatus — legacy single-slot', () => {
  const hours = { mon: ['11:00', '22:30'] as [string, string] }

  it('is open at 12:00', () => {
    const s = getOpenStatus(hours, monAt(12))
    expect(s).toEqual({ status: 'open', closesAt: '22:30' })
  })

  it('is closed at 23:00 (after close)', () => {
    const s = getOpenStatus(hours, monAt(23))
    expect(s.status).toBe('closed')
  })
})

describe('getOpenStatus — multi-slot (lunch + dinner)', () => {
  const hours = { mon: [['11:00', '14:30'], ['18:00', '22:30']] as [string, string][] }

  it('is open at 12:00 (lunch slot)', () => {
    const s = getOpenStatus(hours, monAt(12))
    expect(s).toEqual({ status: 'open', closesAt: '14:30' })
  })

  it('is CLOSED at 16:00 (the gap between slots)', () => {
    const s = getOpenStatus(hours, monAt(16))
    expect(s).toEqual({ status: 'closed', opensAt: '18:00' })
  })

  it('is open at 19:00 (dinner slot)', () => {
    const s = getOpenStatus(hours, monAt(19))
    expect(s).toEqual({ status: 'open', closesAt: '22:30' })
  })

  it('before any slot opens, picks the earliest future slot', () => {
    const s = getOpenStatus(hours, monAt(9))
    expect(s).toEqual({ status: 'closed', opensAt: '11:00' })
  })
})

describe('getOpenStatus — missing/empty hours', () => {
  it('null hours → unknown', () => {
    expect(getOpenStatus(null, monAt(12))).toEqual({ status: 'unknown' })
  })

  it('no slot for today, finds next day', () => {
    const hours = { tue: ['11:00', '22:30'] as [string, string] }
    const s = getOpenStatus(hours, monAt(12))
    expect(s).toEqual({ status: 'closed', opensAt: 'tomorrow 11:00' })
  })

  it('empty object → closed with null opensAt', () => {
    expect(getOpenStatus({}, monAt(12))).toEqual({ status: 'closed', opensAt: null })
  })
})
