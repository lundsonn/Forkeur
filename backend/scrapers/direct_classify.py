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
    r'|order\.me/'
    r'|app\.fritzy\.be',
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
    r'|digilink\.io'
    r'|bit\.ly/'
    r'|sprd\.li/'
    # Bad page paths — informational, not ordering
    r'|/terms(-of[- _]?(use|service))?(/|$)'
    r'|/privacy(-policy)?(/|$)'
    r'|/legal(/|$)'
    r'|/conditions(-g[eé]n[eé]rales)?(/|$)'
    r'|/cgv(/|$)'
    r'|/contact(/|$)'
    r'|/about(-us)?(/|$)'
    r'|/faq(/|$)'
    r'|/sitemap'
    r'|/cookie',
    re.IGNORECASE,
)

# Global chain corporate domains that geo-redirect or serve generic menus —
# never "ordering" or "menu": always downgrade to "website" so we don't show
# "Order directly · no platform fees" or "View menu" for a page that may
# redirect the user to a different country's site.
_CHAIN_CORPORATE_RE = re.compile(
    r'subway\.com'
    r'|mcdonalds\.com'
    r'|kfc\.com'
    r'|burgerking\.com'
    r'|pizzahut\.com'
    r'|dominos\.com'
    r'|starbucks\.com'
    r'|quick\.be'
    r'|tgifridays\.com'
    r'|papajohns\.com',
    re.IGNORECASE,
)


def _sq_has_restaurant_code(url: str) -> bool:
    """Return True if the sq-menu/foodbooking URL has a restaurant identifier.

    Valid (restaurant-specific subdomain): burger-palace.sq-menu.com/...
    Valid (API path with code):            www.sq-menu.com/api/fb/{code}
    Invalid (generic SPA base):            www.sq-menu.com/ordering/restaurant/menu
    """
    parsed = urlparse(url)
    # Strip www. and check for restaurant-specific subdomain (e.g. burger-palace.sq-menu.com)
    bare_host = re.sub(r'^www\.', '', parsed.netloc.lower())
    if len(bare_host.split('.')) > 2:
        return True
    # API path with restaurant code: /api/{type}/{code}
    parts = [p for p in parsed.path.split("/") if p]
    return len(parts) >= 3 and parts[0] == "api"


def is_junk_url(url: str | None) -> bool:
    """Return True if the URL is a known junk/booking/aggregator artifact."""
    return bool(url and _JUNK_RE.search(url))


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

    # Known global chain corporate sites — never claim ordering/menu capability
    if _CHAIN_CORPORATE_RE.search(host):
        return 'website'

    # Odoo POS self-order: *.odoo.com/pos-self/...
    if 'odoo.com' in host and 'pos-self' in path:
        return 'ordering'

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
