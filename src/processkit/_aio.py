"""Pure-Python asyncio helpers layered on top of the compiled extension.

Three families live here:

- **Readiness helpers** (`wait_until` / `wait_for_line` / `wait_for_port` /
  `wait_for_http` / `wait_for_path`) compose on top of the compiled async
  surface (a `StdoutLines` iterator, a plain TCP connect, a hand-rolled HTTP
  GET) rather than bridging the Rust
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
- **Streaming batch iterators** (`aoutput_as_completed` /
  `aoutput_as_completed_bytes`) fan a sequence of commands out under a hard
  concurrency cap and yield each ``(index, result)`` pair *as its command
  finishes* — a streaming, pure-Python counterpart to the compiled crate's
  *collect-all* `aoutput_all` family, built directly on `Command.aoutput()` and
  carrying the same no-orphan teardown on cancellation.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Container, Sequence
from pathlib import Path
from typing import Any, TypeVar, overload

from ._processkit import (
    BytesResult,
    Command,
    ProcessError,
    ProcessGroup,
    ProcessGroupStats,
    ProcessResult,
)
from ._types import StrPath

__all__ = [
    "WaitTimeout",
    "aoutput_as_completed",
    "aoutput_as_completed_bytes",
    "sample_stats",
    "wait_for_http",
    "wait_for_line",
    "wait_for_path",
    "wait_for_port",
    "wait_until",
]


_ZERO_TIMEOUT_CONNECT_TICK = 0.05


class WaitTimeout(ProcessError, TimeoutError):
    """A readiness helper (`wait_until` / `wait_for_line` / `wait_for_port` /
    `wait_for_http` / `wait_for_path`) didn't succeed within its deadline.

    Also a builtin `TimeoutError`, so `except TimeoutError` catches it too —
    the same convention a run's own `.timeout()` uses (see `Timeout`). Always
    carries `timeout_seconds`; `wait_for_port` and `wait_for_http` additionally
    set `host` / `port` (and `wait_for_http` also `path`), and `wait_for_path`
    sets `path` (all `None` for `wait_until` / `wait_for_line`, which have none
    of these). `wait_for_port` / `wait_for_http` also chain the last attempt's
    failure as `__cause__` (a connection error, or — for `wait_for_http` — the
    last unexpected status code).
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
        # A short fixed tick (never unbounded/`None`) floors ONLY the first
        # attempt's connect window. Two things it fixes:
        #  * at ``remaining <= 0`` (e.g. ``timeout=0``, deadline already
        #    passed) passing the non-positive ``remaining`` straight through
        #    would hit `asyncio.wait_for`'s own ``timeout<=0`` fast-cancel,
        #    which cancels the connect before it ever runs and rejects an
        #    already-ready port before a connection was even attempted; a prior
        #    version passed `None` (no cap) instead, which let an
        #    unresolvable/blackhole address block on the OS's own (much longer,
        #    or absent) timeout — the bounded tick is real enough to let an
        #    already-listening local port answer, short enough never to scale
        #    with a caller-supplied retry interval.
        #  * flooring with ``max(...)`` — rather than switching on
        #    ``remaining <= 0`` — keeps the first window MONOTONE in ``timeout``:
        #    a tiny positive ``timeout`` (e.g. ``0.001``) must never give the
        #    first attempt a SMALLER window than ``timeout=0`` does, or an
        #    already-ready local port could pass at ``timeout=0`` yet fail at
        #    ``timeout=0.001``. The floor is ``min(interval, tick)`` so it never
        #    scales past a smaller caller interval, and is strictly positive so
        #    `wait_for`'s fast-cancel path never re-triggers.
        # Every later attempt is bounded by the real ``remaining`` (kept
        # positive by the deadline guard above).
        if first_attempt:
            connect_timeout = max(remaining, min(interval, _ZERO_TIMEOUT_CONNECT_TICK))
        else:
            connect_timeout = remaining
        first_attempt = False
        # Own the connect as a task: if a timeout or a cancellation races a
        # successful connect, `asyncio.wait_for` can drop the established transport
        # on the floor (a known leak). Owning the task lets us close it — or, when
        # the connect actually completed in that same tick, honor the success.
        conn = asyncio.ensure_future(asyncio.open_connection(host, port))
        try:
            _reader, writer = await asyncio.wait_for(conn, timeout=connect_timeout)
        except (OSError, asyncio.TimeoutError) as exc:
            if (
                isinstance(exc, asyncio.TimeoutError)
                and conn.done()
                and not conn.cancelled()
                and conn.exception() is None
            ):
                # Same-tick race: the connect actually established in the very
                # tick the deadline cancelled it (the classic `wait_for` leak,
                # where a met success is reported as a timeout). Sibling helpers
                # `wait_until` / `wait_for_line` already resolve this exact race
                # in favor of the success ("honor it rather than discarding a
                # met condition"); keep `wait_for_port` consistent — succeed on
                # the proven-ready port instead of closing the live transport
                # and raising `WaitTimeout`.
                _reader, writer = conn.result()
                writer.close()
                with contextlib.suppress(OSError):
                    await writer.wait_closed()
                return
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


