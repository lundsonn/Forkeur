"""Single source of truth for SSRF / unsafe-URL checks.

Used by both `db.py` (validating user-submitted order URLs) and
`scrapers/base.py` (vetting URLs before navigating). Previously these lived in
two places and drifted; consolidate so a fix lands once.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

# Hostname patterns that should never be reachable from a public scraper.
_BAD_HOST_RE = re.compile(
    r"^(localhost|.+\.internal|.+\.local|.+\.localhost)$",
    re.IGNORECASE,
)

# Known security-research / OOB exfil hosts that should never appear in
# user-submitted order URLs even if they technically resolve to public IPs.
_OOB_RE = re.compile(
    r"oast\.|interactsh\.|burpcollaborator\.|canarytokens\.|webhook\.site",
    re.IGNORECASE,
)


def _is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def is_safe_url(url: str) -> bool:
    """Return True only if URL is http/https and resolves to a public, routable IP."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = (p.hostname or "").strip()
    if not host:
        return False
    if _BAD_HOST_RE.match(host) or _OOB_RE.search(host):
        return False
    # If the host is already a literal IP, check it directly.
    try:
        ipaddress.ip_address(host)
        return not _is_blocked_ip(host)
    except ValueError:
        pass
    # Resolve and reject if ANY resolved address is non-public.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        sockaddr = info[4]
        ip = sockaddr[0]
        if _is_blocked_ip(ip):
            return False
    return True


def validate_public_url(url: str) -> None:
    """Raise ValueError with a stable message if URL is unsafe to publish/fetch."""
    if not is_safe_url(url):
        raise ValueError(f"URL not allowed: {url!r}")
