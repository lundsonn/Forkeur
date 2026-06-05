from __future__ import annotations
import hmac
import os
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
import auth

router = APIRouter(prefix="/auth", tags=["auth"])


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
async def login(body: LoginIn):
    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected:
        raise HTTPException(500, "ADMIN_PASSWORD not configured on the server")
    if not hmac.compare_digest(body.password, expected):
        raise HTTPException(401, "Invalid password")
    return LoginOut(token=auth.create_token(admin_id=body.admin_id))
