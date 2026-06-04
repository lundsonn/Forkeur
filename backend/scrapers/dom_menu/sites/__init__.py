"""
Per-site adapter registry for dom_menu.
Add entries here when the generic heuristic fails for a specific restaurant.

Each adapter is an async function:
    async def scrape(url: str, browser, log: Callable) -> list[dict]

Registration example (uncomment and add imports as sites are added):
    # from scrapers.dom_menu.sites import makifornia
    # _REGISTRY["makifornia.be"] = makifornia.scrape
"""
from __future__ import annotations

from typing import Callable

from scrapers.dom_menu.sites import sq_menu, odoo_pos

# domain-fragment → scrape function
_REGISTRY: dict[str, Callable] = {
    "sq-menu.com":    sq_menu.scrape,
    "foodbooking.com": sq_menu.scrape,  # same SPA
    "odoo.com":       odoo_pos.scrape,
}


def get_adapter(host: str) -> Callable | None:
    """Return site-specific adapter if one is registered for this host."""
    host = host.lower()
    for domain, fn in _REGISTRY.items():
        if domain in host:
            return fn
    return None
