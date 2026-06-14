"""Unauthenticated read endpoints for the Next.js frontend.

These mirror the exact nested JSON shapes the frontend's lib/queries.ts
transform consumes (previously fetched from Supabase PostgREST).
"""
import asyncio

from fastapi import APIRouter, HTTPException

import db

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/restaurants")
async def public_restaurants():
    return await asyncio.to_thread(db.get_public_restaurants)


@router.get("/restaurants/{restaurant_id:path}")
async def public_restaurant_detail(restaurant_id: str):
    try:
        row = await asyncio.to_thread(db.get_public_restaurant_detail, restaurant_id)
    except ValueError:
        # Not a UUID — try as slug
        row = await asyncio.to_thread(db.get_public_restaurant_by_slug, restaurant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    return row


@router.get("/deals")
async def public_deals():
    return await asyncio.to_thread(db.get_public_deals)


@router.get("/scraper-runs/latest")
async def public_latest_run(platform: str, since: str | None = None):
    return await asyncio.to_thread(db.get_latest_run, platform, since)
