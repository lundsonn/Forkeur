import { describe, it, expect } from 'vitest'
import { normalizeTitle } from '../lib/queries'

describe('normalizeTitle', () => {
  it('lowercases input', () => {
    expect(normalizeTitle('Pizza Palace')).toBe('pizza palace')
  })

  it('strips accents', () => {
    expect(normalizeTitle('Crêperie')).toBe('creperie')
    expect(normalizeTitle('Café des Amis')).toBe('cafe des amis')
  })

  it('removes punctuation', () => {
    expect(normalizeTitle("McDonald's")).toBe('mcdonalds')
    expect(normalizeTitle('Burger & Fries!')).toBe('burger fries')
  })

  it('collapses multiple spaces', () => {
    expect(normalizeTitle('Pizza   Palace')).toBe('pizza palace')
  })

  it('trims leading and trailing whitespace', () => {
    expect(normalizeTitle('  Pizza Palace  ')).toBe('pizza palace')
  })

  it('handles empty string', () => {
    expect(normalizeTitle('')).toBe('')
  })

  it('handles already normalized input unchanged', () => {
    expect(normalizeTitle('pizza palace')).toBe('pizza palace')
  })

  it('strips mixed diacritics', () => {
    expect(normalizeTitle('Brasserie Ô Côté')).toBe('brasserie o cote')
  })
})
