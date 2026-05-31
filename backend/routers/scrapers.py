from __future__ import annotations
import asyncio
from fastapi import APIRouter, HTTPException
from models import RunTriggerOut, ScraperStatusOut, ScraperConfig, RunTriggerIn
import db
import ws as ws_mod
from scrapers import ubereats, deliveroo, takeaway
from scrapers.base import CloudflareBlockedError

router = APIRouter(prefix="/scrapers", tags=["scrapers"])

SCRAPERS = {
    "ubereats": ubereats.run,
    "deliveroo": deliveroo.run,
    "takeaway": takeaway.run,
}

# Track currently running platforms
_running: set[str] = set()


@router.post("/{platform}/run", response_model=RunTriggerOut)
async def trigger_run(platform: str, body: RunTriggerIn | None = None):
    if platform not in SCRAPERS:
        raise HTTPException(404, f"Unknown platform: {platform}")
    if platform in _running:
        raise HTTPException(409, f"{platform} scraper already running")

    # Use defaults if no body provided
    if body is None:
        body = RunTriggerIn()

    run_id = db.create_run(platform)
    log_fn = ws_mod.make_log_fn(run_id)

    async def _run():
        _running.add(platform)
        try:
            config = ScraperConfig(
                scrape_menus=body.scrape_menus,
                max_menus=body.max_menus
            )
            result = await SCRAPERS[platform](config, log_fn)
            db.finish_run(run_id, "success", records_saved=result.records_saved)
            await ws_mod.send_done(run_id, result.records_saved)
        except CloudflareBlockedError as e:
            db.finish_run(run_id, "blocked", error_msg=str(e))
            await ws_mod.send_error(run_id, str(e))
        except Exception as e:
            db.finish_run(run_id, "failed", error_msg=str(e))
            await ws_mod.send_error(run_id, str(e))
        finally:
            _running.discard(platform)

    asyncio.create_task(_run())
    return RunTriggerOut(run_id=run_id)


@router.get("/status", response_model=list[ScraperStatusOut])
async def get_status():
    last_runs = db.get_last_run_per_platform()
    result = []
    for platform in ("ubereats", "deliveroo", "takeaway"):
        last = last_runs.get(platform)
        status = "running" if platform in _running else (last["status"] if last else "idle")
        result.append(ScraperStatusOut(
            platform=platform,
            status=status,
            last_run=last,
        ))
    return result
