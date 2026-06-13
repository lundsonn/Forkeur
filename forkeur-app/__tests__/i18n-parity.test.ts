import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import en from '../messages/en.json'
import fr from '../messages/fr.json'
import nl from '../messages/nl.json'

/** Recursively flatten a nested message object to a sorted list of dotted key paths. */
function flatten(obj: unknown, prefix = ''): string[] {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) {
    return prefix ? [prefix] : []
  }
  const out: string[] = []
  for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      out.push(...flatten(value, path))
    } else {
      out.push(path)
    }
  }
  return out
}

const locales = { en, fr, nl } as const

describe('i18n message parity', () => {
  const enKeys = new Set(flatten(en))

  for (const [name, messages] of Object.entries(locales)) {
    if (name === 'en') continue
    it(`${name}.json has the identical set of keys as en.json`, () => {
      const keys = new Set(flatten(messages))
      const missing = [...enKeys].filter((k) => !keys.has(k)).sort()
      const extra = [...keys].filter((k) => !enKeys.has(k)).sort()
      expect(
        { missing, extra },
        `${name}.json drift vs en.json — missing: [${missing.join(', ')}], extra: [${extra.join(', ')}]`
      ).toEqual({ missing: [], extra: [] })
    })
  }

  it('all three locales share one identical key set', () => {
    const sets = Object.entries(locales).map(([name, m]) => ({
      name,
      keys: flatten(m).sort(),
    }))
    const reference = sets[0]
    for (const { name, keys } of sets.slice(1)) {
      expect(keys, `${name}.json key set differs from ${reference.name}.json`).toEqual(reference.keys)
    }
  })

  it('every locale file is valid JSON on disk', () => {
    for (const name of ['en', 'fr', 'nl']) {
      const path = resolve(__dirname, `../messages/${name}.json`)
      expect(() => JSON.parse(readFileSync(path, 'utf8'))).not.toThrow()
    }
  })
})
