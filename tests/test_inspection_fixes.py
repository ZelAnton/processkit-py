"""Regression tests for the code-inspection fixes.

Each test pins a specific bug found during the deep inspection so it cannot
silently regress.
"""

from __future__ import annotations

import asyncio
import contextlib
import pathlib
import socket
import sys

import pytest

from processkit import (
    Command,
    ProcessError,
    RecordReplayRunner,
    Supervisor,
    wait_for_port,
)

PY = sys.executable


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


# --- M1: a sync verb called from a stop_when predicate surfaces a clear error ---


def test_sync_verb_in_stop_when_surfaces_clear_error() -> None:
    # Calling a synchronous verb from inside the supervisor's stop_when predicate
    # used to re-enter the tokio runtime and PANIC ("Cannot start a runtime from
    # within a runtime"); the panic was swallowed into "do not stop", so the
    # predicate silently never fired. It must now surface a clear `ProcessError`.
    captured: list[BaseException] = []

    def hook(unraisable: object) -> None:
        exc = getattr(unraisable, "exc_value", None)
        if isinstance(exc, BaseException):
            captured.append(exc)

    old_hook = sys.unraisablehook
    sys.unraisablehook = hook
    try:
        Supervisor(
            Command(PY, ["-c", "import sys; sys.exit(1)"]),
            restart="always",
            max_restarts=1,
            jitter=False,
            backoff_initial=0.001,
            stop_when=lambda r: Command(PY, ["-c", "pass"]).probe(),  # a SYNC verb
        ).run()
    finally:
        sys.unraisablehook = old_hook

    assert captured, "the predicate's error should reach the unraisable hook"
    assert all(isinstance(e, ProcessError) for e in captured), (
        f"expected ProcessError, got {[type(e).__name__ for e in captured]}"
    )
    assert "async context" in str(captured[0]), str(captured[0])


# --- M2: backoff_factor is processed independently of backoff_initial ---


def test_backoff_factor_validated_without_backoff_initial() -> None:
    # backoff_factor used to be silently ignored unless backoff_initial was also
    # passed. It is now applied/validated independently, so an out-of-range factor
    # raises even on its own.
    with pytest.raises(ValueError):
        Supervisor(Command(PY, ["-c", "pass"]), backoff_factor=0.5)


def test_backoff_factor_alone_is_accepted() -> None:
    outcome = Supervisor(Command(PY, ["-c", "pass"]), restart="never", backoff_factor=3.0).run()
    assert outcome.final_result.is_success


# --- m3: a cassette miss carries the .program field ---


def test_cassette_miss_carries_program(tmp_path: pathlib.Path) -> None:
    cassette = str(tmp_path / "cassette.json")
    rec = RecordReplayRunner.record(cassette)
    rec.run(Command(PY, ["-c", "print('a')"]))
    rec.save()

    rep = RecordReplayRunner.replay(cassette)
    with pytest.raises(ProcessError) as excinfo:
        rep.run(Command(PY, ["-c", "print('DIFFERENT')"]))  # absent from the cassette
    assert getattr(excinfo.value, "program", None), "cassette miss should carry .program"


# --- wait_for_port: cancellation propagates cleanly (no leaked probe socket) ---


def test_wait_for_port_cancel_propagates() -> None:
    port = _free_port()  # nothing is listening -> the helper stays in its retry loop

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
        port = _free_port()
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
    port = _free_port()  # nothing listening -> the OSError path runs the cleanup

    async def scenario() -> None:
        task = asyncio.ensure_future(wait_for_port("127.0.0.1", port, timeout=10.0))
        await asyncio.sleep(0.1)  # let a couple of refused-connect retries happen
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert called, "wait_for_port should route cleanup through _close_pending_connection"
