export const MIN_COMPARISON_RESTAURANTS = 3
export const THIN_THRESHOLD = 10
export const RADIUS_CAP = 3000

export const COMMUNE_SLUGS = [
  'anderlecht',
  'auderghem',
  'berchem-sainte-agathe',
  'bruxelles',
  'etterbeek',
  'evere',
  'forest',
  'ganshoren',
  'ixelles',
  'jette',
  'koekelberg',
  'molenbeek',
  'saint-gilles',
  'saint-josse',
  'schaerbeek',
  'uccle',
  'watermael-boitsfort',
  'woluwe-saint-lambert',
  'woluwe-saint-pierre',
] as const

export type CommuneSlug = (typeof COMMUNE_SLUGS)[number]

const DISPLAY_NAMES: Record<string, { fr: string; nl: string }> = {
  'anderlecht': { fr: 'Anderlecht', nl: 'Anderlecht' },
  'auderghem': { fr: 'Auderghem', nl: 'Oudergem' },
  'berchem-sainte-agathe': { fr: 'Berchem-Sainte-Agathe', nl: 'Sint-Agatha-Berchem' },
  'bruxelles': { fr: 'Bruxelles', nl: 'Brussel' },
  'etterbeek': { fr: 'Etterbeek', nl: 'Etterbeek' },
  'evere': { fr: 'Evere', nl: 'Evere' },
  'forest': { fr: 'Forest', nl: 'Vorst' },
  'ganshoren': { fr: 'Ganshoren', nl: 'Ganshoren' },
  'ixelles': { fr: 'Ixelles', nl: 'Elsene' },
  'jette': { fr: 'Jette', nl: 'Jette' },
  'koekelberg': { fr: 'Koekelberg', nl: 'Koekelberg' },
  'molenbeek': { fr: 'Molenbeek-Saint-Jean', nl: 'Sint-Jans-Molenbeek' },
  'saint-gilles': { fr: 'Saint-Gilles', nl: 'Sint-Gillis' },
  'saint-josse': { fr: 'Saint-Josse-ten-Noode', nl: 'Sint-Joost-ten-Node' },
  'schaerbeek': { fr: 'Schaerbeek', nl: 'Schaarbeek' },
  'uccle': { fr: 'Uccle', nl: 'Ukkel' },
  'watermael-boitsfort': { fr: 'Watermael-Boitsfort', nl: 'Watermaal-Bosvoorde' },
  'woluwe-saint-lambert': { fr: 'Woluwe-Saint-Lambert', nl: 'Sint-Lambrechts-Woluwe' },
  'woluwe-saint-pierre': { fr: 'Woluwe-Saint-Pierre', nl: 'Sint-Pieters-Woluwe' },
}

export function communeDisplayName(slug: string, locale: 'fr' | 'nl' | 'en' = 'fr'): string {
  const entry = DISPLAY_NAMES[slug]
  if (!entry) return slug
  if (locale === 'nl') return entry.nl
  return entry.fr
}
