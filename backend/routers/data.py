from fastapi import APIRouter
from models import RestaurantOut, MenuItemOut
import db

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/restaurants", response_model=list[RestaurantOut])
async def list_restaurants(limit: int = 100, offset: int = 0, search: str | None = None):
    return db.get_restaurants(limit=limit, offset=offset, search=search)


@router.get("/menu-items/{listing_id}", response_model=list[MenuItemOut])
async def list_menu_items(listing_id: str):
    return db.get_menu_items(listing_id)
