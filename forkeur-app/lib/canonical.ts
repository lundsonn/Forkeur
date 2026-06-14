const BASE_URL = 'https://forkeur.be'

export function restaurantCanonical(id: string, slug?: string | null): string {
  // When slug routing lands, flip this to: return `${BASE_URL}/restaurant/${slug}`
  void slug
  return `${BASE_URL}/restaurant/${id}`
}

export function pageCanonical(path: string): string {
  return `${BASE_URL}${path}`
}
