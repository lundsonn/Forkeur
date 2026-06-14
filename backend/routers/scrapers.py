from __future__ import annotations
import asyncio
import inspect
import time
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from models import RunTriggerOut, ScraperStatusOut, ScraperConfig, RunTriggerIn, ScraperResult
import alerting
import db
import ws as ws_mod
from scrapers import ubereats, deliveroo, takeaway, direct, direct_menu, match
from scrapers import dom_menu, enrich_contacts, website_finder
from scrapers.base import CloudflareBlockedError
from scrapers.metrics import RamSampler, RunMetrics
from routers.auth_router import require_auth

router = APIRouter(prefix="/scrapers", tags=["scrapers"], dependencies=[Depends(require_auth)])

# Maximum wall-clock seconds each scraper is allowed to run before being killed.
_TIMEOUTS: dict[str, int] = {
    "ubereats":    90 * 60,
    "deliveroo":   60 * 60,
    "takeaway":   150 * 60,
    "direct":      60 * 60,
    "direct_menu": 15 * 60,
    "dom_menu":    60 * 60,
    "match":           15 * 60,
    "enrich":          60 * 60,
    "website_finder":  4 * 60 * 60,
}


async def _direct_menu_adapter(config: ScraperConfig, log_fn) -> ScraperResult:
    result = await direct_menu.run(max_items=config.max_items)
    return ScraperResult(records_saved=result.get("total_scraped", 0))


async def _website_finder_adapter(config: ScraperConfig, log_fn) -> ScraperResult:
    result = await website_finder.run(log=log_fn, limit=config.max_items)
    return ScraperResult(records_saved=result.get("websites_found", 0))


SCRAPERS = {
    "ubereats":        ubereats.run,
    "deliveroo":       deliveroo.run,
    "takeaway":        takeaway.run,
    "direct":          direct.run,
    "direct_menu":     _direct_menu_adapter,
    "dom_menu":        dom_menu.run,
    "match":           match.run,
    "enrich":          enrich_contacts.run,
    "website_finder":  _website_finder_adapter,
}

# Track currently running platforms (also read by scheduler to skip duplicates).
_running: set[str] = set()
_tasks: dict[str, asyncio.Task] = {}
# Tasks not pinned to a platform (e.g. the batch job). Held strictly so the
# event loop does not garbage-collect them mid-run.
_bg_tasks: set[asyncio.Task] = set()
_state_lock = asyncio.Lock()


def _track_bg(task: asyncio.Task) -> None:
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
# No semaphore needed — all Playwright scrapers share one browser instance
# via base.browser_session(). Their asyncio sleeps/waits interleave naturally.


def _is_transient_error(e: Exception) -> bool:
    msg = str(e).lower()
    return (
        "row-level security" in msg
        or "42501" in msg
        or "connection" in msg
        or "econnreset" in msg
        or "feed api not captured" in msg
    )


@router.post("/batch/run")
async def trigger_batch():
    """Trigger all scrapers concurrently (same as the scheduled batch job)."""
    import scheduler as _sched
    _track_bg(asyncio.create_task(_sched._run_batch_all()))
    return {"status": "started"}


@router.post("/{platform}/run", response_model=RunTriggerOut)
async def trigger_run(platform: str, body: RunTriggerIn | None = None):
    if platform not in SCRAPERS:
        raise HTTPException(404, f"Unknown platform: {platform}")
    async with _state_lock:
        if platform in _running:
            raise HTTPException(409, f"{platform} scraper already running")
        _running.add(platform)
        concurrent_with = sorted(_running - {platform})
    try:
        run_id = db.create_run(platform, triggered_by="manual")
    except Exception:
        async with _state_lock:
            _running.discard(platform)
        raise

    metrics = RunMetrics()
    sampler = RamSampler()

    if body is None:
        body = RunTriggerIn()
    _ws_log = ws_mod.make_log_fn(run_id)
    _log_path = f"/tmp/fk_{platform}_{run_id[:8]}.log"
    # Fix A: open the log file once; close it in the _run() finally block.
    _log_fh = open(_log_path, "a")  # noqa: SIM115  (intentionally held open)
    def log_fn(msg: str) -> None:
        _ws_log(msg)
        try:
            # Collapse newlines so a scraper exception cannot inject fake
            # log lines into the audit file via embedded "\n".
            safe = msg.replace("\r", " ").replace("\n", " | ")
            _log_fh.write(f"{time.strftime('%H:%M:%S')} {safe}\n")
            _log_fh.flush()
        except Exception:
            pass
    timeout = _TIMEOUTS.get(platform, 60 * 60)

    # Fix B: precompute scraper_fn and kwargs once, before the retry loop.
    scraper_fn = SCRAPERS[platform]
    sig = inspect.signature(scraper_fn).parameters
    kwargs = {}
    if "run_id" in sig:
        kwargs["run_id"] = run_id
    if "metrics" in sig:
        kwargs["metrics"] = metrics

    async def _run():
        def _finish(status: str, records_saved: int = 0, error_msg: str | None = None) -> None:
            peak_mb, avg_mb = sampler.stop()
            db.finish_run(
                run_id, status, records_saved=records_saved, error_msg=error_msg,
                peak_ram_mb=peak_mb, avg_ram_mb=avg_mb,
                phase_durations=metrics.phase_durations,
                cooldown_hits=metrics.cooldown_hits,
                items_attempted=metrics.items_attempted,
                items_skipped=metrics.items_skipped,
                items_failed=metrics.items_failed,
                concurrent_with=concurrent_with,
            )

        try:
            config = ScraperConfig(
                scrape_menus=body.scrape_menus,
                max_menus=body.max_menus,
                max_items=10 if body.test_mode else None,
                target=body.target,
            )
            # One automatic retry for transient DB/network errors.
            last_exc: Exception | None = None
            for attempt in range(2):
                try:
                    result = await asyncio.wait_for(
                        scraper_fn(config, log_fn, **kwargs),
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

            _finish("success", records_saved=result.records_saved)
            await ws_mod.send_done(run_id, result.records_saved)
        except asyncio.TimeoutError:
            msg = f"timed out after {timeout // 60} min"
            _finish("failed", error_msg=msg)
            await ws_mod.send_error(run_id, msg)
            alerting.send_failure_alert(platform, msg, run_id)
        except CloudflareBlockedError as e:
            metrics.cooldown()
            _finish("blocked", error_msg=str(e))
            await ws_mod.send_error(run_id, str(e))
            alerting.send_failure_alert(platform, str(e), run_id)
        except Exception as e:
            _finish("failed", error_msg=str(e))
            await ws_mod.send_error(run_id, str(e))
            alerting.send_failure_alert(platform, str(e), run_id)
        except BaseException as e:
            _finish("failed", error_msg=f"Process killed: {type(e).__name__}")
            raise
        finally:
            _running.discard(platform)
            _tasks.pop(platform, None)
            try:
                _log_fh.close()
            except Exception:
                pass

    try:
        task = asyncio.create_task(_run())
    except Exception:
        _log_fh.close()
        raise
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
    platforms = ("ubereats", "deliveroo", "takeaway")
    last_runs = db.get_last_successful_run_batch(list(platforms))
    statuses: dict[str, str] = {}
    for platform in platforms:
        run = last_runs.get(platform)
        if run is None:
            statuses[platform] = "never_run"
        else:
            finished = run.get("finished_at") or run.get("started_at")
            if isinstance(finished, str):
                ts = datetime.fromisoformat(finished.replace("Z", "+00:00"))
            else:
                ts = finished
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
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
