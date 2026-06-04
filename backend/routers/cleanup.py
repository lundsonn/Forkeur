from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
import db
from routers.auth_router import require_auth

router = APIRouter(prefix="/cleanup", tags=["cleanup"])


class CleanupResult(BaseModel):
    deleted: int
    message: str


@router.post("/stale-listings", response_model=CleanupResult)
async def cleanup_stale_listings(days: int = Query(default=30, ge=1), _=Depends(require_auth)):
    deleted = db.delete_stale_listings(days=days)
    return CleanupResult(
        deleted=deleted,
        message=f"Deleted {deleted} listing(s) older than {days} days.",
    )
