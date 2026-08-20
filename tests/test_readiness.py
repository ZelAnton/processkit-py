"""Readiness probes: `wait_until` (predicate polling), `wait_for_port` (TCP
accept), `wait_for_http` (an HTTP endpoint answers with an expected status),
`wait_for_line` (match a streamed line), `wait_for_path` (filesystem path
appears), `wait_for_named_pipe` (Windows named-pipe server), and
`wait_for_unix_socket` (Unix-domain socket accept). Includes the probe-socket
cleanup wiring that a cancelled/refused `wait_for_port` / `wait_for_http` /
`wait_for_unix_socket` must run.

Also covers the handle-level partial-tail probes — `RunningProcess`'s
`wait_for_output`/`await_for_output` and `wait_for_stderr_output`/
`await_for_stderr_output` — which match an *un-terminated* prompt the
line-oriented probes above can never see (the PTY dialog case lives in
`test_streaming.py`, next to the other PTY tests).
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import gc
import inspect
import socket
import sys
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest

from processkit import (
    Command,
    ProcessError,
    ProcessGroup,
    Unsupported,
    WaitTimeout,
    wait_for_http,
    wait_for_line,
    wait_for_named_pipe,
    wait_for_path,
    wait_for_port,
    wait_for_unix_socket,
    wait_until,
)
from processkit._aio import _format_host_header, _http_connection_host, _parse_status_code

from ._liveness import is_alive
from ._programs import free_port, refused_port

PY = sys.executable
_HAS_UNIX_SOCKETS = hasattr(socket, "AF_UNIX")


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
    # `timeout` is keyword-only across ALL seven readiness helpers — pin each
    # signature so dropping the `*` on any of them fails.
    for fn in (
        wait_until,
        wait_for_port,
        wait_for_http,
        wait_for_line,
        wait_for_named_pipe,
        wait_for_path,
        wait_for_unix_socket,
    ):
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
    # predicate's unrelated error. Also pins the companion regression: _quiesce
    # must still retrieve that unrelated exception from the now-finished inner
    # task (even though it discards it), or asyncio's default handler reports
    # "Task exception was never retrieved" once the task is garbage-collected —
    # caught here with a private `loop.set_exception_handler`, deterministically
    # (not by scraping captured stderr, whose GC timing isn't guaranteed).
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        unraisable: list[dict[str, object]] = []
        loop.set_exception_handler(lambda _loop, context: unraisable.append(context))

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
        del outer  # drop the last reference so the inner task's own __del__ can run
        gc.collect()  # a Task participates in a refcount cycle; force collection now
        assert not unraisable, f"leaked task exception(s): {unraisable}"

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


def test_wait_for_port_zero_timeout_does_not_hang_on_a_stalled_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A regression: at timeout=0, the first attempt used to be given an
    # unbounded `asyncio.wait_for(..., timeout=None)`, so a connect that never
    # resolves/connects (e.g. a DNS lookup against an unresolvable/blackhole
    # address) could block far past the caller's requested zero deadline —
    # potentially forever, or until the OS's own (much longer) connect/DNS
    # timeout. A never-resolving `open_connection` monkeypatch pins this
    # deterministically instead of relying on a real unreachable address and
    # the OS's own timeout (slow and environment-dependent).
    async def hanging_open_connection(
        _host: str, _port: int, **_kwargs: object
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        await asyncio.Event().wait()  # never resolves, never connects
        raise AssertionError("unreachable")  # pragma: no cover

    monkeypatch.setattr(asyncio, "open_connection", hanging_open_connection)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                wait_for_port("this-host-does-not-resolve.invalid", 1, timeout=0.0),
                timeout=5.0,
            )
        elapsed = loop.time() - start
        # Bounded by a short event-loop tick (~`interval`, default 0.05s), not
        # the outer 5s guard — a regression (unbounded first attempt) would
        # only ever return via that outer `asyncio.wait_for` firing at ~5s.
        assert elapsed < 2.0, (
            f"wait_for_port(timeout=0) did not bound the stalled connect ({elapsed:.1f}s)"
        )

    asyncio.run(scenario())


def test_wait_for_port_zero_timeout_with_large_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def hanging_open_connection(
        _host: str, _port: int, **_kwargs: object
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover

    monkeypatch.setattr(asyncio, "open_connection", hanging_open_connection)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                wait_for_port("example.invalid", 1, timeout=0.0, interval=300.0),
                timeout=2.0,
            )
        elapsed = loop.time() - start
        assert elapsed < 2.0, (
            f"zero-timeout connection attempt scaled with the retry interval ({elapsed:.1f}s)"
        )

    asyncio.run(scenario())


def test_wait_for_port_first_attempt_window_is_monotonic_in_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression (Пункт 1): the first connection attempt's window must never
    # SHRINK as `timeout` grows from 0. It used to: at timeout=0 the first
    # attempt was floored to a fixed tick (~0.05s), but a tiny positive timeout
    # (0.001) fell through to `connect_timeout = remaining ≈ 0.001` — a LARGER
    # requested timeout yielding a SMALLER first window than timeout=0, so an
    # already-ready local port could pass at timeout=0 yet fail at timeout=0.001.
    # Capture the actual `connect_timeout` handed to `asyncio.wait_for` on the
    # first attempt for a rising sequence of timeouts and assert it is
    # non-decreasing — deterministic, no wall-clock or real race.
    windows: list[float] = []

    async def recording_wait_for(
        fut: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]],
        timeout: float,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        windows.append(timeout)
        # Mimic real wait_for's timeout path: cancel and drain the pending
        # connect so no task is left dangling, then report the deadline.
        fut.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await fut
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", recording_wait_for)

    async def first_window_for(timeout: float) -> float:
        windows.clear()
        with contextlib.suppress(WaitTimeout):
            await wait_for_port("127.0.0.1", 1, timeout=timeout)
        return windows[0]

    async def scenario() -> None:
        prev = -1.0
        for timeout in (0.0, 0.001, 0.01, 0.1):
            window = await first_window_for(timeout)
            assert window >= prev, (
                f"first-attempt window shrank at timeout={timeout}: {window} < {prev}"
            )
            prev = window

    asyncio.run(scenario())


def test_wait_for_port_honors_success_that_raced_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression (Пункт 2): if the connect actually established in the same tick
    # the deadline cancelled it, wait_for_port must honor that met success —
    # exactly as its siblings `wait_until` / `wait_for_line` already do for their
    # equivalent race ("honor it rather than discarding a met condition") —
    # instead of closing the live transport and raising WaitTimeout. Before the
    # fix the two related helpers gave two different answers to the same race.
    # Deterministic: a patched `asyncio.wait_for` drives the connect to a genuine
    # success and *then* reports a timeout, mocking the race rather than
    # depending on real scheduling.
    async def racing_wait_for(
        fut: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]],
        timeout: float,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        await fut  # the connect completes successfully (its result is set)...
        raise asyncio.TimeoutError  # ...but the deadline "fires" in the same tick

    async def scenario() -> None:
        port = free_port()
        server = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", port)
        async with server:
            monkeypatch.setattr(asyncio, "wait_for", racing_wait_for)
            # Must return normally: the raced-but-established connection wins.
            # Before the fix this discarded the success and raised WaitTimeout.
            await wait_for_port("127.0.0.1", port, timeout=0.5)

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


# --- partial-tail probes (RunningProcess.wait_for_output & co.) ---------------
#
# The line probes above only ever see COMPLETE lines. An interactive prompt is
# written without a trailing newline and then blocked on, so it never becomes a
# line: these four handle methods watch the live *partial* tail instead.

#: Writes an un-terminated prompt, waits for an answer, then writes a second
#: un-terminated prompt — i.e. a two-turn dialog made entirely of tails that
#: `wait_for_line`/`stdout_lines()` can never observe while the child is alive.
_PROMPT_DIALOG = (
    "import sys; sys.stdout.write('Password: '); sys.stdout.flush(); "
    "ans = sys.stdin.readline(); "
    "sys.stdout.write('granted, welcome> '); sys.stdout.flush(); "
    "sys.stdin.readline()"
)

#: Prompts on stderr while stdout stays a data channel.
_STDERR_PROMPT = (
    "import sys, time; sys.stderr.write('Continue? (y/N) '); sys.stderr.flush(); time.sleep(30)"
)

#: A child that prints one complete line and exits — no partial tail ever.
_ONE_LINE_THEN_EXIT = "print('done', flush=True)"


def test_wait_for_output_matches_an_unterminated_prompt_tail() -> None:
    # The core promise: a prompt with no trailing newline is invisible to the
    # line-oriented probes, and is exactly what this one returns.
    with Command(PY, ["-c", _PROMPT_DIALOG]).keep_stdin_open().start() as proc:
        assert proc.wait_for_output("Password: ", timeout=20.0) == "Password: "


def test_await_for_output_accepts_a_callable_predicate() -> None:
    # The `str` argument above is the substring shorthand; a callable is the
    # general form, exactly as for `wait_for_line`.
    async def scenario() -> str:
        async with await Command(PY, ["-c", _PROMPT_DIALOG]).keep_stdin_open().astart() as proc:
            return await proc.await_for_output(lambda tail: tail.endswith(": "), timeout=20.0)

    assert asyncio.run(scenario()) == "Password: "


def test_wait_for_output_is_non_consuming_and_repeatable() -> None:
    # Unlike the one-shot line probes, this only peeks: the same still-standing
    # prompt matches again, and the handle keeps its live getters.
    with Command(PY, ["-c", _PROMPT_DIALOG]).keep_stdin_open().start() as proc:
        first = proc.wait_for_output("Password", timeout=20.0)
        # timeout=0 exercises the "evaluate at least once" contract on a handle
        # whose output pump the first probe already installed.
        second = proc.wait_for_output("Password", timeout=0.0)
        assert first == second == "Password: "
        assert proc.pid is not None


def test_wait_for_output_dialog_answers_the_prompt_over_take_stdin() -> None:
    # The whole point of the probe: match a prompt, answer it, match the NEXT
    # (also un-terminated) prompt — proving the handle survives a probe.
    async def scenario() -> tuple[str, str, str]:
        proc = await Command(PY, ["-c", _PROMPT_DIALOG]).keep_stdin_open().astart()
        prompt = await proc.await_for_output("Password: ", timeout=20.0)
        stdin = proc.take_stdin()
        await stdin.write_line("s3cret")
        second = await proc.await_for_output("welcome> ", timeout=20.0)
        await stdin.write_line("")
        result = await proc.aoutput()
        return prompt, second, result.stdout

    prompt, second, stdout = asyncio.run(scenario())
    assert prompt == "Password: "
    # The tail is the WHOLE current partial line, and this child never ends it
    # with a newline — so the second prompt arrives appended to the first rather
    # than replacing it. Match prompts with `in`/`endswith`, not equality.
    assert second == "Password: granted, welcome> "
    # `output()` still reports the run after a probe (the drained lines are
    # retained); only `output_bytes()` is ruled out, see the test below.
    assert "granted, welcome>" in stdout


def test_wait_for_output_deadline_neither_kills_nor_times_out_the_run() -> None:
    # Paired with the line probes' own non-killing contract: an expired probe
    # deadline is a `WaitTimeout` and nothing else — the child keeps running and
    # its outcome is whatever it would have been.
    with Command(PY, ["-c", _PROMPT_DIALOG]).keep_stdin_open().start() as proc:
        with pytest.raises(WaitTimeout) as excinfo:
            proc.wait_for_output("never-printed", timeout=0.3)
        assert isinstance(excinfo.value, TimeoutError)  # stdlib-catchable, like its siblings
        assert isinstance(excinfo.value, ProcessError)
        assert excinfo.value.timeout_seconds == 0.3
        pid = proc.pid
        assert pid is not None and is_alive(pid), "a failed probe must not kill the child"
        # Still fully usable afterwards — the prompt is right there.
        assert proc.wait_for_output("Password", timeout=20.0) == "Password: "


def test_wait_for_output_fails_fast_when_the_stream_ends_unmatched() -> None:
    # No waiting out a long deadline on output that can no longer arrive —
    # the same "stream ended" contract `wait_for_line` gives.
    with Command(PY, ["-c", _ONE_LINE_THEN_EXIT]).start() as proc:
        started = time.monotonic()
        with pytest.raises(ProcessError, match="ended before a matching tail") as excinfo:
            proc.wait_for_output("never-printed", timeout=30.0)
        assert not isinstance(excinfo.value, WaitTimeout), "a dead stream is not a deadline"
        assert time.monotonic() - started < 15.0, "must not wait out the 30s deadline"


def test_wait_for_output_propagates_a_predicate_exception_untouched() -> None:
    # Like `wait_for_line`, the caller's own failure is never masked behind the
    # deadline — even though the predicate runs on a runtime worker.
    def boom(tail: str) -> bool:
        raise RuntimeError("predicate exploded")

    with (
        Command(PY, ["-c", _PROMPT_DIALOG]).keep_stdin_open().start() as proc,
        pytest.raises(RuntimeError, match="predicate exploded"),
    ):
        proc.wait_for_output(boom, timeout=20.0)


def test_wait_for_output_rejects_a_bad_predicate_and_a_bad_timeout() -> None:
    with Command(PY, ["-c", _PROMPT_DIALOG]).keep_stdin_open().start() as proc:
        with pytest.raises(TypeError, match="predicate must be a str"):
            proc.wait_for_output(123, timeout=1.0)  # type: ignore[arg-type]
        for bad in (-1.0, float("nan")):
            with pytest.raises(ValueError, match="timeout"):
                proc.wait_for_output("x", timeout=bad)
        with pytest.raises(TypeError):
            proc.wait_for_output("x", 1.0)  # type: ignore[call-arg]  # timeout is keyword-only


def test_wait_for_output_on_a_consumed_handle_raises() -> None:
    proc = Command(PY, ["-c", _ONE_LINE_THEN_EXIT]).start()
    proc.outcome()
    with pytest.raises(ProcessError, match="consumed"):
        proc.wait_for_output("done", timeout=1.0)


def test_await_for_output_without_a_running_loop_raises() -> None:
    # The same guard every other `a`-verb has: reach for the sync twin instead.
    with (
        Command(PY, ["-c", _PROMPT_DIALOG]).keep_stdin_open().start() as proc,
        pytest.raises(ProcessError, match="no running asyncio event loop"),
    ):
        proc.await_for_output("Password", timeout=1.0)


def test_wait_for_stderr_output_matches_a_prompt_on_stderr() -> None:
    # K-043: stdout and stderr are NOT symmetrical here, so the stderr twin is
    # exercised independently rather than inferred from the stdout one.
    with Command(PY, ["-c", _STDERR_PROMPT]).start() as proc:
        assert proc.wait_for_stderr_output("(y/N)", timeout=20.0) == "Continue? (y/N) "


def test_await_for_stderr_output_matches_a_prompt_on_stderr() -> None:
    async def scenario() -> str:
        async with await Command(PY, ["-c", _STDERR_PROMPT]).astart() as proc:
            return await proc.await_for_stderr_output("(y/N)", timeout=20.0)

    assert asyncio.run(scenario()) == "Continue? (y/N) "


def test_wait_for_output_requires_an_observable_stdout() -> None:
    # The stdout half of the same asymmetry: a non-piped stdout has no live tail
    # either, but the crate diagnoses it differently from the stderr half below
    # (K-043 — check both streams, never infer one from the other).
    with (
        Command(PY, ["-c", _PROMPT_DIALOG]).keep_stdin_open().stdout("null").start() as proc,
        pytest.raises(ProcessError, match="not observable for readiness probing"),
    ):
        proc.wait_for_output("Password", timeout=20.0)


def test_wait_for_stderr_output_requires_a_piped_stderr() -> None:
    # The asymmetry itself: a non-piped stderr has no observable tail and says
    # so immediately, instead of waiting out the deadline.
    with (
        Command(PY, ["-c", _STDERR_PROMPT]).stderr("null").start() as proc,
        pytest.raises(ProcessError, match="stderr is not piped"),
    ):
        proc.wait_for_stderr_output("(y/N)", timeout=20.0)


def test_wait_for_output_tail_is_raw_even_under_sanitize_vt() -> None:
    # `sanitize_vt()` scrubs each *complete line* on its way into the capture
    # backlog; the partial tail is published straight off the pump's pending
    # buffer, so it still carries the escape sequences. Match prompts on their
    # plain text (or strip in a callable), never assume a scrubbed tail.
    code = (
        "import sys, time; sys.stdout.write('\\x1b[32mPassword: '); "
        "sys.stdout.flush(); time.sleep(30)"
    )
    with Command(PY, ["-c", code]).sanitize_vt().start() as proc:
        tail = proc.wait_for_output("Password: ", timeout=20.0)
        assert tail == "\x1b[32mPassword: "


def test_wait_for_output_composes_with_a_stream_bound_first() -> None:
    # Ordering contract, half one: a stream bound BEFORE the probe keeps
    # working — the tail is a side channel and steals nothing from the iterator.
    async def scenario() -> tuple[str, str, int | None]:
        code = (
            "import sys; print('line-1', flush=True); "
            "sys.stdout.write('Password: '); sys.stdout.flush(); sys.stdin.readline()"
        )
        async with await Command(PY, ["-c", code]).keep_stdin_open().astart() as proc:
            lines = proc.stdout_lines()
            tail = await proc.await_for_output("Password", timeout=20.0)
            line = await anext(lines)
            return tail, line, proc.stdout_line_count

    tail, line, captured_lines = asyncio.run(scenario())
    assert tail == "Password: "
    assert line.rstrip() == "line-1", "the probe must not consume the stream's line"
    # …and the prompt itself never became a line: exactly the one real line was
    # captured while the child sits on it. That gap between "written" and
    # "a line" is the whole reason this probe exists.
    assert captured_lines == 1


def test_stream_bound_after_a_probe_is_diagnosed() -> None:
    # Ordering contract, half two: probing installs stdout's one line pump (like
    # every other readiness probe), so a stream opened afterwards is refused with
    # the crate's own diagnosis rather than silently yielding nothing.
    with Command(PY, ["-c", _PROMPT_DIALOG]).keep_stdin_open().start() as proc:
        proc.wait_for_output("Password", timeout=20.0)
        with pytest.raises(ProcessError, match="already consumed"):
            proc.stdout_lines()
        with pytest.raises(ProcessError, match="already consumed"):
            proc.output_events()


def test_output_bytes_after_a_probe_is_diagnosed() -> None:
    # Raw bytes can't be recovered once stdout is being decoded into lines; the
    # text-capturing `output()` still works (see the dialog test above).
    proc = Command(PY, ["-c", _PROMPT_DIALOG]).keep_stdin_open().start()
    proc.wait_for_output("Password", timeout=20.0)
    with pytest.raises(ProcessError, match="output_bytes cannot follow"):
        proc.output_bytes()


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
    # must still have its transport closed. Pins the shared probe settler; if it
    # were a no-op the writer would stay open and the assertion would fail.
    from processkit._aio import _close_connection_now, _settle_probe

    async def scenario() -> None:
        port = free_port()
        server = await asyncio.start_server(lambda _r, w: w.close(), "127.0.0.1", port)
        async with server:
            conn = asyncio.ensure_future(asyncio.open_connection("127.0.0.1", port))
            _reader, writer = await conn  # the connect raced to completion
            assert not writer.is_closing()
            _settle_probe(conn, _close_connection_now)
            assert writer.is_closing(), "a raced probe transport must be closed"
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    asyncio.run(scenario())


def test_wait_for_port_routes_through_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pin the wiring (not just the helper): wait_for_port must route each connect
    # through the shared probe settler so a raced/refused connect is cleaned up.
    # Dropping that call would slip past the isolated helper test above.
    import processkit._aio as aio

    called: list[object] = []
    real = aio._settle_probe

    def spy(task: asyncio.Task[object], cleanup_result: Callable[[object], None]) -> None:
        called.append(task)
        real(task, cleanup_result)

    monkeypatch.setattr(aio, "_settle_probe", spy)

    async def scenario(port: int) -> None:
        task = asyncio.ensure_future(wait_for_port("127.0.0.1", port, timeout=10.0))
        await asyncio.sleep(0.1)  # let a couple of refused-connect retries happen
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    with refused_port() as port:  # nothing listening -> the OSError path runs the cleanup
        asyncio.run(scenario(port))
    assert called, "wait_for_port should route cleanup through the shared probe settler"


# Type checkers (mypy, pyright) see ``ctypes.WinDLL``/``WinError``/``get_last_error``
# as unavailable on non-Windows: typeshed declares them only under
# ``if sys.platform == "win32":``. The platform split below is on
# ``sys.platform`` (not ``os.name``) for the same reason documented in
# tests/_liveness.py: it lets the type checker analyse only the branch for the
# platform it is run on, so the Windows-only ``ctypes`` calls stay invisible to
# mypy on Linux. The ``else`` branch is never actually exercised (every caller
# is a test gated by ``@pytest.mark.skipif(sys.platform != "win32", ...)``); it
# only needs to satisfy the type checker with matching signatures.
if sys.platform == "win32":

    def _last_error() -> int:
        return ctypes.get_last_error()

    def _raise_win_error(code: int) -> NoReturn:
        raise ctypes.WinError(code)

    def _windows_pipe_api() -> tuple[Any, Any, Any]:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        create_named_pipe_w: Any = kernel32.CreateNamedPipeW
        create_named_pipe_w.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        )
        create_named_pipe_w.restype = ctypes.c_void_p

        create_file_w: Any = kernel32.CreateFileW
        create_file_w.argtypes = (
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        )
        create_file_w.restype = ctypes.c_void_p

        close_handle: Any = kernel32.CloseHandle
        close_handle.argtypes = (ctypes.c_void_p,)
        close_handle.restype = ctypes.c_int
        return create_named_pipe_w, create_file_w, close_handle

    @contextlib.contextmanager
    def _windows_named_pipe() -> Iterator[tuple[str, Any, Any]]:
        create_named_pipe_w, create_file_w, close_handle = _windows_pipe_api()
        name = rf"\\.\pipe\processkit-test-{uuid.uuid4().hex}"
        handle = create_named_pipe_w(name, 3, 0, 1, 4096, 4096, 0, None)
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle:
            _raise_win_error(_last_error())
        try:
            yield name, create_file_w, close_handle
        finally:
            close_handle(handle)

else:

    def _last_error() -> int:
        raise RuntimeError("Windows named pipes are unavailable on this platform")

    def _raise_win_error(code: int) -> NoReturn:
        raise RuntimeError("Windows named pipes are unavailable on this platform")

    def _windows_pipe_api() -> tuple[Any, Any, Any]:
        raise RuntimeError("Windows named pipes are unavailable on this platform")

    @contextlib.contextmanager
    def _windows_named_pipe() -> Iterator[tuple[str, Any, Any]]:
        raise RuntimeError("Windows named pipes are unavailable on this platform")
        yield  # type: ignore[unreachable]  # pragma: no cover -- makes this a generator


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipes are unavailable")
def test_wait_for_named_pipe_ready() -> None:
    with _windows_named_pipe() as (name, _create_file_w, _close_handle):
        asyncio.run(wait_for_named_pipe(name, timeout=5.0))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipes are unavailable")
def test_wait_for_named_pipe_busy_is_ready() -> None:
    with _windows_named_pipe() as (name, create_file_w, close_handle):
        client = create_file_w(name, 0, 0, None, 3, 0, None)
        invalid_handle = ctypes.c_void_p(-1).value
        if client == invalid_handle:
            _raise_win_error(_last_error())
        try:
            awaitable = wait_for_named_pipe(name, timeout=5.0)
            asyncio.run(awaitable)
        finally:
            close_handle(client)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipes are unavailable")
def test_wait_for_named_pipe_rejects_non_pipes() -> None:
    """Verify that wait_for_named_pipe rejects non-pipe paths.

    Paths that exist but are not named pipes (regular files, devices, etc.)
    should be rejected with WaitTimeout, not reported as ready.
    This is the rejection test for R-02.
    """
    import tempfile

    # Create a temporary file (not a pipe)
    with tempfile.NamedTemporaryFile() as tmp, pytest.raises(WaitTimeout):
        # Try to wait for this regular file as if it were a pipe
        asyncio.run(wait_for_named_pipe(tmp.name, timeout=0.5, interval=0.1))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipes are unavailable")
def test_wait_for_named_pipe_is_non_destructive() -> None:
    """Verify that wait_for_named_pipe does not consume the pipe's instance.

    After a successful probe, a real client should be able to connect
    immediately without receiving ERROR_PIPE_BUSY. This is the
    non-destructiveness regression test for R-03.
    """
    with _windows_named_pipe() as (name, create_file_w, close_handle):
        # Call wait_for_named_pipe on an open pipe
        asyncio.run(wait_for_named_pipe(name, timeout=5.0))

        # Now try to connect as a real client - this should succeed
        # without ERROR_PIPE_BUSY, proving the probe didn't consume instances
        client = create_file_w(name, 0, 0, None, 3, 0, None)
        invalid_handle = ctypes.c_void_p(-1).value
        if client == invalid_handle:
            error = _last_error()
            # If we get ERROR_PIPE_BUSY (231), the probe was destructive
            if error == 231:
                pytest.fail(
                    "wait_for_named_pipe was destructive: real client got ERROR_PIPE_BUSY (231)"
                )
            _raise_win_error(error)
        # Success: close the client handle
        close_handle(client)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipes are unavailable")
def test_wait_for_named_pipe_timeout_carries_path_and_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def passthrough_wait_for(future: asyncio.Future[bool], timeout: float) -> bool:
        return await future

    name = rf"\\.\pipe\processkit-missing-{uuid.uuid4().hex}"

    async def scenario() -> None:
        monkeypatch.setattr(asyncio, "wait_for", passthrough_wait_for)
        with pytest.raises(WaitTimeout) as excinfo:
            await wait_for_named_pipe(name, timeout=0.1, interval=0.01)
        assert excinfo.value.timeout_seconds == 0.1
        assert excinfo.value.path == name
        assert isinstance(excinfo.value.__cause__, OSError)

    asyncio.run(scenario())


def test_wait_for_named_pipe_without_windows_api_raises_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import processkit._aio as aio

    monkeypatch.setattr(aio, "_named_pipe_probe", None)

    async def scenario() -> None:
        with pytest.raises(Unsupported) as excinfo:
            await wait_for_named_pipe(r"\\.\pipe\missing", timeout=1.0)
        assert excinfo.value.operation == "wait_for_named_pipe"

    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipes are unavailable")
def test_wait_for_named_pipe_rejects_invalid_timeout_and_interval() -> None:
    name = rf"\\.\pipe\processkit-missing-{uuid.uuid4().hex}"

    async def scenario() -> None:
        with pytest.raises(ValueError, match="NaN"):
            await wait_for_named_pipe(name, timeout=float("nan"))
        with pytest.raises(ValueError, match="negative"):
            await wait_for_named_pipe(name, timeout=-1.0)
        for interval in (0.0, -1.0, float("nan")):
            with pytest.raises(ValueError, match="positive"):
                await wait_for_named_pipe(name, timeout=1.0, interval=interval)

    asyncio.run(scenario())


@pytest.fixture
def unix_socket_path() -> Iterator[Path]:
    """A bindable Unix-domain socket path guaranteed short enough for
    ``sockaddr_un.sun_path`` on every platform.

    macOS/BSD cap ``sun_path`` at 104 bytes (Linux allows 108). pytest's
    ``tmp_path`` nests each test under a long per-test base directory, which
    overflows that limit on GitHub's macOS runners (deep
    ``/Users/runner/work/...`` working dirs) even though the same path fits on
    Linux and Windows. Rooting a short-lived directory directly under the OS
    temp root with a minimal filename keeps the bound path well under the limit.
    """
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory) / "r.sock"


@pytest.mark.skipif(not _HAS_UNIX_SOCKETS, reason="AF_UNIX is unavailable on this platform")
def test_wait_for_unix_socket_ready(unix_socket_path: Path) -> None:
    socket_path = unix_socket_path

    async def scenario() -> None:
        server = await asyncio.start_unix_server(  # type: ignore[attr-defined,unused-ignore]
            lambda _r, w: w.close(), path=socket_path
        )
        try:
            async with server:
                await wait_for_unix_socket(socket_path, timeout=5.0)
        finally:
            socket_path.unlink(missing_ok=True)

    asyncio.run(scenario())


@pytest.mark.skipif(not _HAS_UNIX_SOCKETS, reason="AF_UNIX is unavailable on this platform")
def test_wait_for_unix_socket_ready_at_zero_timeout(unix_socket_path: Path) -> None:
    socket_path = unix_socket_path

    async def scenario() -> None:
        server = await asyncio.start_unix_server(  # type: ignore[attr-defined,unused-ignore]
            lambda _r, w: w.close(), path=socket_path
        )
        try:
            async with server:
                await wait_for_unix_socket(socket_path, timeout=0.0)
        finally:
            socket_path.unlink(missing_ok=True)

    asyncio.run(scenario())


@pytest.mark.skipif(not _HAS_UNIX_SOCKETS, reason="AF_UNIX is unavailable on this platform")
def test_wait_for_unix_socket_timeout_carries_path_and_last_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Do not let a tiny final `asyncio.wait_for` window race the refused
    # connection (K-037): the helper's own monotonic deadline still governs the
    # retry loop, while this patch preserves the real FileNotFoundError cause.
    async def passthrough_wait_for(
        future: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]], timeout: float
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await future

    missing = tmp_path / "missing.sock"

    async def scenario() -> None:
        monkeypatch.setattr(asyncio, "wait_for", passthrough_wait_for)
        with pytest.raises(WaitTimeout) as excinfo:
            await wait_for_unix_socket(missing, timeout=0.1, interval=0.01)
        assert excinfo.value.timeout_seconds == 0.1
        assert excinfo.value.path == missing
        assert isinstance(excinfo.value.__cause__, OSError)

    asyncio.run(scenario())


@pytest.mark.skipif(not _HAS_UNIX_SOCKETS, reason="AF_UNIX is unavailable on this platform")
def test_wait_for_unix_socket_rejects_invalid_timeout_and_interval(tmp_path: Path) -> None:
    socket_path = tmp_path / "missing.sock"

    async def scenario() -> None:
        with pytest.raises(ValueError, match="NaN"):
            await wait_for_unix_socket(socket_path, timeout=float("nan"))
        with pytest.raises(ValueError, match="negative"):
            await wait_for_unix_socket(socket_path, timeout=-1.0)
        for interval in (0.0, -1.0, float("nan")):
            with pytest.raises(ValueError, match="positive"):
                await wait_for_unix_socket(socket_path, timeout=1.0, interval=interval)

    asyncio.run(scenario())


@pytest.mark.skipif(not _HAS_UNIX_SOCKETS, reason="AF_UNIX is unavailable on this platform")
def test_wait_for_unix_socket_honors_success_that_raced_the_deadline(
    unix_socket_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def racing_wait_for(
        future: asyncio.Future[tuple[asyncio.StreamReader, asyncio.StreamWriter]], timeout: float
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        await future
        raise asyncio.TimeoutError

    socket_path = unix_socket_path

    async def scenario() -> None:
        server = await asyncio.start_unix_server(  # type: ignore[attr-defined,unused-ignore]
            lambda _r, w: w.close(), path=socket_path
        )
        try:
            async with server:
                monkeypatch.setattr(asyncio, "wait_for", racing_wait_for)
                await wait_for_unix_socket(socket_path, timeout=0.5)
        finally:
            socket_path.unlink(missing_ok=True)

    asyncio.run(scenario())


def test_wait_for_unix_socket_without_af_unix_raises_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The guard is an OR condition, so removing the connector it actually calls
    # is sufficient. Deliberately leave ``socket.AF_UNIX`` intact: it is global
    # process state and deleting it makes unrelated ``socket.socketpair()``
    # calls fall back to AF_INET on POSIX event-loop self-pipe setup.
    monkeypatch.delattr(asyncio, "open_unix_connection", raising=False)

    async def scenario() -> None:
        with pytest.raises(Unsupported) as excinfo:
            await wait_for_unix_socket(tmp_path / "missing.sock", timeout=1.0)
        assert excinfo.value.operation == "wait_for_unix_socket"

    asyncio.run(scenario())


# --- wait_for_http (an HTTP endpoint answers with an expected status) --------


async def _serve_http(
    port: int, status: int, *, reason: str = "OK", body: bytes = b""
) -> asyncio.AbstractServer:
    # A minimal one-shot HTTP/1.1 responder on 127.0.0.1: read the request head
    # (up to the blank line, so the peer's write side never blocks), then reply
    # with `status`. Enough to exercise wait_for_http without a web framework;
    # a fresh handler runs per connection, so each retry attempt gets a reply.
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(Exception):
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b""):
                    break
            head = (
                f"HTTP/1.1 {status} {reason}\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("latin-1")
            writer.write(head + body)
            await writer.drain()
            writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", port)


@pytest.mark.parametrize("status", [100, 200, 204, 503, 999])
def test_parse_http_status_code_accepts_three_ascii_digits(status: int) -> None:
    assert _parse_status_code(f"HTTP/1.1 {status} Ready\r\n".encode()) == status


@pytest.mark.parametrize("status_token", [b"20", b"2000", b"two"])
def test_parse_http_status_code_rejects_malformed_tokens(status_token: bytes) -> None:
    with pytest.raises(ProcessError, match="exactly three ASCII digits"):
        _parse_status_code(b"HTTP/1.1 " + status_token + b" Weird\r\n")


def test_wait_for_http_ready() -> None:
    async def scenario() -> None:
        port = free_port()
        server = await _serve_http(port, 200)
        async with server:
            await wait_for_http("127.0.0.1", port, "/health", timeout=5.0)

    asyncio.run(scenario())


def test_wait_for_http_ready_at_zero_timeout() -> None:
    # Symmetry with the sibling helpers: an already-ready endpoint must still
    # succeed at timeout=0 (at least one request attempt always happens), not
    # fail before it was ever probed.
    async def scenario() -> None:
        port = free_port()
        server = await _serve_http(port, 204, reason="No Content")
        async with server:
            await wait_for_http("127.0.0.1", port, timeout=0.0)

    asyncio.run(scenario())


def test_wait_for_http_rejects_nan_timeout() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="NaN"):
            await wait_for_http("127.0.0.1", 1, timeout=float("nan"))
        with pytest.raises(ValueError):
            await wait_for_http("127.0.0.1", 1, timeout=1.0, interval=float("nan"))

    asyncio.run(scenario())


def test_wait_for_http_rejects_negative_timeout() -> None:
    # Unified `timeout<=0` contract: a negative timeout is rejected outright
    # (like NaN), the same across every readiness helper.
    async def scenario() -> None:
        with pytest.raises(ValueError, match="negative"):
            await wait_for_http("127.0.0.1", 1, timeout=-1.0)

    asyncio.run(scenario())


def test_wait_for_http_rejects_nonpositive_interval() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError):
            await wait_for_http("127.0.0.1", 1, timeout=1.0, interval=0)
        with pytest.raises(ValueError):
            await wait_for_http("127.0.0.1", 1, timeout=1.0, interval=-1.0)

    asyncio.run(scenario())


def test_wait_for_http_times_out_when_never_ready() -> None:
    async def scenario(port: int) -> None:
        with pytest.raises(TimeoutError):
            await wait_for_http("127.0.0.1", port, timeout=0.4)

    with refused_port() as port:  # nothing listening
        asyncio.run(scenario(port))


def test_wait_for_http_zero_timeout_unready_fails() -> None:
    async def scenario(port: int) -> None:
        with pytest.raises(WaitTimeout):
            await wait_for_http("127.0.0.1", port, timeout=0.0)

    with refused_port() as port:  # nothing listening
        asyncio.run(scenario(port))


def test_wait_for_http_timeout_carries_host_port_path() -> None:
    # Like wait_for_port's WaitTimeout, but also carrying `path` — the one
    # variant where all three apply.
    async def scenario(port: int) -> None:
        with pytest.raises(WaitTimeout) as excinfo:
            await wait_for_http("127.0.0.1", port, "/ready", timeout=0.4)
        assert isinstance(excinfo.value, TimeoutError)
        assert isinstance(excinfo.value, ProcessError)
        assert excinfo.value.timeout_seconds == 0.4
        assert excinfo.value.host == "127.0.0.1"
        assert excinfo.value.port == port
        assert excinfo.value.path == "/ready"

    with refused_port() as port:  # nothing listening
        asyncio.run(scenario(port))


def test_wait_for_http_chains_last_connection_error() -> None:
    # An unresolvable hostname: the DNS/connect failure survives as the
    # TimeoutError's cause instead of being silently discarded.
    async def scenario() -> None:
        with pytest.raises(TimeoutError) as excinfo:
            await wait_for_http("this-host-does-not-resolve.invalid", 1, timeout=0.4, interval=0.05)
        assert isinstance(excinfo.value.__cause__, OSError)

    asyncio.run(scenario())


def test_wait_for_http_unexpected_status_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A 503 (still warming up) is NOT ready under the default 2xx set: unlike a
    # bare `wait_for_port`, the probe keeps retrying and finally times out,
    # chaining the last unexpected status code as the cause.
    #
    # Deterministic construction: same race as
    # test_wait_for_http_malformed_response_is_not_ready above -- every attempt
    # but the first hands its per-attempt `asyncio.wait_for` the ENTIRE
    # remaining budget, which on the last retry before the deadline can be a
    # thin sliver. Under real CI scheduling delay that last probe can be
    # cancelled by ITS OWN `wait_for` before the 503 status line is even read,
    # overwriting the meaningful `_HttpProbeError`/`ProcessError` cause with a
    # bare `TimeoutError`. Patching `asyncio.wait_for` to simply await the
    # future (no extra per-attempt deadline of its own) removes exactly that
    # race without weakening intent: the 503 status is still read and rejected
    # on every attempt, `wait_for_http` still retries until ITS OWN outer
    # deadline (tracked via `loop.time()`, untouched here) elapses, and the
    # final `WaitTimeout` is still chained from a genuine `ProcessError`
    # recorded by the last completed attempt.
    async def passthrough_wait_for(fut: asyncio.Future[int], timeout: float) -> int:
        del timeout
        return await fut

    async def scenario() -> None:
        port = free_port()
        server = await _serve_http(port, 503, reason="Service Unavailable")
        async with server:
            monkeypatch.setattr(asyncio, "wait_for", passthrough_wait_for)
            with pytest.raises(WaitTimeout) as excinfo:
                await wait_for_http("127.0.0.1", port, timeout=0.4, interval=0.05)
            cause = excinfo.value.__cause__
            assert isinstance(cause, ProcessError)
            assert getattr(cause, "status", None) == 503

    asyncio.run(scenario())


def test_wait_for_http_accepts_a_custom_status_container() -> None:
    # `expected_status` as a container: a caller who considers 503 "ready"
    # succeeds via membership testing.
    async def scenario() -> None:
        port = free_port()
        server = await _serve_http(port, 503, reason="Service Unavailable")
        async with server:
            await wait_for_http("127.0.0.1", port, timeout=5.0, expected_status={200, 503})

    asyncio.run(scenario())


def test_wait_for_http_accepts_a_status_predicate() -> None:
    # `expected_status` as a predicate over the code, not only a container.
    async def scenario() -> None:
        port = free_port()
        server = await _serve_http(port, 204, reason="No Content")
        async with server:
            await wait_for_http(
                "127.0.0.1", port, timeout=5.0, expected_status=lambda code: code == 204
            )

    asyncio.run(scenario())


def test_wait_for_http_malformed_response_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A server answering with a non-HTTP line is a failed attempt (retried, then
    # timed out), never an uncaught crash inside the helper.
    #
    # Deterministic construction: every attempt but the first hands its per-attempt
    # `asyncio.wait_for` the ENTIRE remaining budget (see wait_for_http's own
    # comments on `attempt_timeout`), which on the last retry before the deadline
    # can be a thin sliver. Under real CI scheduling delay that last probe can be
    # cancelled by ITS OWN `wait_for` before the malformed line is even read,
    # overwriting the meaningful `_HttpProbeError`/`ProcessError` cause with a bare
    # `TimeoutError` -- a real race, reproducible locally under load, independent of
    # how generous `timeout` is (a larger `timeout` does not shrink the final
    # sliver's odds). Patching `asyncio.wait_for` to simply await the future (no
    # extra per-attempt deadline of its own) removes exactly that race without
    # weakening intent: the malformed line is still read and rejected on every
    # attempt, `wait_for_http` still retries until ITS OWN outer deadline (tracked
    # via `loop.time()`, untouched here) elapses, and the final `WaitTimeout` is
    # still chained from a genuine `ProcessError` recorded by the last completed
    # attempt.
    async def passthrough_wait_for(fut: asyncio.Future[int], timeout: float) -> int:
        del timeout
        return await fut

    async def scenario() -> None:
        port = free_port()

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            with contextlib.suppress(Exception):
                await reader.readline()
                writer.write(b"not-an-http-response\r\n")
                await writer.drain()
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", port)
        async with server:
            monkeypatch.setattr(asyncio, "wait_for", passthrough_wait_for)
            with pytest.raises(WaitTimeout) as excinfo:
                await wait_for_http("127.0.0.1", port, timeout=0.4, interval=0.05)
            assert isinstance(excinfo.value.__cause__, ProcessError)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status_token", "expected_status"),
    [(b"2000", {2000}), (b"20", {20}), (b"two", set())],
)
def test_wait_for_http_malformed_status_code_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
    status_token: bytes,
    expected_status: set[int],
) -> None:
    async def passthrough_wait_for(fut: asyncio.Future[int], timeout: float) -> int:
        del timeout
        return await fut

    async def scenario() -> None:
        port = free_port()

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            with contextlib.suppress(Exception):
                await reader.readline()
                writer.write(
                    b"HTTP/1.1 "
                    + status_token
                    + b" Weird\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
                await writer.drain()
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", port)
        async with server:
            monkeypatch.setattr(asyncio, "wait_for", passthrough_wait_for)
            with pytest.raises(WaitTimeout) as excinfo:
                await wait_for_http(
                    "127.0.0.1",
                    port,
                    timeout=0.2,
                    interval=0.05,
                    expected_status=expected_status,
                )
            cause = excinfo.value.__cause__
            assert isinstance(cause, ProcessError)
            assert getattr(cause, "status", None) is None
            assert "exactly three ASCII digits" in str(cause)

    asyncio.run(scenario())


def test_wait_for_http_honors_success_that_raced_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression mirror of wait_for_port's same-tick race (K-030): if the probe
    # actually read an acceptable status in the very tick the deadline cancelled
    # it, wait_for_http must honor that met success instead of closing the live
    # transport and raising WaitTimeout. A patched `asyncio.wait_for` drives the
    # probe to a genuine success and *then* reports a timeout, mocking the race.
    async def racing_wait_for(fut: asyncio.Future[int], timeout: float) -> int:
        await fut  # the probe completes (its status is read)...
        raise asyncio.TimeoutError  # ...but the deadline "fires" in the same tick

    async def scenario() -> None:
        port = free_port()
        server = await _serve_http(port, 200)
        async with server:
            monkeypatch.setattr(asyncio, "wait_for", racing_wait_for)
            # Must return normally: the raced-but-read acceptable status wins.
            await wait_for_http("127.0.0.1", port, timeout=0.5)

    asyncio.run(scenario())


def test_wait_for_http_bounds_and_closes_a_hanging_server() -> None:
    # A server that accepts the connection and reads the request but never
    # answers must not let wait_for_http outlive its deadline (the whole
    # request/response is bounded, not just the connect), and the probe must
    # close its transport on timeout — the server observes the peer disconnect.
    async def scenario() -> None:
        port = free_port()
        peer_closed = asyncio.Event()

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    line = await reader.readline()
                    if line in (b"\r\n", b""):
                        break
                if await reader.read() == b"":  # blocks until the client closes
                    peer_closed.set()
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", port)
        async with server:
            loop = asyncio.get_running_loop()
            start = loop.time()
            with pytest.raises(WaitTimeout):
                await asyncio.wait_for(
                    wait_for_http("127.0.0.1", port, timeout=0.3, interval=0.05), timeout=5.0
                )
            elapsed = loop.time() - start
            assert elapsed < 2.0, f"wait_for_http did not bound the hanging server ({elapsed:.1f}s)"
            # The probe closed its transport on timeout — the server sees EOF.
            await asyncio.wait_for(peer_closed.wait(), timeout=2.0)

    asyncio.run(scenario())


def test_wait_for_http_cancel_propagates() -> None:
    async def scenario(port: int) -> None:
        task = asyncio.ensure_future(wait_for_http("127.0.0.1", port, timeout=10.0))
        await asyncio.sleep(0.05)  # let it enter the retry loop
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with refused_port() as port:  # nothing listening -> the helper stays in its retry loop
        asyncio.run(scenario(port))


# --- wait_for_http: host/path validation (T-147) ------------------------------


def test_wait_for_http_brackets_ipv6_host_in_header() -> None:
    # An IPv6 literal host must produce a bracketed `Host` header per RFC
    # 9112/3986 (`Host: [::1]:port`), not the ambiguous `Host: ::1:port` a bare
    # colon-separated literal would otherwise produce — some servers reject the
    # latter outright with a 400, which would otherwise leave the probe
    # "forever not ready" for a confusing reason.
    received_head = ""

    async def scenario() -> None:
        nonlocal received_head
        port = free_port()

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            nonlocal received_head
            with contextlib.suppress(Exception):
                while True:
                    line = await reader.readline()
                    if line in (b"\r\n", b""):
                        break
                    received_head += line.decode("latin-1")
                writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
                await writer.drain()
                writer.close()

        try:
            server = await asyncio.start_server(handle, "::1", port)
        except OSError:
            pytest.skip("IPv6 loopback is not available in this environment")
        async with server:
            await wait_for_http("::1", port, timeout=5.0)

    asyncio.run(scenario())
    assert "Host: [::1]:" in received_head


def test_wait_for_http_accepts_bracketed_ipv6_host() -> None:
    received_host = ""
    server_port = 0

    async def scenario() -> None:
        nonlocal received_host, server_port

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            nonlocal received_host
            with contextlib.suppress(Exception):
                while line := await reader.readline():
                    if line == b"\r\n":
                        break
                    if line.lower().startswith(b"host:"):
                        received_host = line.decode("latin-1").strip()
                writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
                await writer.drain()
                writer.close()

        try:
            server = await asyncio.start_server(handle, "::1", 0)
        except OSError:
            pytest.skip("IPv6 loopback is not available in this environment")
        server_port = server.sockets[0].getsockname()[1]
        async with server:
            await wait_for_http("[::1]", server_port, timeout=5.0)

    asyncio.run(scenario())
    assert received_host == f"Host: [::1]:{server_port}"


def test_wait_for_http_ipv4_and_dns_hosts_stay_unbracketed() -> None:
    # Regression: existing IPv4/DNS-name behavior must not change.
    received_head = ""

    async def scenario() -> None:
        nonlocal received_head
        port = free_port()

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            nonlocal received_head
            with contextlib.suppress(Exception):
                while True:
                    line = await reader.readline()
                    if line in (b"\r\n", b""):
                        break
                    received_head += line.decode("latin-1")
                writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
                await writer.drain()
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", port)
        async with server:
            await wait_for_http("127.0.0.1", port, timeout=5.0)

    asyncio.run(scenario())
    assert "Host: 127.0.0.1:" in received_head
    assert "[" not in received_head


def test_format_host_header_percent_encodes_scoped_ipv6_zone_id() -> None:
    assert _format_host_header("fe80::1%eth0", 8080) == "[fe80::1%25eth0]:8080"
    assert _format_host_header("[fe80::1%25eth0]", 8080) == "[fe80::1%25eth0]:8080"
    assert _http_connection_host("[fe80::1%25eth0]") == "fe80::1%eth0"
    assert _http_connection_host("host%25name.example") == "host%25name.example"


def test_wait_for_http_rejects_path_with_space() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="whitespace or control characters"):
            await wait_for_http("127.0.0.1", 1, "/foo bar", timeout=1.0)

    asyncio.run(scenario())


@pytest.mark.parametrize("bad_char", ["\x85", "\xa0"])
def test_wait_for_http_rejects_latin1_control_and_whitespace_in_path(bad_char: str) -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="whitespace or control characters"):
            await wait_for_http("127.0.0.1", 1, f"/foo{bad_char}bar", timeout=1.0)

    asyncio.run(scenario())


def test_wait_for_http_rejects_path_with_crlf() -> None:
    # The header-injection-shaped case: an untrusted `path` carrying CR/LF must
    # never reach the request line unvalidated.
    async def scenario() -> None:
        with pytest.raises(ValueError, match="whitespace or control characters"):
            await wait_for_http("127.0.0.1", 1, "/foo\r\nX-Injected: 1", timeout=1.0)

    asyncio.run(scenario())


def test_wait_for_http_path_validation_is_fail_fast() -> None:
    # The ValueError must fire before any connection attempt -- an unreachable
    # host/port must not delay or mask it (fail-fast, not "after one retry
    # cycle").
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(ValueError, match="whitespace or control characters"):
            await wait_for_http("this-host-does-not-resolve.invalid", 1, "/bad path", timeout=5.0)
        elapsed = loop.time() - start
        assert elapsed < 1.0, "path validation should reject before any network attempt"

    asyncio.run(scenario())


def test_wait_for_http_host_validation_is_fail_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    async def unexpected_open_connection(
        _host: str, _port: int, **_kwargs: object
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        nonlocal attempts
        attempts += 1
        raise AssertionError("invalid host must be rejected before connecting")

    monkeypatch.setattr(asyncio, "open_connection", unexpected_open_connection)

    async def scenario() -> None:
        with pytest.raises(ValueError, match="whitespace or control characters"):
            await wait_for_http("127.0.0.1\r\nX-Injected: yes", 8080, timeout=30.0)

    asyncio.run(scenario())
    assert attempts == 0


def test_wait_for_http_rejects_non_latin1_path() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="latin-1"):
            await wait_for_http("127.0.0.1", 1, "/café☃", timeout=1.0)

    asyncio.run(scenario())


def test_wait_for_http_rejects_non_latin1_host() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="latin-1"):
            await wait_for_http("h☃ost.invalid", 1, timeout=1.0)

    asyncio.run(scenario())


# --- wait_for_path (filesystem path appears) ---------------------------------


def test_wait_for_path_succeeds_when_path_appears(tmp_path: Path) -> None:
    target = tmp_path / "ready.sock"

    async def scenario() -> None:
        async def create_soon() -> None:
            await asyncio.sleep(0.1)
            target.touch()

        creator = asyncio.ensure_future(create_soon())
        try:
            await wait_for_path(target, timeout=5.0, interval=0.01)
        finally:
            await creator

    asyncio.run(scenario())
    assert target.exists()


def test_wait_for_path_times_out_when_path_never_appears(tmp_path: Path) -> None:
    missing = tmp_path / "never.sock"

    async def scenario() -> None:
        with pytest.raises(WaitTimeout) as excinfo:
            await wait_for_path(missing, timeout=0.2, interval=0.01)
        assert excinfo.value.timeout_seconds == 0.2
        assert excinfo.value.path == missing

    asyncio.run(scenario())


def test_wait_for_path_is_also_a_timeout_error(tmp_path: Path) -> None:
    missing = tmp_path / "never.sock"

    async def scenario() -> None:
        with pytest.raises(TimeoutError):
            await wait_for_path(missing, timeout=0.2, interval=0.01)

    asyncio.run(scenario())


def test_wait_for_path_ready_at_zero_timeout(tmp_path: Path) -> None:
    # Symmetry with wait_until/wait_for_port/wait_for_line: an already-existing
    # path must still succeed at timeout=0 (at least one check always happens),
    # not fail before it was ever checked.
    existing = tmp_path / "already-there"
    existing.touch()

    async def scenario() -> None:
        await wait_for_path(existing, timeout=0.0)

    asyncio.run(scenario())


def test_wait_for_path_rejects_nan_timeout(tmp_path: Path) -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="NaN"):
            await wait_for_path(tmp_path / "x", timeout=float("nan"))
        # A NaN `interval` fails the shared `interval > 0` guard (every NaN
        # comparison is False), the same as a non-positive interval.
        with pytest.raises(ValueError, match="positive"):
            await wait_for_path(tmp_path / "x", timeout=1.0, interval=float("nan"))

    asyncio.run(scenario())


def test_wait_for_path_rejects_negative_timeout(tmp_path: Path) -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError, match="negative"):
            await wait_for_path(tmp_path / "x", timeout=-1.0)

    asyncio.run(scenario())


def test_wait_for_path_rejects_nonpositive_interval(tmp_path: Path) -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError):
            await wait_for_path(tmp_path / "x", timeout=1.0, interval=0)
        with pytest.raises(ValueError):
            await wait_for_path(tmp_path / "x", timeout=1.0, interval=-1.0)

    asyncio.run(scenario())


def test_wait_for_path_accepts_str_and_pathlike(tmp_path: Path) -> None:
    existing = tmp_path / "already-there"
    existing.touch()

    async def scenario() -> None:
        await wait_for_path(str(existing), timeout=0.0)  # plain str
        await wait_for_path(existing, timeout=0.0)  # os.PathLike[str]

    asyncio.run(scenario())
