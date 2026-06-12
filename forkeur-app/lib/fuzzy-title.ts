import { normalizeForFuzzy } from './normalize-title'

function jaro(s1: string, s2: string): number {
  if (s1 === s2) return 1.0
  const len1 = s1.length, len2 = s2.length
  if (len1 === 0 || len2 === 0) return 0.0
  const matchDist = Math.max(Math.floor(Math.max(len1, len2) / 2) - 1, 0)
  const s1Matches = new Uint8Array(len1)
  const s2Matches = new Uint8Array(len2)
  let matches = 0
  for (let i = 0; i < len1; i++) {
    const lo = Math.max(0, i - matchDist)
    const hi = Math.min(len2 - 1, i + matchDist)
    for (let j = lo; j <= hi; j++) {
      if (!s2Matches[j] && s1[i] === s2[j]) {
        s1Matches[i] = 1; s2Matches[j] = 1; matches++; break
      }
    }
  }
  if (matches === 0) return 0.0
  let trans = 0, k = 0
  for (let i = 0; i < len1; i++) {
    if (!s1Matches[i]) continue
    while (!s2Matches[k]) k++
    if (s1[i] !== s2[k]) trans++
    k++
  }
  return (matches / len1 + matches / len2 + (matches - trans / 2) / matches) / 3
}

export function jaroWinkler(s1: string, s2: string): number {
  const j = jaro(s1, s2)
  let l = 0
  const maxL = Math.min(4, Math.min(s1.length, s2.length))
  while (l < maxL && s1[l] === s2[l]) l++
  return j + l * 0.1 * (1 - j)
}

/**
 * Find the best fuzzy-matching item by name (Jaro-Winkler on normalizeForFuzzy).
 * Exact match tried first; fuzzy fallback requires JW ≥ threshold AND len ratio ≥ 0.75
 * (prevents "Burger" merging with "Burger Deluxe").
 */
export function fuzzyFindByTitle<T extends { name: string }>(
  name: string,
  items: T[],
  threshold = 0.88
): T | undefined {
  const normQuery = normalizeForFuzzy(name)
  // Exact first
  const exactMatch = items.find(m => normalizeForFuzzy(m.name) === normQuery)
  if (exactMatch) return exactMatch
  // Fuzzy fallback
  let best: T | undefined
  let bestSim = -1
  for (const item of items) {
    const normItem = normalizeForFuzzy(item.name)
    const lenRatio =
      Math.min(normQuery.length, normItem.length) /
      Math.max(normQuery.length, normItem.length)
    if (lenRatio < 0.75) continue
    const sim = jaroWinkler(normQuery, normItem)
    if (sim >= threshold && sim > bestSim) {
      bestSim = sim; best = item
    }
  }
  return best
}
