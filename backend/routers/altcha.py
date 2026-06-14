from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets

from fastapi import APIRouter

router = APIRouter(prefix="/altcha", tags=["altcha"])

_HMAC_KEY = os.getenv("ALTCHA_HMAC_KEY", "")
_MAX_NUMBER = 100_000


def _hmac_sig(challenge: str) -> str:
    return hmac.new(_HMAC_KEY.encode(), challenge.encode(), hashlib.sha256).hexdigest()


def generate_challenge() -> dict:
    salt = secrets.token_hex(12)
    secret_number = secrets.randbelow(_MAX_NUMBER)
    challenge = hashlib.sha256(f"{salt}{secret_number}".encode()).hexdigest()
    return {
        "algorithm": "SHA-256",
        "challenge": challenge,
        "salt": salt,
        "signature": _hmac_sig(challenge),
        "maxnumber": _MAX_NUMBER,
    }


def verify_payload(payload_b64: str) -> bool:
    """Verify an Altcha base64 payload. Soft-pass if ALTCHA_HMAC_KEY not set (dev)."""
    if not _HMAC_KEY:
        return True
    try:
        data = json.loads(base64.b64decode(payload_b64).decode())
        challenge = hashlib.sha256(
            f"{data['salt']}{data['number']}".encode()
        ).hexdigest()
        if challenge != data["challenge"]:
            return False
        expected = _hmac_sig(challenge)
        return hmac.compare_digest(expected, data["signature"])
    except Exception:
        return False


@router.get("/challenge")
def get_challenge():
    return generate_challenge()
