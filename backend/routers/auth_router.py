from __future__ import annotations
import asyncio
import hmac
import os
import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel
import auth

router = APIRouter(prefix="/auth", tags=["auth"])

# Brute-force protection: track failed attempts per IP.
# 5 failures within 15 min → 15-min lockout.
_FAIL_WINDOW = 15 * 60
_MAX_FAILS = 5
_LOCKOUT_DURATION = 15 * 60
_FAIL_DELAY = 1.0  # sleep on wrong password (slows attack, wastes attacker time)

_attempts: dict[str, list[float]] = defaultdict(list)
_locked: dict[str, float] = {}
_mu = Lock()


def _client_ip(request: Request) -> str:
    return request.headers.get("X-Real-IP") or (request.client.host if request.client else "unknown")


def _check_locked(ip: str) -> bool:
    with _mu:
        until = _locked.get(ip)
        if until:
            if time.monotonic() < until:
                return True
            del _locked[ip]
        return False


def _record_failure(ip: str) -> None:
    now = time.monotonic()
    with _mu:
        _attempts[ip] = [t for t in _attempts[ip] if now - t < _FAIL_WINDOW]
        _attempts[ip].append(now)
        if len(_attempts[ip]) >= _MAX_FAILS:
            _locked[ip] = now + _LOCKOUT_DURATION
            _attempts[ip] = []


def _record_success(ip: str) -> None:
    with _mu:
        _attempts.pop(ip, None)
        _locked.pop(ip, None)


def require_auth(authorization: str = Header(default="")) -> str:
    """FastAPI dependency that enforces Bearer token auth and returns the
    authenticated admin's identity (the JWT `sub` claim). Used by handlers
    that need to record who performed an action — e.g. claim approvals,
    match-queue resolutions."""
    token = authorization.removeprefix("Bearer ").strip()
    identity = auth.identity_from_token(token)
    if identity is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return identity


class LoginIn(BaseModel):
    password: str
    # Optional self-identification so the audit log records who acted. Anyone
    # with the shared password can claim any id, but it still gives a paper
    # trail when operators consistently identify themselves.
    admin_id: str | None = None


class LoginOut(BaseModel):
    token: str


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn, request: Request):
    ip = _client_ip(request)

    if _check_locked(ip):
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")

    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected:
        raise HTTPException(500, "ADMIN_PASSWORD not configured on the server")

    if not hmac.compare_digest(body.password, expected):
        _record_failure(ip)
        await asyncio.sleep(_FAIL_DELAY)
        raise HTTPException(401, "Invalid password")

    _record_success(ip)
    return LoginOut(token=auth.create_token(admin_id=body.admin_id))
