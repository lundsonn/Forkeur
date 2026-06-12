from __future__ import annotations
from constants import DEFAULT_ADDRESS
import asyncio
import inspect
import logging
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.combining import OrTrigger
from models import ScraperConfig, ScheduleConfigIn, ScheduleConfigOut
from scrapers.base import CloudflareBlockedError
import alerting
import db

_log = logging.getLogger("forkeur.scheduler")
_scheduler = AsyncIOScheduler()
_schedules: dict[str, ScheduleConfigIn] = {}

_CLEANUP_JOB_ID = "daily_cleanup"
_CLEANUP_CRON = "0 4 * * *"   # 04:00 UTC daily

_DIGEST_JOB_ID = "daily_digest"
_DIGEST_CRON = "0 19 * * *"   # 19:00 UTC = 21:00 Brussels (CEST)

_BATCH_JOB_ID = "batch_all"

def _noop(line: str) -> None:
    # Forwards scraper log-fn output into the scheduler logger so cron-driven
    # runs are visible in journald instead of silently disappearing.
    _log.info("%s", line)


async def _run_scraper(platform: str) -> None:
    # Skip if the same platform is already running (triggered manually via API).
    from routers.scrapers import _running, _tasks
    if platform in _running:
        _noop(f"Scheduler: {platform} already running, skipping")
        return

    # Fix D: mark platform as running so the status endpoint reflects it and
    # the stop endpoint can cancel it; always discard in the finally block.
    _running.add(platform)
    _tasks[platform] = asyncio.current_task()
    try:
        from scrapers import ubereats, deliveroo, takeaway, direct, direct_menu
        from scrapers import dom_menu

        if platform == "direct_menu":
            run_id = db.create_run(platform)
            try:
                result = await direct_menu.run()
                db.finish_run(run_id, "success", records_saved=result.get("total_scraped", 0))
            except Exception as e:
                db.finish_run(run_id, "failed", error_msg=str(e))
                alerting.send_failure_alert(platform, str(e), run_id)
            return

        SCRAPERS = {
            "ubereats":  ubereats.run,
            "deliveroo": deliveroo.run,
            "takeaway":  takeaway.run,
            "direct":    direct.run,
            "dom_menu":  dom_menu.run,
        }
        if platform not in SCRAPERS:
            return

        # No semaphore — all scrapers share one Chromium via base.browser_session();
        # their asyncio waits interleave so concurrent runs are safe.
        run_id = db.create_run(platform)
        scraper_fn = SCRAPERS[platform]
        kwargs = {"run_id": run_id} if "run_id" in inspect.signature(scraper_fn).parameters else {}
        try:
            result = await scraper_fn(ScraperConfig(), _noop, **kwargs)
            db.finish_run(run_id, "success", records_saved=result.records_saved)
        except CloudflareBlockedError as e:
            db.finish_run(run_id, "blocked", error_msg=str(e))
            alerting.send_failure_alert(platform, str(e), run_id)
        except Exception as e:
            db.finish_run(run_id, "failed", error_msg=str(e))
            alerting.send_failure_alert(platform, str(e), run_id)
    finally:
        _running.discard(platform)
        _tasks.pop(platform, None)


def _persist_schedule(config: ScheduleConfigIn) -> None:
    # updated_at omitted: the column defaults to now() on insert. (The old
    # Supabase code passed the string "now()", which does not cast to
    # timestamptz under plain SQL.)
    db.get_client().table("scraper_schedules").upsert({
        "platform": config.platform,
        "cron": config.cron,
        "address": DEFAULT_ADDRESS,
        "max_items": None,
    }, on_conflict="platform").execute()


def _delete_persisted_schedule(platform: str) -> None:
    db.get_client().table("scraper_schedules").delete().eq("platform", platform).execute()


def _load_persisted_schedules() -> list[ScheduleConfigIn]:
    try:
        rows = db.get_client().table("scraper_schedules").select("*").execute().data
        return [ScheduleConfigIn(platform=r["platform"], cron=r["cron"], enabled=True) for r in rows]
    except Exception:
        return []


def add_or_update_schedule(config: ScheduleConfigIn) -> ScheduleConfigOut:
    job_id = f"scraper_{config.platform}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)

    _schedules[config.platform] = config

    if config.enabled:
        _persist_schedule(config)
        parts = [p.strip() for p in config.cron.split("|") if p.strip()]
        trigger = OrTrigger([CronTrigger.from_crontab(p) for p in parts]) if len(parts) > 1 else CronTrigger.from_crontab(parts[0])
        job = _scheduler.add_job(
            _run_scraper,
            trigger,
            id=job_id,
            args=[config.platform],
        )
        next_run = job.next_run_time
    else:
        _delete_persisted_schedule(config.platform)
        next_run = None

    return ScheduleConfigOut(**config.model_dump(), next_run=next_run)


