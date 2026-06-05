import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from models import RestaurantOut, MenuItemOut
import db
from routers.auth_router import require_auth

router = APIRouter(prefix="/data", tags=["data"], dependencies=[Depends(require_auth)])


@router.get("/restaurants", response_model=list[RestaurantOut])
async def list_restaurants(limit: int = 100, offset: int = 0, search: str | None = None):
    return await asyncio.to_thread(
        db.get_restaurants, limit=limit, offset=offset, search=search
    )


@router.get("/menu-items/{listing_id}", response_model=list[MenuItemOut])
async def list_menu_items(listing_id: str):
    return await asyncio.to_thread(db.get_menu_items, listing_id)


class ResolveIn(BaseModel):
    approve: bool
    resolved_by: str = "admin"


@router.get("/match-queue")
async def match_queue():
    return await asyncio.to_thread(db.get_queued_decisions)


@router.post("/match-queue/{decision_id}/resolve")
async def resolve_match(decision_id: str, body: ResolveIn):
    await asyncio.to_thread(
        db.resolve_decision,
        decision_id,
        approve=body.approve,
        resolved_by=body.resolved_by,
    )
    return {"status": "ok"}
