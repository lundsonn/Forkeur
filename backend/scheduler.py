from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from models import ScraperConfig, ScheduleConfigIn, ScheduleConfigOut
from scrapers.base import CloudflareBlockedError
import db

_scheduler = AsyncIOScheduler()
_schedules: dict[str, ScheduleConfigIn] = {}

# Fee refresh: after each meal-aligned scraper batch (lunch 06:30, dinner 13:30)
_FEE_JOB_ID = "fee_refresh"
_FEE_CRON = "15 8,15 * * *"   # 08:15 / 15:15 UTC — once heavies have finished

_CLEANUP_JOB_ID = "daily_cleanup"
_CLEANUP_CRON = "0 4 * * *"   # 04:00 UTC daily

_DIGEST_JOB_ID = "daily_digest"
_DIGEST_CRON = "0 19 * * *"   # 19:00 UTC = 21:00 Brussels (CEST)


def _noop(line: str) -> None:
    pass


async def _run_scraper(platform: str) -> None:
    # Skip if the same platform is already running (triggered manually via API).
    from routers.scrapers import _running
    if platform in _running:
        _noop(f"Scheduler: {platform} already running, skipping")
        return

    from scrapers import ubereats, deliveroo, takeaway, direct, direct_menu
    from scrapers import dom_menu

    if platform == "direct_menu":
        run_id = db.create_run(platform)
        try:
            result = direct_menu.run()
            db.finish_run(run_id, "success", records_saved=result.get("total_scraped", 0))
        except Exception as e:
            db.finish_run(run_id, "failed", error_msg=str(e))
            import alerting; alerting.send_failure_alert(platform, str(e), run_id)
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
    try:
        import inspect
        kwargs = {"run_id": run_id} if "run_id" in inspect.signature(SCRAPERS[platform]).parameters else {}
        result = await SCRAPERS[platform](ScraperConfig(), _noop, **kwargs)
        db.finish_run(run_id, "success", records_saved=result.records_saved)
    except CloudflareBlockedError as e:
        db.finish_run(run_id, "blocked", error_msg=str(e))
        import alerting; alerting.send_failure_alert(platform, str(e), run_id)
    except Exception as e:
        db.finish_run(run_id, "failed", error_msg=str(e))
        import alerting; alerting.send_failure_alert(platform, str(e), run_id)


def _persist_schedule(config: ScheduleConfigIn) -> None:
    db.get_client().table("scraper_schedules").upsert({
        "platform": config.platform,
        "cron": config.cron,
        "address": "Pl. Poelaert 1, 1000 Bruxelles",
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
        job = _scheduler.add_job(
            _run_scraper,
            CronTrigger.from_crontab(config.cron),
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


async def _run_fee_refresh() -> None:
    from scrapers import fees
    from routers.scrapers import _fees_running
    if _fees_running:
        _noop("Scheduler: fee refresh already running, skipping")
        return
    run_id = db.create_run("fees")
    try:
        counts = await fees.run(_noop)
        total = sum(counts.values())
        db.finish_run(run_id, "success", records_saved=total)
    except Exception as e:
        db.finish_run(run_id, "failed", error_msg=str(e))
        import alerting; alerting.send_failure_alert("fees", str(e), run_id)


async def _run_daily_cleanup() -> None:
    pruned = db.prune_stale_menu_items(days=30)
    if pruned:
        _noop(f"Daily cleanup: pruned {pruned} stale menu items")


async def _run_daily_digest() -> None:
    import alerting
    alerting.send_daily_digest()


def start() -> None:
    _scheduler.add_job(
        _run_fee_refresh,
        CronTrigger.from_crontab(_FEE_CRON),
        id=_FEE_JOB_ID,
        replace_existing=True,
    )
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
        _scheduler.add_job(
            _run_scraper,
            CronTrigger.from_crontab(config.cron),
            id=f"scraper_{config.platform}",
            args=[config.platform],
            replace_existing=True,
        )
    _scheduler.start()


def shutdown() -> None:
    _scheduler.shutdown(wait=False)


def get_fee_next_run():
    job = _scheduler.get_job(_FEE_JOB_ID)
    return job.next_run_time if job else None
