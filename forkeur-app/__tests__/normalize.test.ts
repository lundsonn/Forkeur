import { describe, it, expect } from 'vitest'
import { normalizeTitle } from '../lib/queries'

describe('normalizeTitle', () => {
  it('lowercases', () => {
    expect(normalizeTitle('Big Mac')).toBe('big mac')
  })

  it('strips accents', () => {
    expect(normalizeTitle('Crème brûlée')).toBe('creme brulee')
  })

  it('strips é, à, ñ', () => {
    expect(normalizeTitle('Café au Réglisse Américain')).toBe('cafe au reglisse americain')
  })

  it('strips punctuation', () => {
    expect(normalizeTitle('Pizza (San Marzano, bufala)')).toBe('pizza san marzano bufala')
  })

  it('strips hyphens and apostrophes', () => {
    expect(normalizeTitle("Pain d'épices")).toBe('pain depices')
  })

  it('collapses multiple spaces', () => {
    expect(normalizeTitle('Big   Mac')).toBe('big mac')
  })

  it('trims leading/trailing whitespace', () => {
    expect(normalizeTitle('  Big Mac  ')).toBe('big mac')
  })

  it('cross-platform match: same logical item normalizes to same key', () => {
    expect(normalizeTitle('Pizza Margherita')).toBe(normalizeTitle('pizza margherita'))
  })

  it('does NOT merge different items', () => {
    expect(normalizeTitle('Pizza Margherita')).not.toBe(normalizeTitle('Pizza Napolitaine'))
  })
})
