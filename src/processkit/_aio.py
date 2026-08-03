"""Pure-Python asyncio helpers layered on top of the compiled extension.

Three families live here:

- **Readiness helpers** (`wait_until` / `wait_for_line` / `wait_for_port` /
  `wait_for_http` / `wait_for_path` / `wait_for_named_pipe` /
  `wait_for_unix_socket`) compose on top of the compiled async surface (a
  `StdoutLines` iterator, a plain TCP connect, a hand-rolled HTTP GET, or an OS
  pipe/socket probe) rather than bridging the Rust
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
import ipaddress
import math
import os
import socket
import sys
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable, Container, Sequence
from pathlib import Path
from typing import Any, TypeVar, cast, overload

from ._processkit import (
    BytesResult,
    Command,
    ProcessError,
    ProcessGroup,
    ProcessGroupStats,
    ProcessResult,
    Unsupported,
)
from ._types import StrPath

__all__ = [
    "WaitTimeout",
    "aoutput_as_completed",
    "aoutput_as_completed_bytes",
    "sample_stats",
    "wait_for_http",
    "wait_for_line",
    "wait_for_named_pipe",
    "wait_for_path",
    "wait_for_port",
    "wait_for_unix_socket",
    "wait_until",
]


_ZERO_TIMEOUT_CONNECT_TICK = 0.05


class WaitTimeout(ProcessError, TimeoutError):
    """A readiness helper (`wait_until` / `wait_for_line` / `wait_for_port` /
    `wait_for_http` / `wait_for_path` / `wait_for_named_pipe` /
    `wait_for_unix_socket`) didn't succeed within its deadline.

    Also a builtin `TimeoutError`, so `except TimeoutError` catches it too —
    the same convention a run's own `.timeout()` uses (see `Timeout`). Always
    carries `timeout_seconds`; `wait_for_port` and `wait_for_http` additionally
    set `host` / `port` (and `wait_for_http` also `path`), while `wait_for_path`
    `wait_for_named_pipe`, and `wait_for_unix_socket` set `path` (all `None`
    for `wait_until` / `wait_for_line`, which have none of these).
    `wait_for_port` / `wait_for_http` / `wait_for_named_pipe` /
    `wait_for_unix_socket` also chain the last attempt's failure as `__cause__`
    (a connection error, or — for `wait_for_http` — the last unexpected status
    code).
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
    """Shared ``timeout`` validation for the readiness helpers: NaN and
    negative values are both rejected outright rather than silently accepted.
    ``timeout == 0`` is valid and means "evaluate exactly once, right now" —
    see each helper's docstring.
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
    any other marker file a daemon creates once ready are all typical uses. For
    a Unix-domain socket that must actually accept connections, use
    `wait_for_unix_socket`; for a TCP port or an arbitrary predicate, see
    `wait_for_port` / `wait_until` instead (`wait_until(lambda: path.exists(),
    ...)` is exactly what this helper does, named for readability and given the
    same `WaitTimeout` discipline as its siblings).

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
_ProbeResult = TypeVar("_ProbeResult")


def _settle_probe(
    task: asyncio.Task[_ProbeResult], cleanup_result: Callable[[_ProbeResult], None]
) -> None:
    """Cancel or retrieve an abandoned probe and release a successful result."""
    if not task.done():
        task.cancel()
        task.add_done_callback(lambda done: _settle_probe(done, cleanup_result))
        return
    if task.cancelled() or task.exception() is not None:
        return
    cleanup_result(task.result())


def _validate_probe_retry(*, timeout: float, interval: float) -> None:
    if not interval > 0:  # rejects NaN too (every NaN comparison is False)
        raise ValueError("interval must be a positive number of seconds")
    _check_timeout(timeout)


async def _retry_probe(
    attempt: Callable[[], Awaitable[_ProbeResult]],
    evaluate: Callable[[_ProbeResult], BaseException | None | Awaitable[BaseException | None]],
    cleanup_result: Callable[[_ProbeResult], None],
    timeout_error: Callable[[], WaitTimeout],
    *,
    retry_exceptions: tuple[type[BaseException], ...],
    timeout: float,
    interval: float,
) -> None:
    """Drive one bounded readiness probe until it succeeds or its deadline expires."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    last_exc: BaseException | None = None
    first_attempt = True
    while True:
        remaining = deadline - loop.time()
        if not first_attempt and remaining <= 0:
            raise timeout_error() from last_exc
        # The first attempt gets a short positive floor. This lets timeout=0
        # genuinely try once, while preserving monotonicity for tiny positive
        # timeouts and never leaving an OS connect/DNS operation unbounded.
        attempt_timeout = (
            max(remaining, min(interval, _ZERO_TIMEOUT_CONNECT_TICK))
            if first_attempt
            else remaining
        )
        first_attempt = False
        task = asyncio.ensure_future(attempt())
        result: _ProbeResult | None = None
        try:
            result = await asyncio.wait_for(task, timeout=attempt_timeout)
        except retry_exceptions as exc:
            if (
                isinstance(exc, asyncio.TimeoutError)
                and task.done()
                and not task.cancelled()
                and task.exception() is None
            ):
                # Resolve a deadline/completion race in favor of the readiness
                # condition that was actually met in that same event-loop tick.
                result = task.result()
            else:
                _settle_probe(task, cleanup_result)
                last_exc = exc
        except asyncio.CancelledError:
            _settle_probe(task, cleanup_result)
            raise
        if result is not None:
            evaluation = evaluate(result)
            rejection = await evaluation if isinstance(evaluation, Awaitable) else evaluation
            if rejection is None:
                return
            last_exc = rejection
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise timeout_error() from last_exc
        await asyncio.sleep(min(interval, remaining))


