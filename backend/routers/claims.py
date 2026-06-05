from __future__ import annotations

import asyncio
import html
import ipaddress
import os
import time
from collections import deque
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, HttpUrl, model_validator

import db
from routers.auth_router import require_auth


def _parse_trusted_proxies() -> list:
    """TRUSTED_PROXIES is a comma-separated list of CIDRs whose X-Forwarded-For
    header is honoured. Anything else: we use the socket peer IP directly so
    spoofed XFF cannot defeat the per-IP rate limit."""
    raw = os.environ.get("TRUSTED_PROXIES", "")
    nets = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return nets


_TRUSTED_PROXIES = _parse_trusted_proxies()


def _client_ip(request: Request) -> str:
    peer = (request.client.host if request.client else "?") or "?"
    if not _TRUSTED_PROXIES:
        return peer
    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not any(peer_addr in net for net in _TRUSTED_PROXIES):
        return peer
    fwd = request.headers.get("x-forwarded-for", "")
    if not fwd:
        return peer
    first = fwd.split(",")[0].strip()
    return first or peer

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
    admin_base = os.getenv("ADMIN_DASHBOARD_URL", "").rstrip("/")
    type_labels = {"add_url": "Add URL", "new_listing": "New listing", "remove": "Remove"}
    restaurant = body.restaurant_name_free or str(body.restaurant_id or "unknown")
    # Escape every interpolated value — user input ends up inside an HTML email
    # template, so an injected </td><script>… would be rendered by most clients.
    e_type = html.escape(type_labels.get(body.inquiry_type, body.inquiry_type))
    e_restaurant = html.escape(restaurant)
    e_email = html.escape(body.owner_email)
    e_url = html.escape(str(body.direct_order_url)) if body.direct_order_url else ""
    e_admin_base = html.escape(admin_base, quote=True)
    subject = f"[Forkeur] New owner inquiry — {e_type}: {e_restaurant}"
    review_link = f'<p><a href="{e_admin_base}/claims">Review in admin →</a></p>' if admin_base else ""
    body_html = (
        f"<p><strong>Type:</strong> {e_type}</p>"
        f"<p><strong>Restaurant:</strong> {e_restaurant}</p>"
        f"<p><strong>Email:</strong> {e_email}</p>"
        + (f"<p><strong>URL:</strong> {e_url}</p>" if e_url else "")
        + review_link
    )
    try:
        httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": "Forkeur <noreply@forkeur.be>", "to": [notify_to], "subject": subject, "html": body_html},
            timeout=5,
        )
    except Exception:
        pass  # never block the claim submission


# Per-IP submission rate limit (in-memory; sufficient for single-process backend).
_RATE_WINDOW_S = 3600
_RATE_MAX = 10
_recent: dict[str, deque[float]] = {}


def _rate_check(ip: str) -> None:
    now = time.monotonic()
    bucket = _recent.setdefault(ip, deque())
    while bucket and now - bucket[0] > _RATE_WINDOW_S:
        bucket.popleft()
    if len(bucket) >= _RATE_MAX:
        raise HTTPException(429, "Too many submissions, try again later")
    bucket.append(now)


@router.post("", status_code=201)
async def submit_claim(body: ClaimIn, request: Request):
    _rate_check(_client_ip(request))

    # Vet the URL before persisting — previously only checked at approval time,
    # so the DB could accumulate malicious or internal URLs.
    if body.direct_order_url:
        try:
            db._validate_order_url(str(body.direct_order_url))
        except ValueError as e:
            raise HTTPException(400, str(e))

    claim_id = await asyncio.to_thread(
        db.insert_claim,
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
    return await asyncio.to_thread(db.get_claims, verified=verified)


@router.post("/{claim_id}/approve", dependencies=[Depends(require_auth)])
async def approve_claim(claim_id: str):
    try:
        await asyncio.to_thread(db.approve_claim, claim_id)
    except (IndexError, KeyError, ValueError):
        raise HTTPException(404, "Claim not found")
    return {"status": "approved"}


@router.post("/{claim_id}/reject", dependencies=[Depends(require_auth)])
async def reject_claim(claim_id: str):
    try:
        await asyncio.to_thread(db.reject_claim, claim_id)
    except (IndexError, KeyError, ValueError):
        raise HTTPException(404, "Claim not found")
    return {"status": "rejected"}