class _HttpProbeError(ProcessError):
    """Internal: one `wait_for_http` attempt reached the server but the reply
    wasn't an acceptable readiness signal — an unexpected status code (``status``
    set) or a malformed/absent HTTP response (``status`` is ``None``). Only ever
    surfaced as a `WaitTimeout`'s ``__cause__``, never raised to callers.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _status_predicate(
    expected_status: Container[int] | Callable[[int], bool],
) -> Callable[[int], bool]:
    """Normalize `wait_for_http`'s ``expected_status`` to a predicate: a callable
    is used as-is; anything else is treated as a container and tested with ``in``
    (so ``range(200, 300)`` / a ``set`` / a ``frozenset`` all work)."""
    if callable(expected_status):
        return expected_status
    container = expected_status
    return lambda code: code in container


def _parse_status_code(status_line: bytes) -> int:
    """Extract the integer status code from an HTTP/1.1 status line
    (``b"HTTP/1.1 200 OK\\r\\n"`` -> ``200``). Raises `_HttpProbeError` for an
    empty line (the server hung up before answering) or a malformed one."""
    parts = status_line.split(None, 2)
    if len(parts) < 2 or not parts[0].upper().startswith(b"HTTP/"):
        raise _HttpProbeError(f"malformed or empty HTTP status line: {status_line!r}")
    try:
        return int(parts[1])
    except ValueError:
        raise _HttpProbeError(f"non-numeric HTTP status code in: {status_line!r}") from None


async def _probe_http(host: str, port: int, request: bytes) -> int:
    """Open one connection, send ``request``, read the HTTP status line, and
    return its status code. Owns its socket end-to-end: the ``finally`` closes
    the writer even on cancellation/timeout, so a probe cut short by the deadline
    never leaks the connection. Only the status line is read (the request already
    asked the server to ``Connection: close``); the body is left undrained and
    dropped when the transport closes."""
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(request)
        await writer.drain()
        status_line = await reader.readline()
        code = _parse_status_code(status_line)
    finally:
        # Synchronous close in the finally guarantees the socket is released even
        # when a CancelledError is unwinding this frame; wait_closed is only
        # awaited on the normal path (below), never during cancellation.
        writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return code


def _discard_probe(task: asyncio.Task[int]) -> None:
    """Settle a probe task we own but no longer want — a failed, raced, or
    cancelled attempt. Cancel it if still running (its own ``finally`` then closes
    the socket); otherwise retrieve its result/exception so a finished-with-error
    task doesn't trip asyncio's 'exception never retrieved' warning."""
    if not task.done():
        task.cancel()
        return
    if task.cancelled():
        return
    task.exception()


async def wait_for_http(
    host: str,
    port: int,
    path: str = "/",
    *,
    timeout: float,
    interval: float = 0.05,
    expected_status: Container[int] | Callable[[int], bool] | None = None,
) -> None:
    """Wait until an HTTP ``GET`` of ``http://host:port/path`` answers with an
    acceptable status code.

    A stronger readiness signal than `wait_for_port`: a server often *accepts*
    TCP connections while still warming up and answering ``503``, so a bare port
    probe reports ready too early. This one performs a minimal HTTP/1.1 ``GET``
    (hand-rolled over `asyncio.open_connection` — no `http.client` / `urllib` /
    third-party dependency) every ``interval`` seconds and succeeds only once the
    response's status code is accepted.

    ``expected_status`` decides what "accepted" means: either a container tested
    with ``in`` or a predicate ``Callable[[int], bool]`` for arbitrary logic
    (e.g. ``lambda c: c == 204``). The default (``None``) accepts any 2xx code —
    equivalent to passing ``range(200, 300)``. The whole request/response is
    bounded by the deadline, so a server that accepts the connection but never
    answers can't outlive ``timeout``.

    On failure the deadline raises `WaitTimeout` (also a `TimeoutError`),
    carrying ``host`` / ``port`` / ``path`` and chained (as ``__cause__``) from
    the last attempt's failure — a connection error (e.g. a refused connect or a
    DNS failure) or a `ProcessError` recording the last unexpected status code —
    so the evidence for *why* it never became ready survives.

    ``timeout<=0`` contract (shared with `wait_until` / `wait_for_port` /
    `wait_for_line` / `wait_for_path`): at ``timeout=0`` one request attempt is
    still made (at least one), so an already-ready endpoint succeeds instead of
    failing before it was ever probed; that first attempt is bounded to a short,
    fixed event-loop tick (or a smaller caller-supplied ``interval``), never left
    uncapped. A **negative** ``timeout`` is rejected outright — raises
    `ValueError`, same as NaN — as is a non-positive ``interval``.
    """
    if not interval > 0:  # rejects NaN too (every NaN comparison is False)
        raise ValueError("interval must be a positive number of seconds")
    _check_timeout(timeout)
    if expected_status is None:
        expected_status = range(200, 300)  # default: any 2xx
    status_ok = _status_predicate(expected_status)
    request = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n").encode(
        "latin-1"
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last_exc: BaseException | None = None
    first_attempt = True
    while True:
        remaining = deadline - loop.time()
        if not first_attempt and remaining <= 0:
            raise WaitTimeout(
                f"http://{host}:{port}{path} not ready within {timeout}s",
                timeout_seconds=timeout,
                host=host,
                port=port,
                path=path,
            ) from last_exc
        # The first attempt is floored to a short positive tick (never the
        # non-positive ``remaining`` that ``timeout=0`` yields, which would trip
        # ``asyncio.wait_for``'s fast-cancel and reject an already-ready endpoint
        # before a request ever ran), and kept MONOTONE in ``timeout`` via
        # ``max(...)`` — the exact same reasoning as ``wait_for_port``'s first
        # connect window (see its docstring/comments). Every later attempt is
        # bounded by the real ``remaining`` (kept positive by the guard above).
        if first_attempt:
            attempt_timeout = max(remaining, min(interval, _ZERO_TIMEOUT_CONNECT_TICK))
        else:
            attempt_timeout = remaining
        first_attempt = False
        # Own the whole probe (connect + request + status read) as a task so a
        # deadline/cancellation racing its completion can be told apart from a
        # real timeout (K-030): on ``asyncio.wait_for``'s TimeoutError we check
        # whether the probe actually finished in that same tick and, if so, honor
        # the status it read instead of discarding a met condition — the same
        # race ``wait_until`` / ``wait_for_line`` / ``wait_for_port`` all resolve
        # in favor of the success.
        probe = asyncio.ensure_future(_probe_http(host, port, request))
        code: int | None = None
        try:
            code = await asyncio.wait_for(probe, timeout=attempt_timeout)
        except (OSError, _HttpProbeError, asyncio.TimeoutError) as exc:
            if (
                isinstance(exc, asyncio.TimeoutError)
                and probe.done()
                and not probe.cancelled()
                and probe.exception() is None
            ):
                code = probe.result()  # same-tick success: recover the status
            else:
                _discard_probe(probe)
                last_exc = exc
        except asyncio.CancelledError:
            _discard_probe(probe)
            raise
        if code is not None:
            if status_ok(code):
                return
            last_exc = _HttpProbeError(
                f"HTTP status {code} is not in the expected set", status=code
            )
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise WaitTimeout(
                f"http://{host}:{port}{path} not ready within {timeout}s",
                timeout_seconds=timeout,
                host=host,
                port=port,
                path=path,
            ) from last_exc
        # Don't overshoot the deadline by a full interval on the last retry.
        await asyncio.sleep(min(interval, remaining))


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

        # Named distinctly from the `match` variable above (not reused as the
        # def's own name): pyright otherwise infers `match`'s declared type
        # from this nested def (with its named `item` parameter) rather than
        # from the `Callable[[Any], bool]` annotation two lines up, then
        # rejects the `else` branch's `match = predicate` as incompatible
        # (reportRedeclaration / reportAssignmentType) — mypy has no such
        # issue with the original same-name form.
        def _contains(item: Any) -> bool:
            return needle in item

        match = _contains
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


# --- streaming batch (aoutput_as_completed) ----------------------------------


_Result = TypeVar("_Result")


def _resolve_concurrency(concurrency: int | None) -> int:
    """Shared ``concurrency`` handling for the streaming batch iterators:
    ``None`` means "as many at once as the machine has CPUs" (`os.cpu_count()`,
    floored at 1), matching the `output_all` family's default; a non-positive
    explicit value raises `ValueError` rather than being silently clamped to 1
    — the same contract the compiled batch verbs enforce.
    """
    if concurrency is None:
        return os.cpu_count() or 1
    if concurrency < 1:
        raise ValueError("concurrency must be a positive integer")
    return concurrency


async def _reap_slots(tasks: set[asyncio.Task[Any]]) -> None:
    """Cancel every still-running slot task and wait for all of them to reach a
    terminal state before returning, so each already-started child subtree is
    torn down (reaped) — no orphan survives an early ``break``, an exception
    mid-iteration, or the consuming task's own cancellation.

    Robust against a *fresh* cancellation landing while we drain: `asyncio.wait`
    waits for every task to settle and never re-raises a child's own exception
    into this frame, so the only thing that can interrupt the drain is a new
    cancellation of *this* await — which we absorb by re-cancelling and looping,
    never returning while a slot (and thus a subtree) is still live. Mirrors
    `_quiesce`'s discipline for the single-task case.
    """
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    while True:
        try:
            await asyncio.wait(tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            continue
        break


async def _stream_as_completed(
    commands: Sequence[Command],
    concurrency: int | None,
    run: Callable[[Command], Awaitable[_Result]],
) -> AsyncIterator[tuple[int, _Result | ProcessError]]:
    """Shared engine for `aoutput_as_completed` / `aoutput_as_completed_bytes`:
    drive ``commands`` through ``run`` (`Command.aoutput` or `.aoutput_bytes`)
    under a hard concurrency cap, yielding ``(original index, result)`` as each
    command finishes. See the public wrappers for the full contract.
    """
    limit = _resolve_concurrency(concurrency)
    items = list(commands)
    if not items:
        return
    semaphore = asyncio.Semaphore(limit)

    async def _slot(index: int, command: Command) -> tuple[int, _Result | ProcessError]:
        # Acquire BEFORE running: the semaphore caps how many `run(command)`
        # calls — i.e. how many live child subtrees — exist at once, never more
        # than ``limit``, no matter how many commands are queued behind them.
        async with semaphore:
            try:
                return index, await run(command)
            except ProcessError as error:
                # A spawn/I/O failure (or a `CancellationToken`-driven
                # `Cancelled`) is data for THIS slot, aligned with `output_all`
                # — never an exception that aborts the rest of the series. A
                # task cancellation is an `asyncio.CancelledError` (a
                # `BaseException`, not a `ProcessError`), so it is deliberately
                # NOT caught here: it propagates out to reap this slot's tree.
                return index, error

    pending: set[asyncio.Task[tuple[int, _Result | ProcessError]]] = {
        asyncio.ensure_future(_slot(index, command)) for index, command in enumerate(items)
    }
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                yield task.result()
    finally:
        # An early `break`, an exception, or cancellation of the consuming task
        # all unwind through here: tear down every slot still in flight so no
        # already-started subtree is left orphaned.
        await _reap_slots(pending)


def _aoutput_slot(command: Command) -> Awaitable[ProcessResult]:
    return command.aoutput()


def _aoutput_bytes_slot(command: Command) -> Awaitable[BytesResult]:
    return command.aoutput_bytes()


def aoutput_as_completed(
    commands: Sequence[Command],
    *,
    concurrency: int | None = None,
) -> AsyncIterator[tuple[int, ProcessResult | ProcessError]]:
    """Run ``commands`` with bounded concurrency, yielding each ``(original
    index, ProcessResult | ProcessError)`` pair **as that command finishes** —
    the streaming, pure-Python counterpart to the compiled `aoutput_all`.

    Where `aoutput_all` is *collect-all* (nothing is visible until the whole
    batch is done), this is an async iterator — ``async for index, result in
    aoutput_as_completed(commands, concurrency=8): ...`` — that hands each
    result back the moment its command completes, so a large fan-out reports
    progress and lets you react to early finishers instead of blocking on the
    slowest command in the batch.

    **Completion order, not input order.** Pairs arrive in the order their
    commands *finish*, which is generally not the input order; the ``index`` (a
    command's position in ``commands``) is what re-associates a result with the
    command that produced it. Every command is yielded exactly once, and the
    iterator is exhausted once all of them have been.

    **Errors are per-slot data, not a series-ending raise** (aligned with
    `output_all`): a command that fails to *spawn* — or hits an I/O error, or is
    cancelled through its own `CancellationToken` — yields its `ProcessError` in
    its own pair, and never short-circuits the others. A non-zero exit, a
    timeout, and a signal-kill are, as everywhere in this library, *data* on a
    `ProcessResult`, not errors at all.

    **Hard concurrency cap.** At most ``concurrency`` commands are ever live at
    once (an `asyncio.Semaphore` gates each `Command.aoutput()`), so fanning out
    hundreds of commands can't exhaust file descriptors or the process table —
    the same bound `aoutput_all` gives, held *while* streaming. ``concurrency``
    defaults to the CPU count (`os.cpu_count()`), matching the batch family; a
    non-positive value raises `ValueError` rather than being silently clamped.

    **No orphans on cancellation or early exit.** Cancelling the task consuming
    this iterator — or simply ``break``ing out of the ``async for`` early — tears
    down every command still in flight: each `Command.aoutput()` reaps its whole
    process subtree (grandchildren included) on cancellation, and this iterator
    drives that teardown for *all* live slots before it finishes unwinding. No
    started child is left orphaned, whether the batch ran to completion, was
    abandoned partway, or was cancelled outright.

    Built directly on `Command.aoutput()`; unlike the compiled `aoutput_all`
    family it takes no ``runner=`` double — the streaming layer is deliberately
    kept minimal, so for a hermetic batch that doesn't need streaming reach for
    `aoutput_all(..., runner=...)` instead. For raw ``bytes`` output (no UTF-8
    decode) use the twin `aoutput_as_completed_bytes`.
    """
    return _stream_as_completed(commands, concurrency, _aoutput_slot)


def aoutput_as_completed_bytes(
    commands: Sequence[Command],
    *,
    concurrency: int | None = None,
) -> AsyncIterator[tuple[int, BytesResult | ProcessError]]:
    """The raw-``bytes`` twin of `aoutput_as_completed`: the identical streaming,
    concurrency-cap, per-slot-error, and no-orphan-on-cancellation contract, but
    each finished command yields a `BytesResult` — its stdout/stderr as undecoded
    ``bytes``, for non-UTF-8 or binary output — in place of a text
    `ProcessResult`, mirroring how `aoutput_all_bytes` relates to `aoutput_all`.
    See `aoutput_as_completed` for the full contract.
    """
    return _stream_as_completed(commands, concurrency, _aoutput_bytes_slot)
