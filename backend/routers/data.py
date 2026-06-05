import asyncio

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from models import RestaurantOut, MenuItemOut
import db
from routers.auth_router import require_auth

router = APIRouter(prefix="/data", tags=["data"], dependencies=[Depends(require_auth)])


@router.get("/restaurants", response_model=list[RestaurantOut])
async def list_restaurants(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, max_length=100),
):
    return await asyncio.to_thread(
        db.get_restaurants, limit=limit, offset=offset, search=search
    )


@router.get("/menu-items/{listing_id}", response_model=list[MenuItemOut])
async def list_menu_items(listing_id: str):
    return await asyncio.to_thread(db.get_menu_items, listing_id)


class SetChainIn(BaseModel):
    is_chain: bool


@router.patch("/restaurants/{restaurant_id}/chain", response_model=RestaurantOut)
async def set_chain(restaurant_id: str, body: SetChainIn):
    return await asyncio.to_thread(db.set_restaurant_chain, restaurant_id, body.is_chain)


class ResolveIn(BaseModel):
    approve: bool


@router.get("/match-queue")
async def match_queue(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return await asyncio.to_thread(db.get_queued_decisions, limit=limit, offset=offset)


@router.post("/match-queue/{decision_id}/resolve")
async def resolve_match(
    decision_id: str,
    body: ResolveIn,
    identity: str = Depends(require_auth),
):
    # resolved_by is authoritatively the authenticated admin's JWT sub —
    # not a request-body field — so the audit trail can't be spoofed by a
    # legitimate but curious caller.
    await asyncio.to_thread(
        db.resolve_decision,
        decision_id,
        approve=body.approve,
        resolved_by=identity,
    )
    return {"status": "ok"}