def _close_connection_now(connection: _Connection) -> None:
    _reader, writer = connection
    writer.close()


async def _accept_connection(connection: _Connection) -> BaseException | None:
    _reader, writer = connection
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return None


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
    _validate_probe_retry(timeout=timeout, interval=interval)

    def timeout_error() -> WaitTimeout:
        return WaitTimeout(
            f"port {host}:{port} not ready within {timeout}s",
            timeout_seconds=timeout,
            host=host,
            port=port,
        )

    await _retry_probe(
        lambda: asyncio.open_connection(host, port),
        _accept_connection,
        _close_connection_now,
        timeout_error,
        retry_exceptions=(OSError, asyncio.TimeoutError),
        timeout=timeout,
        interval=interval,
    )


_ERROR_SEM_TIMEOUT = 121
_ERROR_FILE_NOT_FOUND = 2
_ERROR_BAD_PATHNAME = 161
_NMPWAIT_NOWAIT = 1
_NamedPipeProbe = Callable[[str], bool]


# The platform split is on ``sys.platform`` (not ``os.name``) so that a type
# checker analyses only the branch for the platform it is run on — the
# Windows ``ctypes`` calls in the ``win32`` branch are invisible to mypy on
# Linux, and vice versa (same idiom as tests/_liveness.py). This has to be an
# if/else pair of full function definitions rather than an early-return
# fallthrough inside one function body: with ``warn_unreachable = true``
# (pyproject.toml), a statically-true ``sys.platform`` guard followed by a
# ``return`` makes mypy treat the remainder of the function as regular
# unreachable code (an error), not as an elided platform branch.
#
# The ``win32`` clause is excluded from coverage for the same reason: only one
# of the two definitions is ever imported on a given interpreter, so on the
# enforcing Linux leg this block is structurally unexecutable, and measuring it
# there would park 18 permanently missing statements and 7 never-taken branch
# exits in a denominator whose margin is thin (see `[tool.coverage.report]` in
# pyproject.toml). The pragma sits on the ``if`` because coverage then drops
# that clause and its body only: the ``else`` fallback below stays measured on
# the leg that runs it, and the Windows behavior itself stays covered by the
# `skipif(sys.platform != "win32")` tests in tests/test_readiness.py.
if sys.platform == "win32":  # pragma: no cover -- platform-exclusive branch
    import ctypes
    from ctypes import wintypes

    def _load_named_pipe_probe() -> _NamedPipeProbe | None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        wait_named_pipe_w: Any = kernel32.WaitNamedPipeW
        wait_named_pipe_w.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
        wait_named_pipe_w.restype = wintypes.BOOL

        def probe(name: str) -> bool:
            # Use WaitNamedPipeW for non-destructive pipe availability check.
            # This avoids consuming the server's pipe instance and correctly
            # rejects non-pipe paths.
            result = wait_named_pipe_w(name, _NMPWAIT_NOWAIT)
            if result:
                return True
            error = ctypes.get_last_error()
            if error == _ERROR_SEM_TIMEOUT:
                # Pipe exists but server is busy; this is readiness.
                return True
            # File not found or bad path means no pipe at this name.
            if error in (_ERROR_FILE_NOT_FOUND, _ERROR_BAD_PATHNAME):
                raise ctypes.WinError(error)
            # Unknown error: also raise.
            raise ctypes.WinError(error)

        return probe

