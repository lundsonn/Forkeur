from __future__ import annotations

import os
import httpx
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, HttpUrl, model_validator

import db
from routers.auth_router import require_auth

router = APIRouter(prefix="/claims", tags=["claims"])

InquiryType = Literal["add_url", "new_listing", "remove"]


class ClaimIn(BaseModel):
    inquiry_type: InquiryType = "add_url"
    owner_email: EmailStr
    restaurant_id: UUID | None = None
    direct_order_url: HttpUrl | None = None
    restaurant_name_free: str | None = None

    @model_validator(mode="after")
    def check_fields(self) -> "ClaimIn":
        if self.inquiry_type == "add_url" and not self.direct_order_url:
            raise ValueError("direct_order_url is required for add_url inquiries")
        if self.inquiry_type == "new_listing" and not self.restaurant_name_free:
            raise ValueError("restaurant_name_free is required for new_listing inquiries")
        return self


class ClaimOut(BaseModel):
    id: str
    restaurant_id: str | None = None
    owner_email: str
    direct_order_url: str | None = None
    inquiry_type: str = "add_url"
    restaurant_name_free: str | None = None
    verified: bool
    claimed_at: str | None = None
    restaurants: dict | None = None


def _notify_new_claim(body: ClaimIn, claim_id: str) -> None:
    """Fire-and-forget email notification via Resend. Silently skips if not configured."""
    api_key = os.getenv("RESEND_API_KEY")
    notify_to = os.getenv("NOTIFICATION_EMAIL")
    if not api_key or not notify_to:
        return
    type_labels = {"add_url": "Add URL", "new_listing": "New listing", "remove": "Remove"}
    restaurant = body.restaurant_name_free or str(body.restaurant_id or "unknown")
    subject = f"[Forkeur] New owner inquiry — {type_labels.get(body.inquiry_type, body.inquiry_type)}: {restaurant}"
    html = (
        f"<p><strong>Type:</strong> {body.inquiry_type}</p>"
        f"<p><strong>Restaurant:</strong> {restaurant}</p>"
        f"<p><strong>Email:</strong> {body.owner_email}</p>"
        + (f"<p><strong>URL:</strong> {body.direct_order_url}</p>" if body.direct_order_url else "")
        + f"<p><a href='http://178.104.57.72:5173/claims'>Review in admin →</a></p>"
    )
    try:
        httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": "Forkeur <noreply@forkeur.be>", "to": [notify_to], "subject": subject, "html": html},
            timeout=5,
        )
    except Exception:
        pass  # never block the claim submission


@router.post("", status_code=201)
async def submit_claim(body: ClaimIn):
    claim_id = db.insert_claim(
        owner_email=body.owner_email,
        inquiry_type=body.inquiry_type,
        restaurant_id=str(body.restaurant_id) if body.restaurant_id else None,
        direct_order_url=str(body.direct_order_url) if body.direct_order_url else None,
        restaurant_name_free=body.restaurant_name_free,
    )
    _notify_new_claim(body, claim_id)
    return {"claim_id": claim_id}


@router.get("", response_model=list[ClaimOut], dependencies=[Depends(require_auth)])
async def list_claims(verified: bool | None = None):
    return db.get_claims(verified=verified)


@router.post("/{claim_id}/approve", dependencies=[Depends(require_auth)])
async def approve_claim(claim_id: str):
    try:
        db.approve_claim(claim_id)
    except (IndexError, KeyError, ValueError):
        raise HTTPException(404, "Claim not found")
    return {"status": "approved"}


@router.post("/{claim_id}/reject", dependencies=[Depends(require_auth)])
async def reject_claim(claim_id: str):
    try:
        db.reject_claim(claim_id)
    except (IndexError, KeyError, ValueError):
        raise HTTPException(404, "Claim not found")
    return {"status": "rejected"}
