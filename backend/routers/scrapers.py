from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException
from models import RunTriggerOut, ScraperStatusOut, ScraperConfig, RunTriggerIn, ScraperResult
import alerting
import db
import ws as ws_mod
from scrapers import ubereats, deliveroo, takeaway, fees, direct, direct_menu
from scrapers import dom_menu
from scrapers.base import CloudflareBlockedError

router = APIRouter(prefix="/scrapers", tags=["scrapers"])

# Maximum wall-clock seconds each scraper is allowed to run before being killed.
_TIMEOUTS: dict[str, int] = {
    "ubereats":    90 * 60,
    "deliveroo":   60 * 60,
    "takeaway":    60 * 60,
    "direct":      30 * 60,
    "direct_menu": 15 * 60,
    "dom_menu":    60 * 60,
}


async def _direct_menu_adapter(config: ScraperConfig, log_fn) -> ScraperResult:
    """Adapter to run direct_menu.run() (sync) via the standard async interface."""
    result = direct_menu.run(max_items=config.max_items)
    return ScraperResult(records_saved=result.get("total_scraped", 0))


SCRAPERS = {
    "ubereats":    ubereats.run,
    "deliveroo":   deliveroo.run,
    "takeaway":    takeaway.run,
    "direct":      direct.run,
    "direct_menu": _direct_menu_adapter,
    "dom_menu":    dom_menu.run,
}

# Track currently running platforms (also read by scheduler to skip duplicates).
_running: set[str] = set()
_tasks: dict[str, asyncio.Task] = {}
_fees_running: bool = False

# Heavy scrapers (large platforms, many Chromium tabs) — max 1 at a time.
_HEAVY_SCRAPERS = {"ubereats", "deliveroo", "takeaway"}
# Light scrapers (individual sites, single tab) — max 1 at a time, but
# can run concurrently with a heavy scraper.
_LIGHT_SCRAPERS = {"direct", "dom_menu"}
_heavy_sem = asyncio.Semaphore(1)
_light_sem = asyncio.Semaphore(1)


def _is_transient_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (
        "row-level security" in msg
        or "42501" in msg
        or "connection" in msg
        or "econnreset" in msg
    )


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
            counts = await asyncio.wait_for(fees.run(log_fn), timeout=120 * 60)
            total = sum(counts.values())
            db.finish_run(run_id, "success", records_saved=total)
            await ws_mod.send_done(run_id, total)
        except asyncio.TimeoutError:
            msg = "timed out after 120 min"
            db.finish_run(run_id, "failed", error_msg=msg)
            await ws_mod.send_error(run_id, msg)
            alerting.send_failure_alert("fees", msg, run_id)
        except Exception as e:
            db.finish_run(run_id, "failed", error_msg=str(e))
            await ws_mod.send_error(run_id, str(e))
            alerting.send_failure_alert("fees", str(e), run_id)
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


@router.post("/{platform}/run", response_model=RunTriggerOut)
async def trigger_run(platform: str, body: RunTriggerIn | None = None):
    if platform not in SCRAPERS:
        raise HTTPException(404, f"Unknown platform: {platform}")
    if platform in _running:
        raise HTTPException(409, f"{platform} scraper already running")

    if body is None:
        body = RunTriggerIn()

    run_id = db.create_run(platform)
    log_fn = ws_mod.make_log_fn(run_id)
    timeout = _TIMEOUTS.get(platform, 60 * 60)

    async def _run():
        _running.add(platform)
        try:
            config = ScraperConfig(
                scrape_menus=body.scrape_menus,
                max_menus=body.max_menus,
                max_items=10 if body.test_mode else None,
            )
            if platform in _HEAVY_SCRAPERS:
                sem = _heavy_sem
            elif platform in _LIGHT_SCRAPERS:
                sem = _light_sem
            else:
                sem = None
            if sem:
                log_fn(f"  waiting for browser slot...")
                await sem.acquire()
                log_fn(f"  browser slot acquired")
            # One automatic retry for transient DB/network errors.
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    result = await asyncio.wait_for(
                        SCRAPERS[platform](config, log_fn),
                        timeout=timeout,
                    )
                    break
                except asyncio.TimeoutError:
                    raise
                except Exception as e:
                    last_exc = e
                    if attempt == 0 and _is_transient_error(e):
                        log_fn(f"  transient error ({e}), retrying in 60s...")
                        await asyncio.sleep(60)
                    else:
                        raise
            else:
                raise last_exc  # both attempts failed

            db.finish_run(run_id, "success", records_saved=result.records_saved)
            await ws_mod.send_done(run_id, result.records_saved)
        except asyncio.TimeoutError:
            msg = f"timed out after {timeout // 60} min"
            db.finish_run(run_id, "failed", error_msg=msg)
            await ws_mod.send_error(run_id, msg)
            alerting.send_failure_alert(platform, msg, run_id)
        except CloudflareBlockedError as e:
            db.finish_run(run_id, "blocked", error_msg=str(e))
            await ws_mod.send_error(run_id, str(e))
            alerting.send_failure_alert(platform, str(e), run_id)
        except Exception as e:
            db.finish_run(run_id, "failed", error_msg=str(e))
            await ws_mod.send_error(run_id, str(e))
            alerting.send_failure_alert(platform, str(e), run_id)
        except BaseException as e:
            db.finish_run(run_id, "failed", error_msg=f"Process killed: {type(e).__name__}")
            raise
        finally:
            if sem:
                sem.release()
            _running.discard(platform)
            _tasks.pop(platform, None)

    task = asyncio.create_task(_run())
    _tasks[platform] = task
    return RunTriggerOut(run_id=run_id)


@router.get("/status", response_model=list[ScraperStatusOut])
async def get_status():
    last_runs = db.get_last_run_per_platform()
    result = []
    for platform in ("ubereats", "deliveroo", "takeaway", "direct", "direct_menu", "dom_menu"):
        last = last_runs.get(platform)
        status = "running" if platform in _running else (last["status"] if last else "idle")
        result.append(ScraperStatusOut(
            platform=platform,
            status=status,
            last_run=last,
        ))
    return result


@router.get("/health")
async def health_check():
    """Returns degraded if any core platform hasn't had a successful run in 25 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=25)
    statuses: dict[str, str] = {}
    for platform in ("ubereats", "deliveroo", "takeaway"):
        run = db.get_last_successful_run(platform)
        if run is None:
            statuses[platform] = "never_run"
        else:
            finished = run.get("finished_at") or run.get("started_at")
            ts = datetime.fromisoformat(finished.replace("Z", "+00:00"))
            statuses[platform] = "ok" if ts >= cutoff else "stale"

    overall = "ok" if all(v == "ok" for v in statuses.values()) else "degraded"
    return {"status": overall, "platforms": statuses}


@router.post("/{platform}/stop")
async def stop_scraper(platform: str):
    if platform not in SCRAPERS:
        raise HTTPException(404, f"Unknown platform: {platform}")
    if platform not in _running:
        raise HTTPException(400, f"{platform} scraper not running")

    task = _tasks.get(platform)
    if task:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    _running.discard(platform)
    _tasks.pop(platform, None)
    return {"status": "stopped", "platform": platform}
