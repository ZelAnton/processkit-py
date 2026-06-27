"""Readiness probes: `wait_for` (predicate polling), `wait_for_port` (TCP
accept), and `wait_for_line` (match a streamed line). Includes the probe-socket
cleanup wiring that a cancelled/refused `wait_for_port` must run.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import sys

import pytest

from processkit import Command, ProcessGroup, wait_for, wait_for_line, wait_for_port

from ._programs import free_port

PY = sys.executable


# --- wait_for (predicate polling) -------------------------------------------


def test_wait_for_sync_predicate() -> None:
    async def scenario() -> None:
        calls = 0

        def ready() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        await wait_for(ready, timeout=2.0, interval=0.01)
        assert calls >= 3

    asyncio.run(scenario())


def test_wait_for_async_predicate() -> None:
    async def scenario() -> None:
        async def ready() -> bool:
            return True

        await wait_for(ready, timeout=1.0)

    asyncio.run(scenario())


def test_wait_for_times_out() -> None:
    async def scenario() -> None:
        with pytest.raises(TimeoutError):
            await wait_for(lambda: False, timeout=0.2, interval=0.01)

    asyncio.run(scenario())


def test_wait_for_returns_immediately_when_already_true() -> None:
    # An already-true predicate must return before the deadline check, even at
    # timeout=0 (predicate is evaluated first).
    async def scenario() -> None:
        await wait_for(lambda: True, timeout=0.0)

    asyncio.run(scenario())


def test_readiness_timeout_is_keyword_only() -> None:
    # `timeout` is keyword-only across ALL three readiness helpers — pin each
    # signature so dropping the `*` on any of them fails.
    for fn in (wait_for, wait_for_port, wait_for_line):
        kind = inspect.signature(fn).parameters["timeout"].kind
        assert kind is inspect.Parameter.KEYWORD_ONLY, f"{fn.__name__}.timeout is {kind}"


def test_wait_for_async_predicate_polls_until_true() -> None:
    # A missing `await` would treat the coroutine as truthy and return after one
    # call; requiring three proves the value is actually awaited.
    async def scenario() -> None:
        calls = 0

        async def ready() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        await wait_for(ready, timeout=2.0, interval=0.01)
        assert calls >= 3

    asyncio.run(scenario())


def test_wait_for_async_predicate_times_out() -> None:
    async def scenario() -> None:
        async def never() -> bool:
            return False

        with pytest.raises(TimeoutError):
            await wait_for(never, timeout=0.2, interval=0.01)

    asyncio.run(scenario())


def test_wait_for_rejects_nonpositive_interval() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError):
            await wait_for(lambda: True, timeout=1.0, interval=0)

    asyncio.run(scenario())


# --- wait_for_port / wait_for_line ------------------------------------------


def test_wait_for_port_ready() -> None:
    port = free_port()
    server = (
        f"import socket, time; "
        f"s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
        f"s.bind(('127.0.0.1', {port})); s.listen(); time.sleep(10)"
    )

    async def scenario() -> None:
        async with ProcessGroup() as group:
            await group.astart(Command(PY, ["-c", server]))
            await wait_for_port("127.0.0.1", port, timeout=10.0)

    asyncio.run(scenario())


def test_wait_for_port_timeout() -> None:
    port = free_port()  # nothing is listening

    async def scenario() -> None:
        with pytest.raises(TimeoutError):
            await wait_for_port("127.0.0.1", port, timeout=0.5)

    asyncio.run(scenario())


def test_wait_for_line_matches() -> None:
    code = (
        "import time; print('starting', flush=True); "
        "time.sleep(0.05); print('READY now', flush=True); time.sleep(5)"
    )

    async def scenario() -> str:
        proc = await Command(PY, ["-c", code]).astart()
        lines = proc.stdout_lines()
        matched = await wait_for_line(lines, lambda line: "READY" in line, timeout=10.0)
        proc.kill()
        await proc.wait()
        return matched

    assert "READY" in asyncio.run(scenario())


# --- probe-socket cleanup ---------------------------------------------------


def test_wait_for_port_cancel_propagates() -> None:
    port = free_port()  # nothing is listening -> the helper stays in its retry loop

    async def scenario() -> None:
        task = asyncio.ensure_future(wait_for_port("127.0.0.1", port, timeout=10.0))
        await asyncio.sleep(0.05)  # let it enter the retry loop
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_wait_for_port_closes_raced_connection() -> None:
    # The real leak fix: a connect that completes but is never "taken" (a timeout
    # or cancellation racing a successful connect, so `asyncio.wait_for` drops it)
    # must still have its transport closed. Pins `_close_pending_connection`; if it
    # were a no-op the writer would stay open and the assertion would fail.
    from processkit._aio import _close_pending_connection

    async def scenario() -> None:
        port = free_port()
        server = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", port)
        async with server:
            conn = asyncio.ensure_future(asyncio.open_connection("127.0.0.1", port))
            _reader, writer = await conn  # the connect raced to completion
            assert not writer.is_closing()
            _close_pending_connection(conn)  # the cleanup the leak fix runs
            assert writer.is_closing(), "a raced probe transport must be closed"
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    asyncio.run(scenario())


def test_wait_for_port_routes_through_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pin the wiring (not just the helper): wait_for_port must route each connect
    # through _close_pending_connection so a raced/refused connect is cleaned up.
    # Dropping that call would slip past the isolated helper test above.
    import processkit._aio as aio

    called: list[object] = []
    real = aio._close_pending_connection

    def spy(task: asyncio.Task[tuple[asyncio.StreamReader, asyncio.StreamWriter]]) -> None:
        called.append(task)
        real(task)

    monkeypatch.setattr(aio, "_close_pending_connection", spy)
    port = free_port()  # nothing listening -> the OSError path runs the cleanup

    async def scenario() -> None:
        task = asyncio.ensure_future(wait_for_port("127.0.0.1", port, timeout=10.0))
        await asyncio.sleep(0.1)  # let a couple of refused-connect retries happen
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert called, "wait_for_port should route cleanup through _close_pending_connection"