def remove_schedule(platform: str) -> bool:
    job_id = f"scraper_{platform}"
    if _scheduler.get_job(job_id):
        _scheduler.remove_job(job_id)
        _schedules.pop(platform, None)
        _delete_persisted_schedule(platform)
        return True
    return False


def list_schedules() -> list[ScheduleConfigOut]:
    result = []
    for platform, cfg in _schedules.items():
        job = _scheduler.get_job(f"scraper_{platform}")
        result.append(ScheduleConfigOut(**cfg.model_dump(), next_run=job.next_run_time if job else None))
    return result


# dom_menu launch gate: hold while MemAvailable is below this (GB). The 8GB box
# near-OOMed at 85MB free when all browser scrapers stacked; 2GB headroom keeps
# the OOM killer away while still letting dom_menu start early.
_MEM_GATE_GB = float(os.getenv("BATCH_MEM_GATE_GB", "2.0"))
_MEM_GATE_POLL_S = 15
_MEM_GATE_TIMEOUT_S = 3600


def _mem_available_gb() -> float:
    """MemAvailable from /proc/meminfo in GB; inf where unreadable (macOS dev)."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except OSError:
        pass
    return float("inf")


async def _run_batch_all() -> None:
    """Memory-gated batch to bound peak RAM on 4vCPU/8GB without idle time.

    A flat Semaphore(4) caps scraper COUNT but not page WEIGHT: with
    ubereats(3 menu pages) + deliveroo(3) + dom_menu(5) + takeaway(own browser)
    ≈ 12 browser pages, RAM hit 7.6GB / 85MB free (near-OOM). The previous fix
    was a hard two-phase barrier (platforms, then menus), which is safe but
    wastes wall clock: dom_menu idled until the SLOWEST platform scraper
    finished, and direct_menu (plain httpx, zero browser pages) idled with it.

      - ubereats, deliveroo, takeaway, direct, direct_menu start together
      - dom_menu launches once (a) at least one heavy platform scraper has
        finished — its 5 pages never stack on the full platform load — and
        (b) MemAvailable ≥ BATCH_MEM_GATE_GB
      - then: cross-platform match
    """
    from routers.scrapers import _running

    heavy = [p for p in ("ubereats", "deliveroo", "takeaway", "direct") if p not in _running]
    heavy_tasks = [asyncio.create_task(_run_scraper(p)) for p in heavy]

    async def _gated_dom_menu() -> None:
        if heavy_tasks:
            await asyncio.wait(heavy_tasks, return_when=asyncio.FIRST_COMPLETED)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _MEM_GATE_TIMEOUT_S
        while _mem_available_gb() < _MEM_GATE_GB:
            if loop.time() >= deadline:
                _noop(f"Batch: memory gate still closed after {_MEM_GATE_TIMEOUT_S}s, launching dom_menu anyway")
                break
            await asyncio.sleep(_MEM_GATE_POLL_S)
        await _run_scraper("dom_menu")

    await asyncio.gather(
        *heavy_tasks,
        _run_scraper("direct_menu"),
        _gated_dom_menu(),
        return_exceptions=True,
    )

    # Reconcile cross-platform duplicates after all data is fresh.
    await _run_match()


async def _run_match() -> None:
    from scrapers import match as _match
    run_id = db.create_run("match")
    try:
        result = await asyncio.to_thread(_match.run_sync, dry_run=False, log_fn=_noop)
        db.finish_run(run_id, "success", records_saved=result["auto_merge"])
    except Exception as e:
        db.finish_run(run_id, "failed", error_msg=str(e))
        alerting.send_failure_alert("match", str(e), run_id)


async def _run_daily_cleanup() -> None:
    pruned = await asyncio.to_thread(db.prune_stale_menu_items, days=30)
    if pruned:
        _noop(f"Daily cleanup: pruned {pruned} stale menu items")


async def _run_daily_digest() -> None:
    alerting.send_daily_digest()


def start() -> None:
    _scheduler.add_job(
        _run_daily_cleanup,
        CronTrigger.from_crontab(_CLEANUP_CRON),
        id=_CLEANUP_JOB_ID,
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_daily_digest,
        CronTrigger.from_crontab(_DIGEST_CRON),
        id=_DIGEST_JOB_ID,
        replace_existing=True,
    )
    for config in _load_persisted_schedules():
        _schedules[config.platform] = config
        parts = [p.strip() for p in config.cron.split("|") if p.strip()]
        trigger = OrTrigger([CronTrigger.from_crontab(p) for p in parts]) if len(parts) > 1 else CronTrigger.from_crontab(parts[0])
        _scheduler.add_job(
            _run_scraper,
            trigger,
            id=f"scraper_{config.platform}",
            args=[config.platform],
            replace_existing=True,
        )
    _scheduler.start()


def shutdown() -> None:
    _scheduler.shutdown(wait=False)
