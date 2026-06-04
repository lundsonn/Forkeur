"""Classify direct ordering URLs into url_type values."""
from __future__ import annotations
from urllib.parse import urlparse
import re

_ORDERING_HOSTS = re.compile(
    r'sq-menu\.com'
    r'|piki-app\.com'
    r'|lightspeedrestaurant\.com'
    r'|wixrestaurants\.com'
    r'|flipdish\.'
    r'|livepepper\.'
    r'|obypay\.'
    r'|foodbooking\.'
    r'|orderyoyo\.'
    r'|clickeat\.'
    r'|square\.site'
    r'|app\.orda\.io'
    r'|orderingstack\.'
    r'|yummyfood\.be'
    r'|order\.me/',
    re.IGNORECASE,
)

_MENU_PATHS = re.compile(
    r'(?:^|-|/)(menu|carte|kaart|menukaart)(?:$|/|-)',
    re.IGNORECASE,
)

_JUNK_RE = re.compile(
    r'google\.com/searchviewer'
    r'|zenchef\.com'
    r'|tablebooker\.com'
    r'|reservations?\.'
    r'|bookings?\.'
    r'|\.pdf$'
    r'|linktr\.ee'
    r'|digilink\.io',
    re.IGNORECASE,
)


def _sq_has_restaurant_code(url: str) -> bool:
    """Return True only if the sq-menu/foodbooking URL contains a restaurant-specific code.

    Valid:   /api/fb/{code}, /api/res/{code}, /api/menu/{code}
    Invalid: /ordering/restaurant/menu, /ordering/restaurant/menu/reservation
    These generic SPA base paths have no restaurant identifier and can never
    be scraped, so we fall through to 'menu'/'website' classification instead.
    """
    parts = [p for p in urlparse(url).path.split("/") if p]
    return len(parts) >= 3 and parts[0] == "api"


def classify_url(order_url: str | None, phone: str | None = None) -> str:
    """Classify a direct ordering URL. Returns: ordering|menu|website|phone."""
    if not order_url:
        return 'phone' if phone else 'website'

    try:
        parsed = urlparse(order_url)
        host = parsed.netloc.lower()
        path = parsed.path
    except Exception:
        return 'website'

    # Odoo POS self-order: *.odoo.com/pos-self/{id} — require a numeric config ID
    if 'odoo.com' in host and 'pos-self' in path:
        parts = [p for p in path.split('/') if p]
        pos_idx = next((i for i, p in enumerate(parts) if p == 'pos-self'), -1)
        if pos_idx >= 0 and pos_idx + 1 < len(parts) and parts[pos_idx + 1].isdigit():
            return 'ordering'
        return 'website'

    if _ORDERING_HOSTS.search(host):
        # sq-menu / foodbooking: generic SPA base paths have no restaurant code
        # and cannot be scraped — treat as 'menu' so dom_menu handles them.
        if 'sq-menu.com' in host or 'foodbooking.com' in host:
            if not _sq_has_restaurant_code(order_url):
                return 'menu'
        return 'ordering'

    if _MENU_PATHS.search(path):
        return 'menu'

    return 'website'
