// Canonical source of truth for cross-platform menu item key normalization.
// Imported by lib/queries.ts (frontend itemMap) and scripts/match-rate-audit.ts.
// Any change here automatically applies to both.

const STOPWORDS = new Set([
  'menu', 'met', 'avec', 'with', 'de', 'het', 'le', 'la', 'les', 'du', 'des',
  'een', 'our', 'nos', 'maison', 'homemade', 'special', 'speciale',
  'au', 'aux', 'et', 'en', 'and', 'of', 'al', 'con', 'bij', 'op', 'van',
])

// Trailing size/unit pattern — liquid volumes only (cl, ml, dl, l).
// Spot-check showed oz differentiates coffee sizes (12oz ≠ 16oz); g/kg differentiates
// portion sizes; pcs/stuks differentiate box counts; bare `l` differentiates bottle sizes
// (1.5L ≠ 33cl). Only cl/ml/dl are safe — Belgian menus label standard cans/glasses with
// and without volume, but different-litre bottles are always distinct products.
const TRAILING_SIZE = /\s+\d+([.,]\d+)?\s*(cl|ml|dl)\s*$/i

// Trailing piece-count suffix — only one platform (UberEats) appends these.
// Unlike oz/g/kg, piece counts don't distinguish distinct products (the item at
// fewer pieces is the same dish, not a smaller portion); safe to strip globally.
const TRAILING_PIECES = /\s+\d+\s*(pcs?|pieces?|stuks?|st\.?)\s*$/i

// Leading quantity/multiplier pattern.
const LEADING_QTY = /^\d+\s*(x|stuks?|pcs|pieces?|st)\s+/i

// Leading menu-number pattern: digits followed by separator(s), e.g. "52. " "3- " "12) " "03 ".
// Requires at least one non-digit separator after the digits (prevents "7up" → "up").
const LEADING_MENU_NUM = /^\d+[\s\-\.\)\:]+\s*/

// Shared cleaning pipeline: emoji, accents, lowercase, parens, size, pieces,
// leading qty/menu-num, punct→space. No token sort or stopword filtering.
function baseNormalize(title: string): string {
  let s = title
    .replace(/[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu, '')
    .normalize('NFD').replace(/\p{Mn}/gu, '')
    .replace(/['']/g, '')
    .toLowerCase()
  const noParens = s.replace(/\s*\([^)]*\)\s*/g, ' ').replace(/\s+/g, ' ').trim()
  if (noParens) s = noParens
  const noSize = s.replace(TRAILING_SIZE, '').trim()
  if (noSize) s = noSize
  const noPieces = s.replace(TRAILING_PIECES, '').trim()
  if (noPieces) s = noPieces
  const noLeadQty = s.replace(LEADING_QTY, '').trim()
  if (noLeadQty) s = noLeadQty
  const noMenuNum = s.replace(LEADING_MENU_NUM, '').trim()
  if (noMenuNum) s = noMenuNum
  return s.replace(/[^\p{L}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim()
}

/**
 * Canonical exact-match key for cross-platform item pairing.
 *
 * Pass `category` (= item's own catalog_name) to enable category-prefix stripping:
 * UberEats prepends the category to item titles ("Pizza Margherita" where category
 * is "Pizza") while Deliveroo omits it ("Margherita"). Stripping the prefix ONLY when
 * it exactly equals the item's own category is safe — it never fires across platforms
 * that don't use the prefix, and never fires when the prefix is part of the actual name.
 */
export function normalizeTitle(title: string, category?: string): string {
  let s = baseNormalize(title)

  if (category) {
    const catNorm = baseNormalize(category)
    const catTokens = catNorm.split(/\s+/).filter(Boolean)
    const titleTokens = s.split(/\s+/)
    if (
      catTokens.length > 0 &&
      catTokens.length < titleTokens.length &&
      catTokens.every((t, i) => t === titleTokens[i])
    ) {
      s = titleTokens.slice(catTokens.length).join(' ')
    }
  }

  // Token sort — deterministic, symmetric across all platforms.
  const tokens = s.split(/\s+/).sort()

  // Strip stopwords only when ≥2 tokens survive removal.
  const filtered = tokens.filter(t => !STOPWORDS.has(t))
  return (filtered.length >= 2 ? filtered : tokens).join(' ')
}

/**
 * Same cleaning pipeline as normalizeTitle but WITHOUT token sort and WITHOUT
 * stopword filtering. Use for fuzzy similarity scoring — Jaro-Winkler is
 * order-sensitive, so token sort distorts the distance calculation.
 */
export function normalizeForFuzzy(title: string): string {
  return baseNormalize(title)
}
