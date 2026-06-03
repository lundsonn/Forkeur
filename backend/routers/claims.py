from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, HttpUrl

import db

router = APIRouter(prefix="/claims", tags=["claims"])


class ClaimIn(BaseModel):
    restaurant_id: UUID
    owner_email: EmailStr
    direct_order_url: HttpUrl


class ClaimOut(BaseModel):
    id: str
    restaurant_id: str
    owner_email: str
    direct_order_url: str
    verified: bool
    claimed_at: str | None = None
    restaurants: dict | None = None


@router.post("", status_code=201)
async def submit_claim(body: ClaimIn):
    claim_id = db.insert_claim(
        restaurant_id=str(body.restaurant_id),
        owner_email=body.owner_email,
        direct_order_url=str(body.direct_order_url),
    )
    return {"claim_id": claim_id}


@router.get("", response_model=list[ClaimOut])
async def list_claims(verified: bool | None = None):
    return db.get_claims(verified=verified)


@router.post("/{claim_id}/approve")
async def approve_claim(claim_id: str):
    try:
        db.approve_claim(claim_id)
    except (IndexError, KeyError, ValueError):
        raise HTTPException(404, "Claim not found")
    return {"status": "approved"}


@router.post("/{claim_id}/reject")
async def reject_claim(claim_id: str):
    try:
        db.reject_claim(claim_id)
    except (IndexError, KeyError, ValueError):
        raise HTTPException(404, "Claim not found")
    return {"status": "rejected"}
