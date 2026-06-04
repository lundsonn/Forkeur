from __future__ import annotations
import os
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
import auth

router = APIRouter(prefix="/auth", tags=["auth"])


def require_auth(authorization: str = Header(default="")) -> None:
    """FastAPI dependency that enforces Bearer token authentication."""
    token = authorization.removeprefix("Bearer ").strip()
    if not auth.verify_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")


class LoginIn(BaseModel):
    password: str


class LoginOut(BaseModel):
    token: str


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn):
    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected:
        raise HTTPException(500, "ADMIN_PASSWORD not configured on the server")
    if body.password != expected:
        raise HTTPException(401, "Invalid password")
    return LoginOut(token=auth.create_token())
