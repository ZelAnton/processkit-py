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
from collections.abc import AsyncIterator, Awaitable, Callable

from ._processkit import ProcessError

__all__ = ["wait_for", "wait_for_line", "wait_for_port"]


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
    use an async ``predicate`` for anything that does I/O.
    """
    if interval <= 0:
        raise ValueError("interval must be a positive number of seconds")
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
            remaining = deadline - loop.time()
            try:
                done, _pending = await asyncio.wait({task}, timeout=max(remaining, 0.0))
            except asyncio.CancelledError:
                # The caller cancelled us. asyncio.wait (unlike asyncio.wait_for) does
                # NOT cancel its member task, so cancel the predicate ourselves or it
                # leaks. Drain suppressing *any* exception — the task may have already
                # finished with its own error the instant we were cancelled, and that
                # must not replace the cancellation — then re-raise the CancelledError.
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
                raise
            if task not in done:
                # Our deadline fired first: cancel the predicate and drain it (again
                # swallowing whatever it raises on the way down) before timing out.
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
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
    ``timeout`` seconds elapse, in which case `TimeoutError` is raised.
    """
    if interval <= 0:
        raise ValueError("interval must be a positive number of seconds")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"port {host}:{port} not ready within {timeout}s")
        # Own the connect as a task: if a timeout or a cancellation races a
        # successful connect, `asyncio.wait_for` can drop the established transport
        # on the floor (a known leak). Owning the task lets us close it instead.
        conn = asyncio.ensure_future(asyncio.open_connection(host, port))
        try:
            _reader, writer = await asyncio.wait_for(conn, timeout=remaining)
        except (OSError, asyncio.TimeoutError):
            _close_pending_connection(conn)
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"port {host}:{port} not ready within {timeout}s") from None
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
    ``timeout`` seconds, or `ProcessError` if the stream ends first. Lines read
    before the match are consumed; iteration may continue afterwards.
    """

    async def scan() -> str:
        async for line in lines:
            if predicate(line):
                return line
        raise ProcessError("the output stream ended before a matching line")

    # Own the scan as a task so a line that matches at the exact deadline — which
    # would complete the task just as `wait_for` cancels it — is recovered rather
    # than dropped (the line is already consumed from the iterator).
    task = asyncio.ensure_future(scan())
    try:
        return await asyncio.wait_for(task, timeout)
    except asyncio.TimeoutError:
        if task.done() and not task.cancelled() and task.exception() is None:
            return task.result()
        raise TimeoutError(f"no matching line within {timeout}s") from None
