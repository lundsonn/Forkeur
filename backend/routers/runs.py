import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from models import ScraperRunOut
import db
from routers.auth_router import require_auth

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[ScraperRunOut])
async def list_runs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return await asyncio.to_thread(db.get_runs, limit=limit, offset=offset)


@router.get("/{run_id}", response_model=ScraperRunOut)
async def get_run(run_id: str):
    run = await asyncio.to_thread(db.get_run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run
