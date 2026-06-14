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

# slug → (lat, lng) centroid of each commune
COMMUNE_CENTROIDS: dict[str, tuple[float, float]] = {
    "anderlecht": (50.6619, 4.3059),
    "auderghem": (50.8131, 4.4326),
    "berchem-sainte-agathe": (50.8681, 4.2992),
    "bruxelles": (50.8503, 4.3517),
    "etterbeek": (50.8352, 4.3896),
    "evere": (50.8737, 4.4023),
    "forest": (50.8113, 4.3309),
    "ganshoren": (50.8815, 4.3149),
    "ixelles": (50.8271, 4.3707),
    "jette": (50.8875, 4.3282),
    "koekelberg": (50.8674, 4.3341),
    "molenbeek": (50.8613, 4.3123),
    "saint-gilles": (50.8261, 4.3454),
    "saint-josse": (50.8545, 4.3697),
    "schaerbeek": (50.8663, 4.3787),
    "uccle": (50.7960, 4.3556),
    "watermael-boitsfort": (50.7997, 4.4253),
    "woluwe-saint-lambert": (50.8416, 4.4338),
    "woluwe-saint-pierre": (50.8202, 4.4555),
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
