"""Readiness probes: `wait_until` (predicate polling), `wait_for_port` (TCP
accept), and `wait_for_line` (match a streamed line). Includes the probe-socket
cleanup wiring that a cancelled/refused `wait_for_port` must run.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import sys
from collections.abc import AsyncIterator

import pytest

from processkit import (
    Command,
    ProcessError,
    ProcessGroup,
    WaitTimeout,
    wait_for_line,
    wait_for_port,
    wait_until,
)

from ._programs import free_port, refused_port

PY = sys.executable


# --- wait_until (predicate polling) -------------------------------------------


def test_wait_until_sync_predicate() -> None:
    async def scenario() -> None:
        calls = 0

        def ready() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        await wait_until(ready, timeout=2.0, interval=0.01)
        assert calls >= 3

    asyncio.run(scenario())


def test_wait_until_async_predicate() -> None:
    async def scenario() -> None:
        async def ready() -> bool:
            return True

        await wait_until(ready, timeout=1.0)

    asyncio.run(scenario())


def test_wait_until_times_out() -> None:
    async def scenario() -> None:
        with pytest.raises(TimeoutError):
            await wait_until(lambda: False, timeout=0.2, interval=0.01)

    asyncio.run(scenario())


def test_wait_until_timeout_is_a_wait_timeout_with_the_deadline() -> None:
    # `WaitTimeout` is catchable as both `TimeoutError` (the readiness-timeout
    # convention) and `ProcessError` (the library's base), and carries the
    # `timeout_seconds` that was actually configured.
    async def scenario() -> None:
        with pytest.raises(WaitTimeout) as excinfo:
            await wait_until(lambda: False, timeout=0.2, interval=0.01)
        assert isinstance(excinfo.value, TimeoutError)
        assert isinstance(excinfo.value, ProcessError)
        assert excinfo.value.timeout_seconds == 0.2
        assert excinfo.value.host is None
        assert excinfo.value.port is None

    asyncio.run(scenario())


def test_wait_until_returns_immediately_when_already_true() -> None:
    # An already-true predicate must return before the deadline check, even at
    # timeout=0 (predicate is evaluated first).
    async def scenario() -> None:
        await wait_until(lambda: True, timeout=0.0)

    asyncio.run(scenario())


def test_readiness_timeout_is_keyword_only() -> None:
    # `timeout` is keyword-only across ALL three readiness helpers — pin each
    # signature so dropping the `*` on any of them fails.
    for fn in (wait_until, wait_for_port, wait_for_line):
        kind = inspect.signature(fn).parameters["timeout"].kind
        assert kind is inspect.Parameter.KEYWORD_ONLY, f"{fn.__name__}.timeout is {kind}"


def test_wait_until_async_predicate_polls_until_true() -> None:
    # A missing `await` would treat the coroutine as truthy and return after one
    # call; requiring three proves the value is actually awaited.
    async def scenario() -> None:
        calls = 0

        async def ready() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        await wait_until(ready, timeout=2.0, interval=0.01)
        assert calls >= 3

    asyncio.run(scenario())


def test_wait_until_async_predicate_times_out() -> None:
    async def scenario() -> None:
        async def never() -> bool:
            return False

        with pytest.raises(TimeoutError):
            await wait_until(never, timeout=0.2, interval=0.01)

    asyncio.run(scenario())


def test_wait_until_rejects_nonpositive_interval() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError):
            await wait_until(lambda: True, timeout=1.0, interval=0)
        with pytest.raises(ValueError):
            await wait_until(lambda: True, timeout=1.0, interval=float("nan"))

    asyncio.run(scenario())


def test_wait_until_bounds_a_hanging_async_predicate() -> None:
    # A hung async predicate must not outlive `timeout`: the deadline bounds the
    # predicate itself, not just the gaps between polls. A regression (bare await)
    # would hang until the outer guard fires, so assert it returns *promptly*.
    async def scenario() -> None:
        async def never_answers() -> bool:
            await asyncio.Event().wait()  # blocks forever
            return True

        loop = asyncio.get_running_loop()
        start = loop.time()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                wait_until(never_answers, timeout=0.2, interval=0.01), timeout=5.0
            )
        elapsed = loop.time() - start
        assert elapsed < 2.0, f"wait_until did not bound the hanging predicate ({elapsed:.1f}s)"

    asyncio.run(scenario())


def test_wait_until_propagates_predicate_own_exception() -> None:
    # A predicate that raises its own error (e.g. an I/O `TimeoutError`) must surface
    # untouched — not be swallowed and relabelled as the generic "condition not met".
    async def scenario() -> None:
        async def boom() -> bool:
            raise TimeoutError("db handshake timed out")

        with pytest.raises(TimeoutError, match="db handshake"):
            await wait_until(boom, timeout=10.0)

    asyncio.run(scenario())


def test_wait_until_async_predicate_runs_once_at_zero_timeout() -> None:
    # Symmetry with the sync path: an already-true async predicate is evaluated (and
    # succeeds) even at timeout=0, not cancelled before it runs.
    async def scenario() -> None:
        calls = 0

        async def ready() -> bool:
            nonlocal calls
            calls += 1
            return True

        await wait_until(ready, timeout=0.0)
        assert calls == 1

    asyncio.run(scenario())


def test_wait_until_cancels_inner_predicate_on_outer_cancel() -> None:
    # Cancelling the task awaiting wait_until must not orphan the in-flight predicate:
    # asyncio.wait (unlike wait_until) does not cancel its member, so wait_until must.
    async def scenario() -> None:
        started = asyncio.Event()
        cancelled = False

        async def slow() -> bool:
            nonlocal cancelled
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled = True
                raise
            return True

        task = asyncio.ensure_future(wait_until(slow, timeout=10.0))
        await started.wait()  # the predicate is now running inside asyncio.wait
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.01)  # let the inner cancellation settle
        assert cancelled, "wait_until orphaned the inner predicate task on outer cancel"

    asyncio.run(scenario())


def test_wait_until_deadline_drain_preserves_outer_cancellation() -> None:
    # A regression: a caller cancellation landing WHILE wait_until is draining a
    # just-timed-out predicate used to be swallowed and replaced with a
    # misleading TimeoutError instead of propagating as CancelledError.
    async def scenario() -> None:
        cleanup_started = asyncio.Event()

        async def slow_predicate() -> bool:
            try:
                await asyncio.sleep(30)  # never completes on its own
            except asyncio.CancelledError:
                cleanup_started.set()
                await asyncio.sleep(0.1)  # cleanup takes a moment to unwind
                raise
            return True

        outer = asyncio.ensure_future(wait_until(slow_predicate, timeout=0.05, interval=0.01))
        await cleanup_started.wait()  # wait_until's deadline fired and cancelled the predicate
        outer.cancel()  # a fresh cancellation lands while the predicate is still unwinding
        with pytest.raises(asyncio.CancelledError):
            await outer

    asyncio.run(scenario())


def test_wait_until_second_cancellation_during_drain_does_not_leak_task_exception() -> None:
    # A regression for _quiesce's own drain: if a SECOND cancellation lands
    # while it is still draining an already-cancelling predicate, and that
    # predicate's cleanup then raises its own (non-CancelledError) exception,
    # the fresh cancellation must still win — not get replaced by the
    # predicate's unrelated error.
    async def scenario() -> None:
        first_cancel_seen = asyncio.Event()

        async def flaky_predicate() -> bool:
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                first_cancel_seen.set()
                try:
                    await asyncio.sleep(30)  # a second cancellation lands here
                except asyncio.CancelledError:
                    raise ValueError("cleanup failed") from None  # NOT re-raised
            return True

        outer = asyncio.ensure_future(wait_until(flaky_predicate, timeout=0.05, interval=0.01))
        await first_cancel_seen.wait()  # wait_until's deadline fired; predicate mid-cleanup
        outer.cancel()  # a fresh, second cancellation lands while still draining
        with pytest.raises(asyncio.CancelledError):
            await outer

    asyncio.run(scenario())


def test_wait_until_rejects_nan_timeout() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="NaN"):
            await wait_until(lambda: True, timeout=float("nan"))

    asyncio.run(scenario())


def test_wait_until_rejects_negative_timeout() -> None:
    # Unified `timeout<=0` contract: a negative timeout is rejected outright
    # (like NaN), the same across all three readiness helpers.
    async def scenario() -> None:
        with pytest.raises(ValueError, match="negative"):
            await wait_until(lambda: True, timeout=-1.0)

    asyncio.run(scenario())


def test_wait_until_outer_cancel_wins_over_completed_predicate_exception() -> None:
    # Race: if the predicate task finishes with its OWN exception at the same instant
    # the caller cancels wait_until, the cancellation must win (CancelledError) — not the
    # predicate's exception, or `except CancelledError: cleanup()` silently misses.
    async def scenario() -> None:
        started = asyncio.Event()

        async def flaky() -> bool:
            started.set()
            raise ValueError("predicate's own error")  # completes without awaiting

        outer = asyncio.ensure_future(wait_until(flaky, timeout=10.0))
        await started.wait()  # flaky's task is now done with ValueError; outer still in wait
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await outer

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


def test_wait_for_port_rejects_nan_timeout() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="NaN"):
            await wait_for_port("127.0.0.1", 1, timeout=float("nan"))
        with pytest.raises(ValueError):
            await wait_for_port("127.0.0.1", 1, timeout=1.0, interval=float("nan"))

    asyncio.run(scenario())


def test_wait_for_port_rejects_negative_timeout() -> None:
    # Unified `timeout<=0` contract: a negative timeout is rejected outright
    # (like NaN), the same across all three readiness helpers.
    async def scenario() -> None:
        with pytest.raises(ValueError, match="negative"):
            await wait_for_port("127.0.0.1", 1, timeout=-1.0)

    asyncio.run(scenario())


def test_wait_for_port_ready_at_zero_timeout() -> None:
    # Symmetry with wait_until/wait_for_line: an already-ready port must still
    # succeed at timeout=0 (at least one connection attempt always happens),
    # not fail before a connection was ever attempted.
    async def scenario() -> None:
        port = free_port()
        server = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", port)
        async with server:
            await wait_for_port("127.0.0.1", port, timeout=0.0)

    asyncio.run(scenario())


def test_wait_for_port_chains_last_connection_error() -> None:
    # A typo'd/unresolvable hostname must not have its evidence (the DNS
    # failure) silently discarded — it survives as the TimeoutError's cause.
    async def scenario() -> None:
        with pytest.raises(TimeoutError) as excinfo:
            await wait_for_port("this-host-does-not-resolve.invalid", 1, timeout=0.5, interval=0.05)
        assert isinstance(excinfo.value.__cause__, OSError)

    asyncio.run(scenario())


def test_wait_for_port_timeout() -> None:
    async def scenario(port: int) -> None:
        with pytest.raises(TimeoutError):
            await wait_for_port("127.0.0.1", port, timeout=0.5)

    with refused_port() as port:  # nothing is listening
        asyncio.run(scenario(port))


def test_wait_for_port_timeout_carries_host_and_port() -> None:
    # Unlike wait_until()/wait_for_line()'s WaitTimeout (host/port always
    # None), wait_for_port's sets them — the one variant where they apply.
    async def scenario(port: int) -> None:
        with pytest.raises(WaitTimeout) as excinfo:
            await wait_for_port("127.0.0.1", port, timeout=0.5)
        assert excinfo.value.timeout_seconds == 0.5
        assert excinfo.value.host == "127.0.0.1"
        assert excinfo.value.port == port

    with refused_port() as port:  # nothing is listening
        asyncio.run(scenario(port))


def test_wait_for_line_rejects_nan_timeout() -> None:
    async def empty_lines() -> AsyncIterator[str]:
        return
        yield  # pragma: no cover -- never reached; makes this an async generator

    async def scenario() -> None:
        with pytest.raises(ValueError, match="NaN"):
            await wait_for_line(empty_lines(), lambda _line: True, timeout=float("nan"))

    asyncio.run(scenario())


def test_wait_for_line_rejects_negative_timeout() -> None:
    # Unified `timeout<=0` contract: a negative timeout is rejected outright
    # (like NaN), the same across all three readiness helpers.
    async def empty_lines() -> AsyncIterator[str]:
        return
        yield  # pragma: no cover -- never reached; makes this an async generator

    async def scenario() -> None:
        with pytest.raises(ValueError, match="negative"):
            await wait_for_line(empty_lines(), lambda _line: True, timeout=-1.0)

    asyncio.run(scenario())


def test_wait_for_line_propagates_predicate_own_timeout_error() -> None:
    # A builtin-TimeoutError-family exception the predicate raises for its own
    # reasons must surface untouched, not be masked behind the generic
    # "no matching line" message.
    async def lines() -> AsyncIterator[str]:
        yield "line one"

    def boom(_line: str) -> bool:
        raise TimeoutError("db handshake timed out")

    async def scenario() -> None:
        with pytest.raises(TimeoutError, match="db handshake"):
            await wait_for_line(lines(), boom, timeout=10.0)

    asyncio.run(scenario())


def test_wait_for_line_times_out_when_no_line_matches() -> None:
    # The genuine timeout branch: lines keep arriving (the stream doesn't end)
    # but none ever match, and the deadline passes first — a real TimeoutError,
    # distinct from both the predicate's-own-exception and stream-ended paths.
    async def endless_non_matching_lines() -> AsyncIterator[str]:
        while True:
            yield "nope"
            await asyncio.sleep(0.01)

    async def scenario() -> None:
        with pytest.raises(TimeoutError, match="no matching line"):
            await wait_for_line(
                endless_non_matching_lines(), lambda line: "READY" in line, timeout=0.2
            )

    asyncio.run(scenario())


def test_wait_for_line_timeout_carries_no_host_or_port() -> None:
    async def endless_non_matching_lines() -> AsyncIterator[str]:
        while True:
            yield "nope"
            await asyncio.sleep(0.01)

    async def scenario() -> None:
        with pytest.raises(WaitTimeout) as excinfo:
            await wait_for_line(
                endless_non_matching_lines(), lambda line: "READY" in line, timeout=0.2
            )
        assert excinfo.value.timeout_seconds == 0.2
        assert excinfo.value.host is None
        assert excinfo.value.port is None

    asyncio.run(scenario())


def test_wait_for_line_accepts_a_string_predicate_as_substring_match() -> None:
    # The `predicate: str` overload — a shorthand for `lambda line: needle in
    # line` — only valid for a `str`-yielding iterator.
    async def lines() -> AsyncIterator[str]:
        yield "starting"
        yield "READY now"

    async def scenario() -> str:
        return await wait_for_line(lines(), "READY", timeout=10.0)

    assert asyncio.run(scenario()) == "READY now"


def test_wait_for_line_string_predicate_times_out_like_a_callable_one() -> None:
    async def endless_non_matching_lines() -> AsyncIterator[str]:
        while True:
            yield "nope"
            await asyncio.sleep(0.01)

    async def scenario() -> None:
        with pytest.raises(WaitTimeout, match="no matching line"):
            await wait_for_line(endless_non_matching_lines(), "READY", timeout=0.2)

    asyncio.run(scenario())


def test_wait_for_line_generalizes_over_a_non_string_item_type() -> None:
    # "generic over the iterator item type" (Stage 3 / C4): a callable
    # predicate works over ANY async iterator, not just `str` lines —
    # e.g. an `OutputEvent`-shaped item.
    class _Event:
        def __init__(self, text: str) -> None:
            self.text = text

    async def events() -> AsyncIterator[_Event]:
        yield _Event("starting")
        yield _Event("READY now")

    async def scenario() -> _Event:
        return await wait_for_line(events(), lambda ev: "READY" in ev.text, timeout=10.0)

    matched = asyncio.run(scenario())
    assert matched.text == "READY now"


def test_wait_for_line_stream_ended_raises_process_error() -> None:
    # The stream-ended branch: the iterator exhausts (EOF) before any line
    # matches and before the deadline — this is a ProcessError, not a
    # TimeoutError (there was no timeout; the source simply ran out).
    async def few_non_matching_lines() -> AsyncIterator[str]:
        yield "one"
        yield "two"

    async def scenario() -> None:
        with pytest.raises(ProcessError, match="stream ended"):
            await wait_for_line(
                few_non_matching_lines(), lambda line: "READY" in line, timeout=10.0
            )

    asyncio.run(scenario())


def test_wait_for_line_recovers_match_at_zero_timeout() -> None:
    # Symmetry with wait_until's "evaluate at least once": a line already
    # available in the iterator must still be found even at timeout=0 (the
    # done-at-deadline recovery path), not discarded as a timeout.
    async def one_line() -> AsyncIterator[str]:
        yield "READY now"

    async def scenario() -> str:
        return await wait_for_line(one_line(), lambda line: "READY" in line, timeout=0.0)

    assert asyncio.run(scenario()) == "READY now"


def test_wait_for_line_matches() -> None:
    code = (
        "import time; print('starting', flush=True); "
        "time.sleep(0.05); print('READY now', flush=True); time.sleep(5)"
    )

    async def scenario() -> str:
        # `async with`, not a bare `proc.kill()`/`proc.wait()` pair: if the
        # assertion inside raises, the 5s-sleeping child must still be reaped.
        async with await Command(PY, ["-c", code]).astart() as proc:
            lines = proc.stdout_lines()
            return await wait_for_line(lines, lambda line: "READY" in line, timeout=10.0)

    assert "READY" in asyncio.run(scenario())


# --- probe-socket cleanup ---------------------------------------------------


def test_wait_for_port_cancel_propagates() -> None:
    async def scenario(port: int) -> None:
        task = asyncio.ensure_future(wait_for_port("127.0.0.1", port, timeout=10.0))
        await asyncio.sleep(0.05)  # let it enter the retry loop
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with refused_port() as port:  # nothing is listening -> the helper stays in its retry loop
        asyncio.run(scenario(port))


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

    async def scenario(port: int) -> None:
        task = asyncio.ensure_future(wait_for_port("127.0.0.1", port, timeout=10.0))
        await asyncio.sleep(0.1)  # let a couple of refused-connect retries happen
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    with refused_port() as port:  # nothing listening -> the OSError path runs the cleanup
        asyncio.run(scenario(port))
    assert called, "wait_for_port should route cleanup through _close_pending_connection"
