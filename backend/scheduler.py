from __future__ import annotations
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from models import ScraperConfig, ScheduleConfigIn, ScheduleConfigOut
from scrapers.base import CloudflareBlockedError
import db

_scheduler = AsyncIOScheduler()
_schedules: dict[str, ScheduleConfigIn] = {}

# Fee refresh: runs 45 min after each main scraper batch (06:45, 12:15, 18:15, 23:45 UTC)
_FEE_JOB_ID = "fee_refresh"
_FEE_CRON = "45 6,12,18,23 * * *"


def _noop(line: str) -> None:
    pass


async def _run_scraper(platform: str) -> None:
    from scrapers import ubereats, deliveroo, takeaway, direct
    SCRAPERS = {"ubereats": ubereats.run, "deliveroo": deliveroo.run, "takeaway": takeaway.run, "direct": direct.run}

    run_id = db.create_run(platform)
    try:
        result = await SCRAPERS[platform](ScraperConfig(), _noop)
        db.finish_run(run_id, "success", records_saved=result.records_saved)
    except CloudflareBlockedError as e:
        db.finish_run(run_id, "blocked", error_msg=str(e))
    except Exception as e:
        db.finish_run(run_id, "failed", error_msg=str(e))


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
    try:
        counts = await fees.run(_noop)
        _noop(f"Fee refresh done: {counts}")
    except Exception as e:
        _noop(f"Fee refresh failed: {e}")


def start() -> None:
    _scheduler.add_job(
        _run_fee_refresh,
        CronTrigger.from_crontab(_FEE_CRON),
        id=_FEE_JOB_ID,
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
