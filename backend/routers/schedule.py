from __future__ import annotations
from fastapi import APIRouter, HTTPException
from models import ScheduleConfigIn, ScheduleConfigOut
from scheduler import add_or_update_schedule, remove_schedule, list_schedules

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("", response_model=list[ScheduleConfigOut])
async def get_schedules():
    return list_schedules()


@router.post("", response_model=ScheduleConfigOut)
async def upsert_schedule(body: ScheduleConfigIn):
    return add_or_update_schedule(body)


@router.delete("/{platform}", status_code=204)
async def delete_schedule(platform: str):
    removed = remove_schedule(platform)
    if not removed:
        raise HTTPException(404, f"No schedule for {platform}")
