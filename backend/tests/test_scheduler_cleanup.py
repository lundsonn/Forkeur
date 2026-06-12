"""Tests for scheduler._run_daily_cleanup and scheduler timezone."""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-scheduler-cleanup")

import scheduler


async def _tt(fn, *a, **k):
    """to_thread stand-in that calls the (mocked) sync fn directly."""
    return fn(*a, **k)


@pytest.mark.asyncio
async def test_run_daily_cleanup_logs_run():
    mock_db = MagicMock()
    mock_db.create_run.return_value = "cid"
    mock_db.delete_stale_listings.return_value = 2
    mock_db.prune_stale_menu_items.return_value = 5

    with patch.object(scheduler, "db", mock_db), \
         patch.object(scheduler.asyncio, "to_thread", _tt):
        await scheduler._run_daily_cleanup()

    mock_db.create_run.assert_called_once_with("cleanup")
    mock_db.delete_stale_listings.assert_called_once_with(days=30)
    mock_db.prune_stale_menu_items.assert_called_once_with(days=30)
    mock_db.finish_run.assert_called_once_with("cid", "success", records_saved=7)


@pytest.mark.asyncio
async def test_run_daily_cleanup_failure_alerts():
    mock_db = MagicMock()
    mock_db.create_run.return_value = "cid"
    mock_db.delete_stale_listings.side_effect = RuntimeError("boom")
    mock_alerting = MagicMock()

    with patch.object(scheduler, "db", mock_db), \
         patch.object(scheduler, "alerting", mock_alerting), \
         patch.object(scheduler.asyncio, "to_thread", _tt):
        await scheduler._run_daily_cleanup()

    mock_db.finish_run.assert_called_once_with("cid", "failed", error_msg="boom")
    mock_alerting.send_failure_alert.assert_called_once_with("cleanup", "boom", "cid")


def test_scheduler_timezone_is_brussels():
    assert str(scheduler._scheduler.timezone) == "Europe/Brussels"
