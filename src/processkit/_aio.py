"""Pure-Python asyncio helpers layered on top of the compiled extension.

Two families live here:

- **Readiness helpers** (`wait_until` / `wait_for_line` / `wait_for_port` /
  `wait_for_path`) compose on top of the compiled async surface (a
  `StdoutLines` iterator, a plain TCP connect) rather than bridging the Rust
  crate's borrowing probe methods — simpler, fully composable, and they work
  against any server, not only one this package started. (The `processkit`
  crate's 1.1.0 made its probes `Send`-bridgeable, but these Python helpers are
  kept deliberately: a free `wait_for_line(iterator)` / `wait_for_port(host,
  port)` is more composable than methods bound to one started
  `RunningProcess`.)
- **`sample_stats`** — a periodic `ProcessGroupStats` series, for the same
  reason: the crate's `StatsSampler` borrows the group by lifetime and has no
  FFI-safe equivalent, so this is plain Python built directly on the already
  -public `ProcessGroup.stats()`.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar, overload

from ._processkit import ProcessError, ProcessGroup, ProcessGroupStats
from ._types import StrPath

__all__ = [
    "WaitTimeout",
    "sample_stats",
    "wait_for_line",
    "wait_for_path",
    "wait_for_port",
    "wait_until",
]


_ZERO_TIMEOUT_CONNECT_TICK = 0.05


class WaitTimeout(ProcessError, TimeoutError):
    """A readiness helper (`wait_until` / `wait_for_line` / `wait_for_port` /
    `wait_for_path`) didn't succeed within its deadline.

    Also a builtin `TimeoutError`, so `except TimeoutError` catches it too —
    the same convention a run's own `.timeout()` uses (see `Timeout`). Always
    carries `timeout_seconds`; `wait_for_port` additionally sets `host` /
    `port`, and `wait_for_path` sets `path` (all `None` for `wait_until` /
    `wait_for_line`, which have none of these) and chains the last connection
    attempt's exception as `__cause__` (`wait_for_port` only).
    """

    def __init__(
        self,
        message: str,
        *,
        timeout_seconds: float,
        host: str | None = None,
        port: int | None = None,
        path: StrPath | None = None,
    ) -> None:
        super().__init__(message)
        self.timeout_seconds = timeout_seconds
        self.host = host
        self.port = port
        self.path = path


def _check_timeout(timeout: float) -> None:
    """Shared ``timeout`` validation for `wait_until` / `wait_for_port` /
    `wait_for_line`: NaN and negative values are both rejected outright rather
    than silently accepted. ``timeout == 0`` is valid and means "evaluate
    exactly once, right now" — see each helper's docstring.
    """
    if math.isnan(timeout):
        raise ValueError("timeout must not be NaN")
    if timeout < 0:
        raise ValueError("timeout must not be negative")


async def _quiesce(task: asyncio.Task[Any]) -> None:
    """Cancel a task we own and wait for it to settle, without raising its own
    exception into this frame (the caller inspects ``task.exception()`` /
    ``task.result()`` afterwards) and without corrupting a *fresh* cancellation
    that lands on us while doing so. Only call this for a task ``wait_until`` /
    ``wait_for_line`` created itself — never for a caller-supplied Future/Task
    (see their ``owns_task`` guards).
    """
    task.cancel()
    pending_cancel: asyncio.CancelledError | None = None
    while True:
        try:
            # Never `await task` directly here: that would raise the task's OWN
            # exception (e.g. from cleanup code that catches its CancelledError
            # and raises something else instead), which would mask a `raise`d
            # fresh cancellation below. `asyncio.wait` only raises if THIS
            # await itself is cancelled again.
            await asyncio.wait({task})
        except asyncio.CancelledError as exc:
            pending_cancel = exc
            task.cancel()
            continue
        break
    if pending_cancel is not None:
        # A *fresh* cancellation landed on us while draining — it wins over
        # whatever the inner task did, so we raise it below instead of
        # returning normally. That means the caller never reaches their own
        # `task.exception()` / `task.result()` inspection (it's skipped by the
        # `raise`), yet the task IS done by now (the loop above only `break`s
        # once `asyncio.wait` completes without itself being cancelled again)
        # and may have finished with its own exception (e.g. cleanup code that
        # caught its second CancelledError and raised something else instead
        # of re-raising it). Retrieve it here — even though we deliberately
        # discard it in favor of `pending_cancel` — so asyncio's default
        # exception handler doesn't report "Task exception was never
        # retrieved" once `task` is garbage-collected. `task.exception()`
        # itself raises `CancelledError` for a task that finished cancelled
        # (rather than with its own exception), so only call it when that
        # isn't the case.
        if not task.cancelled():
            task.exception()
        raise pending_cancel


async def wait_until(
    predicate: Callable[[], bool | Awaitable[bool]],
    *,
    timeout: float,
    interval: float = 0.05,
) -> None:
    """Poll ``predicate`` until it returns true, or ``timeout`` seconds elapse.

    (Named ``wait_until``, not ``wait_for`` — the latter would collide with
    ``asyncio.wait_for``, whose semantics differ: it bounds one *awaitable*,
    not a *polled predicate*.)

    ``predicate`` may be synchronous or return an awaitable. Polls every
    ``interval`` seconds; raises `WaitTimeout` (also a `TimeoutError`) if the
    deadline passes first. A synchronous ``predicate`` runs on the event loop,
    so keep it non-blocking — use an async ``predicate`` for anything that does
    I/O. If ``predicate``'s awaitable is already a `asyncio.Future`/`asyncio.Task`
    you own, note it is never cancelled by this helper on timeout — only
    abandoned, so cancel or await it yourself afterwards if that matters.

    ``timeout<=0`` contract (shared with `wait_for_port` / `wait_for_line`):
    at ``timeout=0``, ``predicate`` is still evaluated (at least once) before
    any deadline check, so an already-true predicate succeeds instead of
    failing before it was ever checked. A **negative** ``timeout`` is rejected
    outright — raises `ValueError`, same as NaN — rather than being treated as
    "expired" or silently accepted.
    """
    if not interval > 0:  # rejects NaN too (every NaN comparison is False)
        raise ValueError("interval must be a positive number of seconds")
    _check_timeout(timeout)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        outcome = predicate()
        if isinstance(outcome, Awaitable):
            # Bound the predicate by the deadline so a hung async predicate (a server
            # that accepts but never answers) can't outlive ``timeout``. Drive it as an
            # explicit task under ``asyncio.wait`` rather than ``asyncio.wait_for``:
            # ``wait_for`` cancels the task *before it runs* at ``timeout<=0`` (which
            # would break "evaluate at least once"), and its own ``TimeoutError`` is
            # indistinguishable from one the predicate raises for its own I/O. With
            # ``asyncio.wait`` we tell the two apart — if our deadline fires the task
            # isn't ``done``; otherwise ``task.result()`` re-raises the predicate's own
            # exception untouched.
            task = asyncio.ensure_future(outcome)
            # `ensure_future` returns a pre-existing Future/Task unchanged: never
            # cancel or drain an object we didn't create ourselves.
            owns_task = task is not outcome
            remaining = deadline - loop.time()
            try:
                done, _pending = await asyncio.wait({task}, timeout=max(remaining, 0.0))
            except asyncio.CancelledError:
                # The caller cancelled us — propagate that, never a WaitTimeout.
                if owns_task:
                    await _quiesce(task)
                raise
            if task not in done:
                # Our deadline fired first.
                if owns_task:
                    await _quiesce(task)
                    if not task.cancelled():
                        exc = task.exception()
                        if exc is not None:
                            # The predicate finished with its own exception in the
                            # same tick as our deadline — that's the real cause,
                            # not a timeout; let it propagate untouched.
                            raise exc
                        if task.result():
                            # It also finished truthy in that same tick — honor it
                            # rather than discarding a met condition.
                            return
                raise WaitTimeout(f"condition not met within {timeout}s", timeout_seconds=timeout)
            ready = task.result()
        else:
            ready = outcome
        if ready:
            return
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise WaitTimeout(f"condition not met within {timeout}s", timeout_seconds=timeout)
        await asyncio.sleep(min(interval, remaining))


async def wait_for_path(
    path: StrPath,
    *,
    timeout: float,
    interval: float = 0.05,
) -> None:
    """Wait until ``path`` exists on the filesystem.

    Polls every ``interval`` seconds until ``path.exists()`` returns true or
    ``timeout`` seconds elapse, in which case `WaitTimeout` (also a
    `TimeoutError`) is raised, carrying ``path``. A unix-socket, a pid file, or
    any other marker file a daemon creates once ready are all typical uses —
    for a TCP port or an arbitrary predicate, see `wait_for_port` /
    `wait_until` instead (`wait_until(lambda: path.exists(), ...)` is exactly
    what this helper does, named for readability and given the same
    `WaitTimeout` discipline as its siblings).

    ``timeout<=0`` contract (shared with `wait_until` / `wait_for_port` /
    `wait_for_line`): at ``timeout=0``, ``path`` is still checked (at least
    once) before any deadline check, so an already-existing path succeeds
    instead of failing before it was ever checked. A **negative** ``timeout``
    is rejected outright — raises `ValueError`, same as NaN — rather than
    being treated as "expired" or silently accepted.
    """
    if not interval > 0:  # rejects NaN too (every NaN comparison is False)
        raise ValueError("interval must be a positive number of seconds")
    _check_timeout(timeout)
    target = Path(path)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if target.exists():
            return
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise WaitTimeout(
                f"path {target} did not appear within {timeout}s",
                timeout_seconds=timeout,
                path=path,
            )
        await asyncio.sleep(min(interval, remaining))


_Connection = tuple[asyncio.StreamReader, asyncio.StreamWriter]


def _close_pending_connection(task: asyncio.Task[_Connection]) -> None:
    """Close a probe transport that ``open_connection`` produced but that we never
    took ownership of — e.g. a timeout or cancellation that raced a successful
    connect (the classic ``asyncio.wait_for`` leak, where the established
    connection is dropped on the floor). If the task hasn't finished, cancel it so
    it can't produce an orphan transport later.
    """
    if not task.done():
        task.cancel()
        return
    if task.cancelled() or task.exception() is not None:
        return
    _reader, writer = task.result()
    writer.close()


async def wait_for_port(
    host: str,
    port: int,
    *,
    timeout: float,
    interval: float = 0.05,
) -> None:
    """Wait until a TCP connection to ``(host, port)`` succeeds.

    Polls every ``interval`` seconds until the port accepts a connection or
    ``timeout`` seconds elapse, in which case `WaitTimeout` (also a
    `TimeoutError`) is raised — carrying ``host``/``port`` — chained from the
    last connection attempt's exception (e.g. a DNS failure survives as the
    cause instead of being silently dropped).

    ``timeout<=0`` contract (shared with `wait_until` / `wait_for_line`): at
    ``timeout=0``, a connection attempt is still made (at least one), so an
    already-ready port succeeds instead of failing before a connection was
    ever tried — this first attempt is not cut short by the already-expired
    deadline. It IS bounded, though: to a short, fixed event-loop tick (or a
    smaller caller-supplied ``interval``), not left uncapped — an
    unresolvable/blackhole address would
    otherwise be free to block on the OS's own (much longer, or absent)
    connect/DNS timeout well past the caller's requested deadline. A
    **negative** ``timeout`` is rejected outright — raises `ValueError`, same
    as NaN — rather than being treated as "expired" or silently accepted.
    """
    if not interval > 0:  # rejects NaN too (every NaN comparison is False)
        raise ValueError("interval must be a positive number of seconds")
    _check_timeout(timeout)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last_exc: BaseException | None = None
    first_attempt = True
    while True:
        remaining = deadline - loop.time()
        if not first_attempt and remaining <= 0:
            raise WaitTimeout(
                f"port {host}:{port} not ready within {timeout}s",
                timeout_seconds=timeout,
                host=host,
                port=port,
            ) from last_exc
        first_attempt = False
        # Own the connect as a task: if a timeout or a cancellation races a
        # successful connect, `asyncio.wait_for` can drop the established transport
        # on the floor (a known leak). Owning the task lets us close it instead.
        conn = asyncio.ensure_future(asyncio.open_connection(host, port))
        try:
            # A short fixed tick (never unbounded/`None`) only on this — the
            # first — attempt, and only when the deadline has already passed
            # (``remaining <= 0``, e.g. at ``timeout=0``):
            # `asyncio.wait_for(fut, timeout<=0)` cancels ``fut`` before it
            # ever runs, which would reject an already-ready port before a
            # connection was ever attempted, so we can't just pass
            # ``remaining`` (non-positive) through unchanged either. A prior
            # version passed `None` (no cap) here instead, which let a
            # connection attempt against an unresolvable/blackhole address
            # block on the OS's own (much longer, or absent) timeout — a
            # regression this bounded tick fixes: real enough to let an
            # already-listening local port answer, short enough to never scale
            # with a caller-supplied retry interval. Preserve intervals smaller
            # than the cap; the guard above ensures the result stays positive,
            # so this never re-triggers `wait_for`'s own ``timeout<=0``
            # fast-cancel path. Every later attempt is still bounded by the
            # real ``remaining``.
            connect_timeout = (
                min(interval, _ZERO_TIMEOUT_CONNECT_TICK) if remaining <= 0 else remaining
            )
            _reader, writer = await asyncio.wait_for(conn, timeout=connect_timeout)
        except (OSError, asyncio.TimeoutError) as exc:
            _close_pending_connection(conn)
            last_exc = exc
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise WaitTimeout(
                    f"port {host}:{port} not ready within {timeout}s",
                    timeout_seconds=timeout,
                    host=host,
                    port=port,
                ) from last_exc
            # Don't overshoot the deadline by a full interval on the last retry.
            await asyncio.sleep(min(interval, remaining))
            continue
        except asyncio.CancelledError:
            _close_pending_connection(conn)
            raise
        # Connected — close the probe socket (best-effort) and succeed.
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        return


_Item = TypeVar("_Item")


@overload
async def wait_for_line(lines: AsyncIterator[str], predicate: str, *, timeout: float) -> str: ...
@overload
async def wait_for_line(
    lines: AsyncIterator[_Item], predicate: Callable[[_Item], bool], *, timeout: float
) -> _Item: ...
async def wait_for_line(
    lines: AsyncIterator[Any],
    predicate: str | Callable[[Any], bool],
    *,
    timeout: float,
) -> Any:
    """Consume from an async iterator until ``predicate`` matches an item.

    ``predicate`` is either a callable (``predicate(item) -> bool``) or, for a
    `str`-yielding iterator only, a plain `str` — a shorthand for "the item
    contains this substring" (``predicate in item``). Not just for
    `StdoutLines`: any async iterator works (e.g. `OutputEvents`, with a
    callable predicate over its `OutputEvent` items).

    Returns the matching item. Raises `WaitTimeout` (also a `TimeoutError`,
    carrying ``timeout_seconds``) if nothing matches within ``timeout``
    seconds, or propagates whatever ``predicate`` or the iterator itself
    raised (a `ProcessError` if the stream ends first) untouched — never
    masked behind the timeout. Items read before the match are consumed;
    iteration may continue afterward **only when a match was found** — on a
    `WaitTimeout`, exactly how far the iterator advanced past the last
    inspected item is unspecified (cancellation of the internal scan races the
    iterator's own advancement), so don't rely on its position after a
    timeout.

    ``timeout<=0`` contract (shared with `wait_until` / `wait_for_port`): at
    ``timeout=0``, the iterator is still scanned (at least one tick), so an
    item that already matches (already sitting in the iterator) succeeds
    instead of failing before it was ever inspected. A **negative** ``timeout``
    is rejected outright — raises `ValueError`, same as NaN — rather than being
    treated as "expired" or silently accepted.
    """
    _check_timeout(timeout)
    match: Callable[[Any], bool]
    if isinstance(predicate, str):
        needle = predicate

        def match(item: Any) -> bool:
            return needle in item
    else:
        match = predicate

    async def scan() -> Any:
        async for item in lines:
            if match(item):
                return item
        raise ProcessError("the output stream ended before a matching line")

    # Own the scan as a task and bound it with `asyncio.wait` (not
    # `asyncio.wait_for`, whose own `TimeoutError` would be indistinguishable
    # from — and can mask — a builtin-`TimeoutError`-family exception `scan()`
    # raises on its own), so an item that matches at the exact deadline is
    # recovered rather than dropped (the item is already consumed from the
    # iterator).
    task = asyncio.ensure_future(scan())
    try:
        done, _pending = await asyncio.wait({task}, timeout=max(timeout, 0.0))
    except asyncio.CancelledError:
        await _quiesce(task)
        raise
    if task not in done:
        await _quiesce(task)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                raise exc
            return task.result()
        raise WaitTimeout(f"no matching line within {timeout}s", timeout_seconds=timeout) from None
    return task.result()


# --- live monitoring (sample_stats) ------------------------------------------


def _check_every(every: float) -> None:
    if math.isnan(every):
        raise ValueError("every must not be NaN")
    if every < 0:
        raise ValueError("every must not be negative")


async def sample_stats(group: ProcessGroup, every: float) -> AsyncIterator[ProcessGroupStats]:
    """Sample ``group.stats()`` on an interval, forever, as an async series of
    `ProcessGroupStats` snapshots — a pure-Python analogue of the crate's
    `ProcessGroup::sample_stats` (its `StatsSampler` borrows the group by
    lifetime and has no FFI-safe equivalent here; this is plain Python built
    directly on the already-public `group.stats()`, living alongside the
    readiness helpers above for the same reason).

    ``async for snapshot in sample_stats(group, every): ...`` — the first
    snapshot is taken immediately (no initial sleep), then one every ``every``
    seconds, for as long as you keep consuming. There is no overall deadline;
    stop by ``break``ing out of the loop or otherwise abandoning/closing the
    generator yourself.

    **Fused, and louder than the crate's stream.** The crate's `StatsSampler`
    swallows the error on the first failed sample and just ends the series
    silently — a caller has to separately call `stats()` to learn why. This
    generator instead lets `group.stats()`'s own exception (a `ProcessError` —
    e.g. "ProcessGroup is already closed" once the group has torn down, or an
    `Unsupported`/OS-error-derived failure from the platform's resource query)
    propagate out of the ``async for`` untouched — the underlying cause is
    never hidden behind a quiet end-of-series. That still fuses the series:
    once this generator function raises, it is exhausted by Python's own
    async-generator protocol, so a further ``__anext__`` (another loop
    iteration, a second ``async for`` over the same object) raises
    `StopAsyncIteration` rather than calling `group.stats()` again or
    replaying the same error. If the group is already closed/invalid *before
    the first snapshot* (e.g. iteration starts only after `group.shutdown()`
    already ran), that same exception surfaces on the very first ``async
    for`` step, not silently as an empty series.

    ``every`` is validated up front: NaN and negative values raise
    `ValueError` (the shared convention with the readiness helpers'
    ``timeout``/``interval``). Unlike the crate — which clamps a zero period
    to 1 ms because `tokio` panics on a zero-duration interval — ``every=0``
    is accepted here as-is: `asyncio.sleep(0)` has no such restriction, so it
    means "sample as fast as the event loop allows," with no artificial floor.
    """
    _check_every(every)
    while True:
        yield group.stats()
        await asyncio.sleep(every)