else:

    def _load_named_pipe_probe() -> _NamedPipeProbe | None:
        return None


_named_pipe_probe = _load_named_pipe_probe()


async def wait_for_named_pipe(
    name: str,
    *,
    timeout: float,
    interval: float = 0.05,
) -> None:
    """Wait until a Windows named pipe is available or has a busy server.

    ``name`` is the full pipe path, such as ``r"\\\\.\\pipe\\my-service"``.
    The pipe's availability is checked with `WaitNamedPipeW`, a non-destructive
    operation that does not consume the pipe's instances. A pipe with a busy
    server (all instances occupied) is also readiness: it proves that the
    server exists. Other failures are retried every ``interval`` seconds until
    ``timeout`` elapses, then raised as the cause of `WaitTimeout`, whose
    ``path`` is ``name``.

    Platforms without the Windows named-pipe API raise `Unsupported`. At
    ``timeout=0`` one bounded attempt still runs; negative and NaN timeouts are
    rejected with `ValueError`.
    """
    named_pipe_probe = _named_pipe_probe
    if named_pipe_probe is None:
        exc = Unsupported("Windows named pipes are not supported on this platform")
        exc.operation = "wait_for_named_pipe"
        raise exc
    _validate_probe_retry(timeout=timeout, interval=interval)

    def timeout_error() -> WaitTimeout:
        return WaitTimeout(
            f"named pipe {name} not ready within {timeout}s",
            timeout_seconds=timeout,
            path=name,
        )

    await _retry_probe(
        lambda: asyncio.to_thread(named_pipe_probe, name),
        lambda _ready: None,
        lambda _ready: None,
        timeout_error,
        retry_exceptions=(OSError, asyncio.TimeoutError),
        timeout=timeout,
        interval=interval,
    )


async def wait_for_unix_socket(
    path: StrPath,
    *,
    timeout: float,
    interval: float = 0.05,
) -> None:
    """Wait until a Unix-domain socket at ``path`` accepts a connection.

    Unlike `wait_for_path`, this proves that the socket has started accepting
    connections, rather than only that its filesystem entry exists. Polls every
    ``interval`` seconds until a connection succeeds or ``timeout`` seconds
    elapse, in which case `WaitTimeout` (also a `TimeoutError`) is raised,
    carrying ``path`` and chained from the last connection failure.

    Platforms lacking Unix-domain-socket support — no ``socket.AF_UNIX`` or no
    ``asyncio.open_unix_connection`` (asyncio binds the latter only when the
    former existed at import) — raise `Unsupported` instead of silently
    downgrading to a filesystem-existence check. At ``timeout=0`` one bounded
    connection attempt still runs, so an already-ready socket succeeds; negative
    and NaN timeouts are rejected with `ValueError`.
    """
    # A platform supports this probe only if BOTH the AF_UNIX address family and
    # asyncio's Unix-socket connector exist. asyncio.streams binds
    # ``open_unix_connection`` once, at import time, gated on ``socket.AF_UNIX``;
    # that connector is the authoritative gate for the ``asyncio.open_unix_connection``
    # call below, and a bare ``socket.AF_UNIX`` check does not reliably reflect
    # the connector's availability (the connector's binding is fixed at import
    # and independent of the live ``socket.AF_UNIX`` attribute).
    if not hasattr(socket, "AF_UNIX") or not hasattr(asyncio, "open_unix_connection"):
        exc = Unsupported("Unix-domain sockets are not supported on this platform")
        exc.operation = "wait_for_unix_socket"
        raise exc
    _validate_probe_retry(timeout=timeout, interval=interval)

    def timeout_error() -> WaitTimeout:
        return WaitTimeout(
            f"unix socket {path!s} not ready within {timeout}s",
            timeout_seconds=timeout,
            path=path,
        )

    # Typeshed exposes this Unix-only asyncio API conditionally on
    # ``sys.platform``. The runtime capability check above is authoritative.
    open_unix_connection = cast(
        Callable[[StrPath], Awaitable[_Connection]],
        asyncio.open_unix_connection,  # type: ignore[attr-defined,unused-ignore]
    )
    await _retry_probe(
        lambda: open_unix_connection(path),
        _accept_connection,
        _close_connection_now,
        timeout_error,
        retry_exceptions=(OSError, asyncio.TimeoutError),
        timeout=timeout,
        interval=interval,
    )


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


