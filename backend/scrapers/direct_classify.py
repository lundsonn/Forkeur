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
    r'|orderingstack\.',
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

    # Odoo POS self-order: *.odoo.com/pos-self/...
    if 'odoo.com' in host and 'pos-self' in path:
        return 'ordering'

    if _ORDERING_HOSTS.search(host):
        return 'ordering'

    if _MENU_PATHS.search(path):
        return 'menu'

    return 'website'
