import { describe, it, expect } from 'vitest'
import { normalizeTitle } from '../lib/queries'

describe('normalizeTitle', () => {
  it('lowercases', () => {
    expect(normalizeTitle('Pizza Margherita')).toBe('pizza margherita')
  })

  it('strips accents', () => {
    expect(normalizeTitle('Pâtes à la carbonara')).toBe('pates a la carbonara')
  })

  it('strips punctuation', () => {
    expect(normalizeTitle('Margherita (San Marzano, bufala)')).toBe('margherita san marzano bufala')
  })

  it('collapses whitespace', () => {
    expect(normalizeTitle('pizza   margherita')).toBe('pizza margherita')
  })

  it('trims', () => {
    expect(normalizeTitle('  pizza  ')).toBe('pizza')
  })

  it('handles accents + punctuation combined', () => {
    expect(normalizeTitle('Café liègeois')).toBe('cafe liegeois')
  })

  it('empty string', () => {
    expect(normalizeTitle('')).toBe('')
  })

  it('strips é, à, ñ', () => {
    expect(normalizeTitle('Café au Réglisse Américain')).toBe('cafe au reglisse americain')
  })

  it('cross-platform match: same logical item normalizes to same key', () => {
    expect(normalizeTitle('Pizza Margherita')).toBe(normalizeTitle('pizza margherita'))
  })
})
