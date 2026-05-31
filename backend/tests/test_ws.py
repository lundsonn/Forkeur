import asyncio

import pytest

import ws


@pytest.mark.asyncio
async def test_make_log_fn_pushes_to_queue():
    log_fn = ws.make_log_fn("test-run-1")
    log_fn("hello world")
    queue = ws.get_or_create_queue("test-run-1")
    msg = queue.get_nowait()
    assert msg == {"type": "log", "line": "hello world"}


@pytest.mark.asyncio
async def test_send_done_puts_done_msg():
    await ws.send_done("test-run-2", records=42)
    queue = ws.get_or_create_queue("test-run-2")
    msg = queue.get_nowait()
    assert msg == {"type": "done", "records": 42}
