"""Watchdog tests for scrapers.takeaway.run().

Takeaway uses headed Chromium (CF bypass); a hung page could block run() forever.
run() now wraps its whole browser-session body in
`async with asyncio.timeout(_RUN_TIMEOUT_S)` and, on trip, logs + returns the
partial ScraperResult instead of propagating a raw TimeoutError.
"""
import asyncio
import os
from contextlib import asynccontextmanager

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-takeaway-watchdog")

from models import ScraperConfig, ScraperResult
from scrapers import takeaway


def test_run_timeout_is_env_tunable(monkeypatch):
    """_RUN_TIMEOUT_S reads TAKEAWAY_RUN_TIMEOUT_S with a 7200s default."""
    import importlib

    monkeypatch.delenv("TAKEAWAY_RUN_TIMEOUT_S", raising=False)
    importlib.reload(takeaway)
    assert takeaway._RUN_TIMEOUT_S == 7200

    monkeypatch.setenv("TAKEAWAY_RUN_TIMEOUT_S", "9")
    importlib.reload(takeaway)
    assert takeaway._RUN_TIMEOUT_S == 9

    monkeypatch.delenv("TAKEAWAY_RUN_TIMEOUT_S", raising=False)
    importlib.reload(takeaway)


@pytest.mark.asyncio
async def test_watchdog_returns_partial_instead_of_hanging(monkeypatch):
    """If the body would await forever, the watchdog trips and run() returns
    a ScraperResult (partial) rather than hanging."""
    exited = {"aexit": False}

    @asynccontextmanager
    async def fake_browser_session(*args, **kwargs):
        try:
            yield object()
        finally:
            exited["aexit"] = True

    class _HangingPage:
        def on(self, *a, **k):
            pass

        async def goto(self, *a, **k):
            await asyncio.Event().wait()

        async def close(self, *a, **k):
            pass

    async def fake_new_page(*args, **kwargs):
        return _HangingPage()

    monkeypatch.setattr(takeaway, "_RUN_TIMEOUT_S", 0.2)
    monkeypatch.setattr(takeaway, "browser_session", fake_browser_session)
    monkeypatch.setattr(takeaway, "new_page", fake_new_page)

    cfg = ScraperConfig(address="Test Address, Brussels")

    result = await asyncio.wait_for(takeaway.run(cfg), timeout=10)

    assert isinstance(result, ScraperResult)
    assert result.records_saved == 0
    assert exited["aexit"] is True
