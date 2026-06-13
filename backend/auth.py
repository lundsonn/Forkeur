from __future__ import annotations
import os
import re
from datetime import datetime, timedelta, timezone
import jwt

_SECRET: str | None = None
_ALGO = "HS256"


def _secret() -> str:
    """Lazily read JWT_SECRET so importing this module never crashes before
    main.py's _check_required_env() can emit a clean error. Cached after first
    successful read."""
    global _SECRET
    if _SECRET is None:
        s = os.environ.get("JWT_SECRET")
        if not s:
            raise RuntimeError("JWT_SECRET environment variable is not set")
        _SECRET = s
    return _SECRET
# Hours, not days: 30-day tokens on a single shared admin password offer too
# wide a window for credential reuse if the token ever leaks.
_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "12"))
_AUDIENCE = "forkeur-admin"
_ISSUER = "forkeur-backend"
_VALID_ADMIN_ID = re.compile(r"^[a-zA-Z0-9_.@-]{1,64}$")


def _normalize_admin_id(admin_id: str | None) -> str:
    """Default to 'admin' if none supplied; reject anything non-printable so a
    spoofed identity can't smuggle log-injection into audit trails."""
    if not admin_id:
        return "admin"
    if not _VALID_ADMIN_ID.match(admin_id):
        return "admin"
    return admin_id


def create_token(admin_id: str | None = None) -> str:
    """Mint an admin JWT. `admin_id` lets multiple operators identify themselves
    on login so downstream audit logs can record who approved/rejected what."""
    now = datetime.now(timezone.utc)
    payload = {
        "admin": True,
        "sub": _normalize_admin_id(admin_id),
        "aud": _AUDIENCE,
        "iss": _ISSUER,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(hours=_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGO)


def _decode(token: str) -> dict | None:
    if not token:
        return None
    try:
        return jwt.decode(
            token,
            _secret(),
            algorithms=[_ALGO],
            audience=_AUDIENCE,
            issuer=_ISSUER,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except Exception:
        return None


def verify_token(token: str) -> bool:
    return _decode(token) is not None


def identity_from_token(token: str) -> str | None:
    """Return the sub claim of a valid token, or None if invalid/missing."""
    payload = _decode(token)
    if payload is None:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) and sub else None
