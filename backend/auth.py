from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
import jwt

_SECRET = os.environ["JWT_SECRET"]
_ALGO = "HS256"
# Hours, not days: 30-day tokens on a single shared admin password offer too
# wide a window for credential reuse if the token ever leaks.
_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "12"))
_AUDIENCE = "forkeur-admin"
_ISSUER = "forkeur-backend"


def create_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "admin": True,
        "sub": "admin",
        "aud": _AUDIENCE,
        "iss": _ISSUER,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(hours=_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGO)


def verify_token(token: str) -> bool:
    if not token:
        return False
    try:
        jwt.decode(
            token,
            _SECRET,
            algorithms=[_ALGO],
            audience=_AUDIENCE,
            issuer=_ISSUER,
            # require ensures decode raises if any of these standard claims is
            # missing — protects against tokens minted by older code paths.
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
        return True
    except Exception:
        return False
