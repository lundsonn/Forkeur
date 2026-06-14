"""Brussels-Capital Region commune mapping and postal-code resolution."""

from __future__ import annotations

# slug → (fr_name, nl_name, postal_codes, neighborhood_aliases)
COMMUNES: dict[str, tuple[str, str, list[int], list[str]]] = {
    "anderlecht": ("Anderlecht", "Anderlecht", [1070], ["anderlecht"]),
    "auderghem": ("Auderghem", "Oudergem", [1160], ["auderghem", "oudergem"]),
    "berchem-sainte-agathe": ("Berchem-Sainte-Agathe", "Sint-Agatha-Berchem", [1082], ["berchem", "sint-agatha-berchem"]),
    "bruxelles": ("Bruxelles", "Brussel", [1000, 1020, 1120, 1130], ["bruxelles", "brussel", "brussels", "centre", "laeken"]),
    "etterbeek": ("Etterbeek", "Etterbeek", [1040], ["etterbeek"]),
    "evere": ("Evere", "Evere", [1140], ["evere"]),
    "forest": ("Forest", "Vorst", [1190], ["forest", "vorst"]),
    "ganshoren": ("Ganshoren", "Ganshoren", [1083], ["ganshoren"]),
    "ixelles": ("Ixelles", "Elsene", [1050], ["ixelles", "elsene"]),
    "jette": ("Jette", "Jette", [1090], ["jette"]),
    "koekelberg": ("Koekelberg", "Koekelberg", [1081], ["koekelberg"]),
    "molenbeek": ("Molenbeek-Saint-Jean", "Sint-Jans-Molenbeek", [1080], ["molenbeek", "sint-jans-molenbeek"]),
    "saint-gilles": ("Saint-Gilles", "Sint-Gillis", [1060], ["saint-gilles", "sint-gillis"]),
    "saint-josse": ("Saint-Josse-ten-Noode", "Sint-Joost-ten-Node", [1210], ["saint-josse", "sint-joost"]),
    "schaerbeek": ("Schaerbeek", "Schaarbeek", [1030], ["schaerbeek", "schaarbeek"]),
    "uccle": ("Uccle", "Ukkel", [1180], ["uccle", "ukkel"]),
    "watermael-boitsfort": ("Watermael-Boitsfort", "Watermaal-Bosvoorde", [1170], ["watermael-boitsfort", "watermaal-bosvoorde"]),
    "woluwe-saint-lambert": ("Woluwe-Saint-Lambert", "Sint-Lambrechts-Woluwe", [1200], ["woluwe-saint-lambert", "sint-lambrechts-woluwe"]),
    "woluwe-saint-pierre": ("Woluwe-Saint-Pierre", "Sint-Pieters-Woluwe", [1150], ["woluwe-saint-pierre", "sint-pieters-woluwe"]),
}

# Build reverse lookup: postal_code → slug
_POSTAL_TO_SLUG: dict[int, str] = {}
for _slug, (_fr, _nl, _codes, _aliases) in COMMUNES.items():
    for _code in _codes:
        _POSTAL_TO_SLUG[_code] = _slug

# Build reverse lookup: normalised alias → slug
_ALIAS_TO_SLUG: dict[str, str] = {}
for _slug, (_fr, _nl, _codes, _aliases) in COMMUNES.items():
    for _alias in _aliases:
        _ALIAS_TO_SLUG[_alias.lower()] = _slug


def resolve_commune(postal_code: int | None, neighborhood: str | None) -> str | None:
    """Return canonical commune slug, or None if unresolvable.

    postal_code takes priority; neighborhood is fallback.
    """
    if postal_code is not None:
        slug = _POSTAL_TO_SLUG.get(int(postal_code))
        if slug:
            return slug

    if neighborhood:
        needle = neighborhood.strip().lower()
        # Exact alias match
        if needle in _ALIAS_TO_SLUG:
            return _ALIAS_TO_SLUG[needle]
        # Substring match — first alias that appears in the neighborhood string
        for alias, slug in _ALIAS_TO_SLUG.items():
            if alias in needle:
                return slug

    return None
