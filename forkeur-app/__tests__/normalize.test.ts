import { describe, it, expect } from 'vitest'
import { normalizeTitle } from '../lib/normalize-title'

// ── Base transforms ─────────────────────────────────────────────────────────

describe('normalizeTitle — base transforms', () => {
  it('lowercases', () => {
    expect(normalizeTitle('Pizza Margherita')).toBe('margherita pizza')
  })

  it('strips accents + removes stopword "la"', () => {
    // "la" is a stopword; 3 tokens remain after removal so it is stripped
    expect(normalizeTitle('Pâtes à la carbonara')).toBe('a carbonara pates')
  })

  it('strips parenthetical content entirely', () => {
    // "(San Marzano, bufala)" stripped before punct→space
    expect(normalizeTitle('Margherita (San Marzano, bufala)')).toBe('margherita')
  })

  it('collapses whitespace + token sorts', () => {
    expect(normalizeTitle('pizza   margherita')).toBe('margherita pizza')
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

  it('strips é, à, ñ — "au" stopword stripped when ≥2 tokens survive', () => {
    expect(normalizeTitle('Café au Réglisse Américain')).toBe('americain cafe reglisse')
  })

  it('cross-platform match: same logical item normalizes to same key', () => {
    expect(normalizeTitle('Pizza Margherita')).toBe(normalizeTitle('pizza margherita'))
  })

  it('strips emoji', () => {
    expect(normalizeTitle('🍕 Pizza')).toBe(normalizeTitle('Pizza'))
  })
})

// ── MUST MATCH pairs ────────────────────────────────────────────────────────

describe('normalizeTitle — must-match pairs', () => {
  it('trailing cm NOT stripped (size differentiates pizza variants)', () => {
    // cm was removed from TRAILING_SIZE to prevent false positives (28cm ≠ 33cm pizza).
    expect(normalizeTitle('Margherita 30cm')).not.toBe(normalizeTitle('Margherita'))
  })

  it('parenthetical size stripped', () => {
    expect(normalizeTitle('Chicken Burger (200g)')).toBe(normalizeTitle('Chicken Burger'))
  })

  it('trailing cl strips — cross-platform formatting differs', () => {
    expect(normalizeTitle('Coca-Cola 33cl')).toBe(normalizeTitle('coca cola 33cl'))
  })

  it('parenthetical cl stripped; trailing cl stripped — same result', () => {
    expect(normalizeTitle('Fanta (33cl)')).toBe(normalizeTitle('fanta 33cl'))
  })

  it('token sort rescues word-order difference', () => {
    expect(normalizeTitle('Classic Chicken Burger')).toBe(normalizeTitle('Chicken Burger Classic'))
  })

  it('leading 2x multiplier stripped', () => {
    expect(normalizeTitle('2x Margherita')).toBe(normalizeTitle('Margherita'))
  })

  it('parenthetical stuks stripped', () => {
    expect(normalizeTitle('Bicky Burger (2 stuks)')).toBe(normalizeTitle('Bicky Burger'))
  })

  it('diacritic strip — poulet rôti', () => {
    expect(normalizeTitle('Poulet rôti')).toBe(normalizeTitle('poulet roti'))
  })

  it('case normalization — PIZZA HAWAII', () => {
    expect(normalizeTitle('PIZZA HAWAII')).toBe(normalizeTitle('pizza hawaii'))
  })

  it('trailing size with space — Sparkling Water 330 ml', () => {
    expect(normalizeTitle('Sparkling Water')).toBe(normalizeTitle('Sparkling Water 330 ml'))
  })

  it('size with space before unit — 33 cl same as 33cl', () => {
    expect(normalizeTitle('Coca-Cola 33 cl')).toBe(normalizeTitle('Coca-Cola'))
  })

  it('token sort — Menu Quattro / Quattro Menu', () => {
    // "menu" is a stopword; only 1 token would remain → stopword filter NOT applied
    // both sort to "menu quattro"
    expect(normalizeTitle('Quattro Menu')).toBe(normalizeTitle('Menu Quattro'))
  })
})

// ── Numbered-prefix strip ────────────────────────────────────────────────────

describe('normalizeTitle — numbered-prefix strip', () => {
  it('dot separator', () => {
    expect(normalizeTitle('52. Malay Soup')).toBe(normalizeTitle('Malay Soup'))
  })

  it('dash separator', () => {
    expect(normalizeTitle('3- Potage aux champignons')).toBe(normalizeTitle('Potage aux champignons'))
  })

  it('closing-paren separator', () => {
    expect(normalizeTitle('12) Canard laqué')).toBe(normalizeTitle('Canard Laque'))
  })

  it('zero-padded prefix', () => {
    expect(normalizeTitle('03 Pad Thai')).toBe(normalizeTitle('Pad Thai'))
  })

  it('7up — digit with no separator is NOT stripped', () => {
    expect(normalizeTitle('7up')).not.toBe(normalizeTitle('up'))
    expect(normalizeTitle('7up')).toBe('7up')
  })

  it('number-only title survives — does not collapse to empty', () => {
    expect(normalizeTitle('12')).toBe('12')
  })
})

// ── MUST NOT MATCH pairs ────────────────────────────────────────────────────

describe('normalizeTitle — must-not-match pairs', () => {
  it('different products', () => {
    expect(normalizeTitle('Margherita')).not.toBe(normalizeTitle('Diavola'))
  })

  it('burger vs wrap', () => {
    expect(normalizeTitle('Chicken Burger')).not.toBe(normalizeTitle('Chicken Wrap'))
  })

  it('same size, different drink', () => {
    expect(normalizeTitle('Coca-Cola 33cl')).not.toBe(normalizeTitle('Fanta 33cl'))
  })

  it('small vs large fries differ (size is meaningful here)', () => {
    expect(normalizeTitle('Small Fries')).not.toBe(normalizeTitle('Large Fries'))
  })
})

// ── Category-prefix stripping ────────────────────────────────────────────────

describe('normalizeTitle — category-prefix stripping', () => {
  it('strips exact category prefix', () => {
    expect(normalizeTitle('Pizza Margherita', 'Pizza')).toBe(normalizeTitle('Margherita'))
  })
  it('does not strip when prefix equals full title', () => {
    expect(normalizeTitle('Margherita', 'Margherita')).toBe(normalizeTitle('Margherita'))
  })
  it('strips multi-token category prefix', () => {
    expect(normalizeTitle('Pasta Carbonara Special', 'Pasta Carbonara')).toBe(normalizeTitle('Special'))
  })
  it('does not strip partial match from middle', () => {
    expect(normalizeTitle('Pizza Margherita', 'Margherita')).toBe(normalizeTitle('Pizza Margherita'))
  })
})

// ── Edge cases ──────────────────────────────────────────────────────────────

describe('normalizeTitle — edge cases', () => {
  it('parenthetical-only name survives — does not collapse to empty', () => {
    const result = normalizeTitle('(large)')
    expect(result.length).toBeGreaterThan(0)
  })

  it('two identical parenthetical-only names produce the same key', () => {
    expect(normalizeTitle('(large)')).toBe(normalizeTitle('(large)'))
  })

  it('stopword removal skipped when <2 tokens would survive', () => {
    // "le menu" → sort: "le menu" → filter "le" + "menu" → 0 tokens → keep "le menu"
    const result = normalizeTitle('Le Menu')
    expect(result).toBe('le menu')
  })
})
