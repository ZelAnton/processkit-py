"""Pure-Python asyncio readiness helpers.

These compose on top of the compiled async surface (a `StdoutLines` iterator, a
plain TCP connect) rather than bridging the Rust crate's borrowing probe methods
— simpler, fully composable, and they work against any server, not only one this
package started. (The `processkit` crate's 1.1.0 made its probes `Send`-bridgeable,
but these Python helpers are kept deliberately: a free `wait_for_line(iterator)` /
`wait_for_port(host, port)` is more composable than methods bound to one started
`RunningProcess`.)
"""

from __future__ import annotations

import asyncio
import contextlib
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from ._processkit import ProcessError

__all__ = ["wait_for", "wait_for_line", "wait_for_port"]


def _check_timeout(timeout: float) -> None:
    if math.isnan(timeout):
        raise ValueError("timeout must not be NaN")


async def _quiesce(task: asyncio.Task[Any]) -> None:
    """Cancel a task we own and wait for it to settle, without raising its own
    exception into this frame (the caller inspects ``task.exception()`` /
    ``task.result()`` afterwards) and without corrupting a *fresh* cancellation
    that lands on us while doing so. Only call this for a task ``wait_for`` /
    ``wait_for_line`` created itself — never for a caller-supplied Future/Task
    (see their ``owns_task`` guards).
    """
    task.cancel()
    try:
        await asyncio.wait({task})
    except asyncio.CancelledError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        raise


async def wait_for(
    predicate: Callable[[], bool | Awaitable[bool]],
    *,
    timeout: float,
    interval: float = 0.05,
) -> None:
    """Poll ``predicate`` until it returns true, or ``timeout`` seconds elapse.

    ``predicate`` may be synchronous or return an awaitable. Polls every
    ``interval`` seconds; raises `TimeoutError` if the deadline passes first. A
    synchronous ``predicate`` runs on the event loop, so keep it non-blocking —
    use an async ``predicate`` for anything that does I/O. If ``predicate``'s
    awaitable is already a `asyncio.Future`/`asyncio.Task` you own, note it is
    never cancelled by this helper on timeout — only abandoned, so cancel or
    await it yourself afterwards if that matters. Raises `ValueError` if
    ``timeout`` is NaN.
    """
    if interval <= 0:
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
                # The caller cancelled us — propagate that, never a TimeoutError.
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
                raise TimeoutError(f"condition not met within {timeout}s")
            ready = task.result()
        else:
            ready = outcome
        if ready:
            return
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"condition not met within {timeout}s")
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
    ``timeout`` seconds elapse, in which case `TimeoutError` is raised, chained
    from the last connection attempt's exception (e.g. a DNS failure survives
    as the cause instead of being silently dropped). Raises `ValueError` if
    ``timeout`` is NaN.
    """
    if interval <= 0:
        raise ValueError("interval must be a positive number of seconds")
    _check_timeout(timeout)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last_exc: BaseException | None = None
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"port {host}:{port} not ready within {timeout}s") from last_exc
        # Own the connect as a task: if a timeout or a cancellation races a
        # successful connect, `asyncio.wait_for` can drop the established transport
        # on the floor (a known leak). Owning the task lets us close it instead.
        conn = asyncio.ensure_future(asyncio.open_connection(host, port))
        try:
            _reader, writer = await asyncio.wait_for(conn, timeout=remaining)
        except (OSError, asyncio.TimeoutError) as exc:
            _close_pending_connection(conn)
            last_exc = exc
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"port {host}:{port} not ready within {timeout}s") from last_exc
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


async def wait_for_line(
    lines: AsyncIterator[str],
    predicate: Callable[[str], bool],
    *,
    timeout: float,
) -> str:
    """Consume from an stdout line iterator until ``predicate(line)`` is true.

    Returns the matching line. Raises `TimeoutError` if no line matches within
    ``timeout`` seconds, or propagates whatever `predicate` or the stream itself
    raised (a `ProcessError` if the stream ends first) untouched — never masked
    behind the timeout. Lines read before the match are consumed; iteration may
    continue afterwards. Raises `ValueError` if ``timeout`` is NaN.
    """
    _check_timeout(timeout)

    async def scan() -> str:
        async for line in lines:
            if predicate(line):
                return line
        raise ProcessError("the output stream ended before a matching line")

    # Own the scan as a task and bound it with `asyncio.wait` (not
    # `asyncio.wait_for`, whose own `TimeoutError` would be indistinguishable
    # from — and can mask — a builtin-`TimeoutError`-family exception `scan()`
    # raises on its own), so a line that matches at the exact deadline is
    # recovered rather than dropped (the line is already consumed from the
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
        raise TimeoutError(f"no matching line within {timeout}s") from None
    return task.result()
