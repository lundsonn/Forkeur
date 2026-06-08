from __future__ import annotations
from constants import DEFAULT_ADDRESS
import asyncio
import inspect
import logging
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
    db.get_client().table("scraper_schedules").upsert({
        "platform": config.platform,
        "cron": config.cron,
        "address": DEFAULT_ADDRESS,
        "max_items": None,
        "updated_at": "now()",
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


async def _run_batch_all() -> None:
    """Two-phase batch to bound peak RAM on 4vCPU/8GB.

    A flat Semaphore(4) cap was not enough: it limits scraper COUNT but not page
    WEIGHT. When the 4 slots happened to hold the 4 heaviest at once —
    ubereats(3 menu pages) + deliveroo(3) + dom_menu(5) + takeaway(own browser)
    ≈ 12 browser pages — RAM hit 7.6GB / 85MB free (near-OOM).

    Fix: run the platform scrapers first, THEN the menu scrapers. dom_menu's 5
    concurrent pages never overlap the ube/del parallel menu workers.

      Phase 1: ubereats, deliveroo, takeaway, direct   (concurrent)
      Phase 2: dom_menu, direct_menu                    (concurrent, field clear)
      then: fees, then: cross-platform match
    """
    from routers.scrapers import _running

    async def _run_direct_menu_threaded():
        from scrapers import direct_menu as _dm
        run_id = db.create_run("direct_menu")
        try:
            result = await _dm.run()
            db.finish_run(run_id, "success", records_saved=result.get("total_scraped", 0))
        except Exception as e:
            db.finish_run(run_id, "failed", error_msg=str(e))
            alerting.send_failure_alert("direct_menu", str(e), run_id)

    # ── Phase 1: platform scrapers (no dom_menu) ──────────────────────────────
    phase1 = [p for p in ("ubereats", "deliveroo", "takeaway", "direct") if p not in _running]
    await asyncio.gather(*[_run_scraper(p) for p in phase1], return_exceptions=True)

    # ── Phase 2: menu scrapers, run with the heavy platform pages gone ────────
    phase2 = [_run_direct_menu_threaded()]
    if "dom_menu" not in _running:
        phase2.append(_run_scraper("dom_menu"))
    await asyncio.gather(*phase2, return_exceptions=True)

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
    _scheduler.shutdown(wait=True)
