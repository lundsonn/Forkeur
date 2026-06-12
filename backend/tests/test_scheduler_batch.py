"""Orchestration tests for scheduler._run_batch_all (memory-gated batch)."""
import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-scheduler-batch")

import scheduler


def _make_run_scraper(events: list[str], durations: dict[str, float]):
    """Fake _run_scraper that records start/end order with controllable durations."""
    async def fake_run_scraper(platform: str) -> None:
        events.append(f"start:{platform}")
        await asyncio.sleep(durations.get(platform, 0))
        events.append(f"end:{platform}")
    return fake_run_scraper


@pytest.mark.asyncio
async def test_direct_menu_starts_with_heavy_scrapers():
    """direct_menu (httpx, no browser) must not wait for the platform scrapers."""
    events: list[str] = []
    durations = {"ubereats": 0.05, "deliveroo": 0.05, "takeaway": 0.05, "direct": 0.05}

    with patch.object(scheduler, "_run_scraper", _make_run_scraper(events, durations)), \
         patch.object(scheduler, "_run_match", AsyncMock()), \
         patch.object(scheduler, "_mem_available_gb", return_value=10.0):
        await scheduler._run_batch_all()

    dm_start = events.index("start:direct_menu")
    first_heavy_end = min(events.index(f"end:{p}") for p in durations)
    assert dm_start < first_heavy_end, events


@pytest.mark.asyncio
async def test_dom_menu_waits_for_first_heavy_completion():
    """dom_menu launches after the FIRST heavy scraper ends, not after all of them."""
    events: list[str] = []
    durations = {"ubereats": 0.01, "deliveroo": 0.2, "takeaway": 0.2, "direct": 0.2}

    with patch.object(scheduler, "_run_scraper", _make_run_scraper(events, durations)), \
         patch.object(scheduler, "_run_match", AsyncMock()), \
         patch.object(scheduler, "_mem_available_gb", return_value=10.0):
        await scheduler._run_batch_all()

    dm_start = events.index("start:dom_menu")
    assert dm_start > events.index("end:ubereats"), events
    assert dm_start < events.index("end:deliveroo"), events


@pytest.mark.asyncio
async def test_dom_menu_holds_while_memory_gate_closed():
    """dom_menu must not launch while MemAvailable < gate threshold."""
    events: list[str] = []
    durations = {"ubereats": 0.01, "deliveroo": 0.01, "takeaway": 0.01, "direct": 0.01}
    mem_values = iter([0.5, 0.5, 10.0])  # closed twice, then opens

    with patch.object(scheduler, "_run_scraper", _make_run_scraper(events, durations)), \
         patch.object(scheduler, "_run_match", AsyncMock()), \
         patch.object(scheduler, "_mem_available_gb", side_effect=lambda: next(mem_values, 10.0)), \
         patch.object(scheduler, "_MEM_GATE_POLL_S", 0.01):
        await scheduler._run_batch_all()

    # All heavies finished before dom_menu started (gate held it past their ends)
    dm_start = events.index("start:dom_menu")
    for p in durations:
        assert dm_start > events.index(f"end:{p}"), events


@pytest.mark.asyncio
async def test_match_runs_after_everything():
    events: list[str] = []

    async def fake_match():
        events.append("match")

    with patch.object(scheduler, "_run_scraper", _make_run_scraper(events, {})), \
         patch.object(scheduler, "_run_match", fake_match), \
         patch.object(scheduler, "_mem_available_gb", return_value=10.0):
        await scheduler._run_batch_all()

    assert events[-1] == "match"
    assert "end:dom_menu" in events and "end:direct_menu" in events


@pytest.mark.asyncio
async def test_run_scraper_finalizes_db_row_on_cancel():
    """A cancelled run must mark its DB row failed, not orphan it as 'running'.

    Regression: stopping (or batch-cancelling) a hung scraper raises
    CancelledError, a BaseException that bypasses `except Exception`; without an
    explicit handler the run row never gets finish_run and stays 'running' forever.
    """
    from routers.scrapers import _running, _tasks
    _running.discard("dom_menu")
    _tasks.pop("dom_menu", None)

    async def hang(*args, **kwargs):
        raise asyncio.CancelledError()

    finished: dict = {}

    with patch.object(scheduler, "db") as mock_db, \
         patch("scrapers.dom_menu.run", hang):
        mock_db.create_run.return_value = "run-cancel"
        mock_db.finish_run.side_effect = lambda rid, status, **kw: finished.update(
            id=rid, status=status, kw=kw
        )
        with pytest.raises(asyncio.CancelledError):
            await scheduler._run_scraper("dom_menu")

    assert finished == {"id": "run-cancel", "status": "failed", "kw": {"error_msg": "cancelled (stop requested or hung)"}}
    assert "dom_menu" not in _running  # finally block still cleared it
