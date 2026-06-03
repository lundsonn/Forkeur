from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
import jwt

_SECRET = os.environ.get("JWT_SECRET", "forkeur-dev-secret-change-in-prod")
_ALGO = "HS256"
_EXPIRE_DAYS = 30


def create_token() -> str:
    payload = {
        "admin": True,
        "exp": datetime.now(timezone.utc) + timedelta(days=_EXPIRE_DAYS),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGO)


def verify_token(token: str) -> bool:
    try:
        jwt.decode(token, _SECRET, algorithms=[_ALGO])
        return True
    except Exception:
        return False