def _format_host_header(host: str, port: int) -> str:
    """Render `wait_for_http`'s ``Host`` header value for ``host``/``port`` per
    RFC 9112/3986/6874: an IPv6 literal is bracketed (``Host: [::1]:8080``) and
    a scope-ID separator is percent-encoded (``[fe80::1%25eth0]:8080``), since
    a bare colon-separated literal would otherwise be indistinguishable from
    the header's own ``host:port`` separator; anything else (an IPv4 literal or
    a DNS name) is used as-is, unchanged from before this validation existed
    (``Host: 127.0.0.1:8080`` / ``Host: example.com:8080``). A caller who
    already passed a bracketed literal (``"[::1]"``) is not double-wrapped.
    """
    if host.startswith("[") and host.endswith("]"):
        literal = host[1:-1].replace("%25", "%")
        return f"[{literal.replace('%', '%25')}]:{port}"
    try:
        is_ipv6_literal = ipaddress.ip_address(host).version == 6
    except ValueError:
        is_ipv6_literal = False
    if is_ipv6_literal:
        literal = host.replace("%25", "%")
        return f"[{literal.replace('%', '%25')}]:{port}"
    return f"{host}:{port}"


def _http_connection_host(host: str) -> str:
    """Return the socket-layer form of an HTTP host literal.

    Brackets and RFC 6874's encoded scope separator belong to URI/header
    syntax, while ``asyncio.open_connection`` expects the raw address.
    """
    if host.startswith("[") != host.endswith("]"):
        raise ValueError("an IPv6 host must use either both brackets or neither")
    bracketed = host.startswith("[")
    if bracketed:
        host = host[1:-1]
    if bracketed or ":" in host:
        return host.replace("%25", "%")
    return host


# Every Latin-1 control character: C0 (0x00-0x1F), DEL (0x7F), and C1
# (0x80-0x9F). Any of these in `path` would corrupt `wait_for_http`'s
# hand-rolled, single-line request — and CR/LF specifically would let an
# untrusted `path` inject extra request/header lines into the request that
# follows.
_HTTP_FORBIDDEN_PATH_CHARS = frozenset(
    chr(c) for c in range(0x100) if unicodedata.category(chr(c)) == "Cc"
)


def _check_http_path(path: str) -> None:
    """Guard `wait_for_http`'s request-line construction against a ``path``
    that would corrupt it: reject whitespace and control characters (CR/LF
    included) with a `ValueError` up front, fail-fast, before any connection
    is attempted — the same discipline as this module's ``timeout``/
    ``interval`` validation.
    """
    for ch in path:
        # Keep non-Latin-1 characters on the existing encode-time ValueError
        # path below: only characters that could reach the wire belong here.
        if ord(ch) <= 0xFF and (ch in _HTTP_FORBIDDEN_PATH_CHARS or ch.isspace()):
            raise ValueError(
                f"path must not contain whitespace or control characters (found {ch!r} in {path!r})"
            )


