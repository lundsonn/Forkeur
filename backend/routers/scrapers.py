from __future__ import annotations
import asyncio
from fastapi import APIRouter, HTTPException
from models import RunTriggerOut, ScraperStatusOut, ScraperConfig, RunTriggerIn
import db
import ws as ws_mod
from scrapers import ubereats, deliveroo, takeaway, fees, direct
from scrapers.base import CloudflareBlockedError

router = APIRouter(prefix="/scrapers", tags=["scrapers"])

SCRAPERS = {
    "ubereats": ubereats.run,
    "deliveroo": deliveroo.run,
    "takeaway": takeaway.run,
    "direct": direct.run,
}

# Track currently running platforms
_running: set[str] = set()
_tasks: dict[str, asyncio.Task] = {}
_fees_running: bool = False


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
                max_menus=body.max_menus,
                max_items=10 if body.test_mode else None,
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
        except BaseException as e:
            # asyncio.CancelledError and other non-Exception BaseExceptions
            db.finish_run(run_id, "failed", error_msg=f"Process killed: {type(e).__name__}")
            raise
        finally:
            _running.discard(platform)

    task = asyncio.create_task(_run())
    _tasks[platform] = task
    return RunTriggerOut(run_id=run_id)


@router.get("/status", response_model=list[ScraperStatusOut])
async def get_status():
    last_runs = db.get_last_run_per_platform()
    result = []
    for platform in ("ubereats", "deliveroo", "takeaway", "direct"):
        last = last_runs.get(platform)
        status = "running" if platform in _running else (last["status"] if last else "idle")
        result.append(ScraperStatusOut(
            platform=platform,
            status=status,
            last_run=last,
        ))
    return result


@router.post("/fees/run")
async def trigger_fees():
    """Trigger a fee refresh run (delivery_fee + min_order for all known listings)."""
    global _fees_running
    if _fees_running:
        raise HTTPException(409, "Fee refresh already running")

    run_id = db.create_run("fees")

    async def _run():
        global _fees_running
        _fees_running = True
        log_fn = ws_mod.make_log_fn(run_id)
        try:
            counts = await fees.run(log_fn)
            total = sum(counts.values())
            db.finish_run(run_id, "success", records_saved=total)
            await ws_mod.send_done(run_id, total)
        except Exception as e:
            db.finish_run(run_id, "failed", error_msg=str(e))
            await ws_mod.send_error(run_id, str(e))
        finally:
            _fees_running = False

    asyncio.create_task(_run())
    return RunTriggerOut(run_id=run_id)


@router.get("/fees/status")
async def fees_status():
    import scheduler
    return {
        "running": _fees_running,
        "next_run": scheduler.get_fee_next_run(),
    }


@router.post("/{platform}/stop")
async def stop_scraper(platform: str):
    if platform not in SCRAPERS:
        raise HTTPException(404, f"Unknown platform: {platform}")
    if platform not in _running:
        raise HTTPException(400, f"{platform} scraper not running")

    # Cancel the task
    if platform in _tasks:
        task = _tasks[platform]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        del _tasks[platform]

    _running.discard(platform)
    return {"status": "stopped", "platform": platform}
