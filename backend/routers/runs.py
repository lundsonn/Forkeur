from fastapi import APIRouter, Depends, HTTPException
from models import ScraperRunOut
import db
from routers.auth_router import require_auth

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[ScraperRunOut])
async def list_runs(limit: int = 50, offset: int = 0):
    return db.get_runs(limit=limit, offset=offset)


@router.get("/{run_id}", response_model=ScraperRunOut)
async def get_run(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run
