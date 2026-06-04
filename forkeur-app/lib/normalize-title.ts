// Canonical source of truth for cross-platform menu item key normalization.
// Imported by lib/queries.ts (frontend itemMap) and scripts/match-rate-audit.ts.
// Any change here automatically applies to both.

const STOPWORDS = new Set([
  'menu', 'met', 'avec', 'with', 'de', 'het', 'le', 'la', 'les', 'du', 'des',
  'een', 'our', 'nos', 'maison', 'homemade', 'special', 'speciale',
])

// Trailing size/unit pattern — liquid volumes only (cl, ml, dl, l).
// Spot-check showed oz differentiates coffee sizes (12oz ≠ 16oz); g/kg differentiates
// portion sizes; pcs/stuks differentiate box counts; bare `l` differentiates bottle sizes
// (1.5L ≠ 33cl). Only cl/ml/dl are safe — Belgian menus label standard cans/glasses with
// and without volume, but different-litre bottles are always distinct products.
const TRAILING_SIZE = /\s+\d+([.,]\d+)?\s*(cl|ml|dl)\s*$/i

// Leading quantity/multiplier pattern.
const LEADING_QTY = /^\d+\s*(x|stuks?|pcs|pieces?|st)\s+/i

// Leading menu-number pattern: digits followed by separator(s), e.g. "52. " "3- " "12) " "03 ".
// Requires at least one non-digit separator after the digits (prevents "7up" → "up").
const LEADING_MENU_NUM = /^\d+[\s\-\.\)\:]+\s*/

export function normalizeTitle(title: string): string {
  let s = title
    .replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu, '')
    .normalize('NFD').replace(/\p{Mn}/gu, '')
    .replace(/['']/g, '')
    .toLowerCase()

  // Strip parentheticals while parens are still present (before punct→space).
  // Safety: if result is empty, keep the pre-strip form.
  const noParens = s.replace(/\s*\([^)]*\)\s*/g, ' ').replace(/\s+/g, ' ').trim()
  if (noParens) s = noParens

  // Strip trailing size/unit tokens.
  const noSize = s.replace(TRAILING_SIZE, '').trim()
  if (noSize) s = noSize

  // Strip leading quantity/multiplier tokens.
  const noLeadQty = s.replace(LEADING_QTY, '').trim()
  if (noLeadQty) s = noLeadQty

  // Strip leading menu-number prefix (e.g. "52. Malay Soup" → "malay soup").
  const noMenuNum = s.replace(LEADING_MENU_NUM, '').trim()
  if (noMenuNum) s = noMenuNum

  // Replace remaining punctuation with space.
  s = s.replace(/[^\p{L}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim()

  // Token sort — deterministic, symmetric across all platforms.
  const tokens = s.split(/\s+/).sort()

  // Strip stopwords only when ≥2 tokens survive removal.
  const filtered = tokens.filter(t => !STOPWORDS.has(t))
  return (filtered.length >= 2 ? filtered : tokens).join(' ')
}
