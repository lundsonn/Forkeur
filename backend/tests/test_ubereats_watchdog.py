"""Watchdog tests for scrapers.ubereats.run().

A wedged Playwright page once hung run() for 2h+ on a bare, unbounded
`await page.evaluate(...)`. run() now wraps its whole browser-session body in
`async with asyncio.timeout(_RUN_TIMEOUT_S)` and, on trip, logs + returns the
partial ScraperResult instead of propagating a raw TimeoutError. These tests
prove the watchdog returns instead of hanging — without any network.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-ubereats-watchdog")

from models import ScraperConfig, ScraperResult
from scrapers import ubereats


def test_run_timeout_is_env_tunable(monkeypatch):
    """_RUN_TIMEOUT_S reads UBEREATS_RUN_TIMEOUT_S with a 14400s default."""
    import importlib

    monkeypatch.delenv("UBEREATS_RUN_TIMEOUT_S", raising=False)
    importlib.reload(ubereats)
    assert ubereats._RUN_TIMEOUT_S == 14400

    monkeypatch.setenv("UBEREATS_RUN_TIMEOUT_S", "7")
    importlib.reload(ubereats)
    assert ubereats._RUN_TIMEOUT_S == 7

    # restore module to the default-env state for other tests
    monkeypatch.delenv("UBEREATS_RUN_TIMEOUT_S", raising=False)
    importlib.reload(ubereats)


@pytest.mark.asyncio
async def test_watchdog_returns_partial_instead_of_hanging(monkeypatch):
    """If the body would await forever, the watchdog trips and run() returns
    a ScraperResult (partial) rather than hanging."""
    exited = {"aexit": False}

    @asynccontextmanager
    async def fake_browser_session(*args, **kwargs):
        try:
            yield object()  # dummy browser; body never really uses it
        finally:
            exited["aexit"] = True  # prove browser_session.__aexit__ still runs

    class _HangingPage:
        def on(self, *a, **k):
            pass

        async def goto(self, *a, **k):
            # First real await inside the body — hang forever so the watchdog
            # is the only thing that can end the run.
            await asyncio.Event().wait()

    async def fake_new_page(*args, **kwargs):
        return _HangingPage()

    # Tiny watchdog so the test is fast and deterministic.
    monkeypatch.setattr(ubereats, "_RUN_TIMEOUT_S", 0.2)
    monkeypatch.setattr(ubereats, "browser_session", fake_browser_session)
    monkeypatch.setattr(ubereats, "new_page", fake_new_page)

    cfg = ScraperConfig(address="Test Address, Brussels")

    # Outer wall-clock cap on the test itself: if the watchdog were broken this
    # would raise TimeoutError and fail the test instead of hanging the suite.
    result = await asyncio.wait_for(ubereats.run(cfg), timeout=10)

    assert isinstance(result, ScraperResult)
    assert result.records_saved == 0  # nothing saved before the wedge
    assert exited["aexit"] is True  # browser cleanup still happened
