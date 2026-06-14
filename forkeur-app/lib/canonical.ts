const BASE_URL = 'https://forkeur.be'

export function restaurantCanonical(id: string, slug?: string | null): string {
  return `${BASE_URL}/restaurant/${slug ?? id}`
}

export function pageCanonical(path: string): string {
  return `${BASE_URL}${path}`
}
