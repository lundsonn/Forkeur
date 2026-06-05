from __future__ import annotations
import re
from fastapi import APIRouter, Depends, HTTPException
from models import ScheduleConfigIn, ScheduleConfigOut
from scheduler import add_or_update_schedule, remove_schedule, list_schedules
from routers.auth_router import require_auth
from routers.scrapers import SCRAPERS

router = APIRouter(prefix="/schedules", tags=["schedules"], dependencies=[Depends(require_auth)])

# Valid cron field: digit, *, */n, n-m, or comma-separated list of those.
_CRON_FIELD = r'(?:\*(?:/\d+)?|\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)'
_CRON_RE = re.compile(rf'^{_CRON_FIELD}\s+{_CRON_FIELD}\s+{_CRON_FIELD}\s+{_CRON_FIELD}\s+{_CRON_FIELD}$')


def _validate_schedule(body: ScheduleConfigIn) -> None:
    if body.platform not in SCRAPERS:
        raise HTTPException(400, f"Unknown platform: {body.platform!r}")
    for part in body.cron.split("|"):
        if not _CRON_RE.match(part.strip()):
            raise HTTPException(400, f"Invalid cron expression: {body.cron!r}")


@router.get("", response_model=list[ScheduleConfigOut])
async def get_schedules():
    return list_schedules()


@router.post("", response_model=ScheduleConfigOut)
async def upsert_schedule(body: ScheduleConfigIn):
    _validate_schedule(body)
    return add_or_update_schedule(body)


@router.delete("/{platform}", status_code=204)
async def delete_schedule(platform: str):
    removed = remove_schedule(platform)
    if not removed:
        raise HTTPException(404, f"No schedule for {platform}")
