import { describe, it, expect } from 'vitest'
import { normalizeTitle } from '../lib/queries'

describe('normalizeTitle', () => {
  it('lowercases input + token sorts', () => {
    expect(normalizeTitle('Pizza Palace')).toBe('palace pizza')
  })

  it('strips accents; stopword "des" removed when 2+ tokens remain', () => {
    expect(normalizeTitle('Crêperie')).toBe('creperie')
    // "cafe des amis" → sort "amis cafe des" → filter "des" → "amis cafe"
    expect(normalizeTitle('Café des Amis')).toBe('amis cafe')
  })

  it('removes punctuation', () => {
    expect(normalizeTitle("McDonald's")).toBe('mcdonalds')
    expect(normalizeTitle('Burger & Fries!')).toBe('burger fries')
  })

  it('collapses multiple spaces + token sorts', () => {
    expect(normalizeTitle('Pizza   Palace')).toBe('palace pizza')
  })

  it('trims + token sorts', () => {
    expect(normalizeTitle('  Pizza Palace  ')).toBe('palace pizza')
  })

  it('handles empty string', () => {
    expect(normalizeTitle('')).toBe('')
  })

  it('token sorts already-lowercase input', () => {
    expect(normalizeTitle('pizza palace')).toBe('palace pizza')
  })

  it('strips mixed diacritics + token sorts', () => {
    // "brasserie o cote" → sort alphabetically: brasserie < cote < o
    expect(normalizeTitle('Brasserie Ô Côté')).toBe('brasserie cote o')
  })
})