def _build_http_request(host: str, port: int, path: str) -> bytes:
    """Validate ``host``/``path`` and render `wait_for_http`'s hand-rolled
    HTTP/1.1 request line as ``bytes``, fail-fast (before any connection is
    attempted): rejects a ``path`` with whitespace/control characters
    (`_check_http_path`), brackets an IPv6 literal ``host`` in the ``Host``
    header (`_format_host_header`), and turns a ``host``/``path`` character
    that can't be encoded as latin-1 into a `ValueError` instead of a raw
    `UnicodeEncodeError`.
    """
    _check_http_path(path)
    host_header = _format_host_header(host, port)
    request_text = f"GET {path} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n\r\n"
    try:
        return request_text.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise ValueError(
            f"host and path must be latin-1 encodable for an HTTP request line: {exc}"
        ) from exc


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

    ``host`` and ``path`` are validated up front, before any connection is
    attempted (fail-fast, not "after one retry cycle"): an IPv6 literal
    ``host`` may be raw or already bracketed (e.g. ``"::1"`` / ``"[::1]"``);
    brackets are removed for the socket connection and present exactly once in
    the ``Host`` header per RFC 9112/3986 (``Host: [::1]:8080``, never the
    ambiguous ``Host: ::1:8080``). An encoded IPv6 scope separator (``%25``)
    is decoded for the socket and encoded exactly once in the header;
    a ``path`` containing whitespace or a control character (including
    CR/LF — which could otherwise inject extra request/header lines from an
    untrusted ``path``) raises `ValueError`; and a ``host``/``path`` with a
    character that can't be encoded as latin-1 (required for the request
    line) raises `ValueError` instead of a raw `UnicodeEncodeError`.
    """
    _validate_probe_retry(timeout=timeout, interval=interval)
    if expected_status is None:
        expected_status = range(200, 300)  # default: any 2xx
    status_ok = _status_predicate(expected_status)
    connection_host = _http_connection_host(host)
    request = _build_http_request(host, port, path)

    def timeout_error() -> WaitTimeout:
        return WaitTimeout(
            f"http://{host}:{port}{path} not ready within {timeout}s",
            timeout_seconds=timeout,
            host=host,
            port=port,
            path=path,
        )

    async def evaluate_status(code: int) -> BaseException | None:
        if status_ok(code):
            return None
        return _HttpProbeError(f"HTTP status {code} is not in the expected set", status=code)

    await _retry_probe(
        lambda: _probe_http(connection_host, port, request),
        evaluate_status,
        lambda _code: None,
        timeout_error,
        retry_exceptions=(OSError, _HttpProbeError, asyncio.TimeoutError),
        timeout=timeout,
        interval=interval,
    )


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
    ``None`` means the process-available CPU count (respecting CPU affinity and
    cgroup quotas where Python exposes them through `os.process_cpu_count()`),
    with `os.cpu_count()` as the Python 3.10-3.12 fallback and ``4`` if neither
    can determine a count. This matches the compiled batch family's
    `available_parallelism()` default. A non-positive explicit value raises
    `ValueError` rather than being silently clamped to 1 — the same contract the
    compiled batch verbs enforce.
    """
    if concurrency is None:
        process_cpu_count = cast(
            Callable[[], int | None] | None, getattr(os, "process_cpu_count", None)
        )
        count = process_cpu_count() if process_cpu_count is not None else os.cpu_count()
        return count or 4
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
    defaults to the process-available CPU count (CPU affinity/cgroup-aware on
    Python 3.13+), falling back to `os.cpu_count()` and then ``4``; this matches
    the batch family. A non-positive value raises `ValueError` rather than being
    silently clamped.

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
    each finished command yields a `BytesResult` — raw-``bytes`` stdout for
    non-UTF-8 or binary output, while stderr stays decoded text — in place of a
    text `ProcessResult`, mirroring how `aoutput_all_bytes` relates to
    `aoutput_all`.
    With ``concurrency=None``, it uses the same process-available CPU-count
    default (and fallbacks) as every other batch entry point. See
    `aoutput_as_completed` for the full contract.
    """
    return _stream_as_completed(commands, concurrency, _aoutput_bytes_slot)
