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
    CliClient,
    Command,
    OutputTooLarge,
    ProcessError,
    ProcessRunner,
    RecordReplayRunner,
    Runner,
    ScriptedRunner,
    Signalled,
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


# --- Stage 2: interface ergonomics ------------------------------------------


@pytest.mark.parametrize("label", ["latin_1", "latin-1", "utf_8", "euc_jp", "utf_16", "UTF_8"])
def test_encoding_accepts_python_aliases(label: str) -> None:
    # Common Python codec spellings the WHATWG label table doesn't contain
    # verbatim must still resolve (no exception).
    Command("x").encoding(label)


def test_encoding_unknown_label_gives_guidance() -> None:
    with pytest.raises(ValueError, match="WHATWG"):
        Command("x").encoding("cp437")  # no encoding_rs equivalent


def test_arg_args_accept_path_like() -> None:
    p = pathlib.Path("sub/file")
    # arg()/args() and the constructor accept os.PathLike without a manual str().
    cmd = Command("tool").arg(p).args([p, "literal"])
    assert isinstance(cmd, Command)
    Command("tool", [p, "x"])
    # The path value is actually passed through to the child as an argument.
    echo = "import sys; print(sys.argv[1])"
    echoed = Command(PY, ["-c", echo, pathlib.Path("xyz") / "abc"]).output()
    assert "abc" in echoed.stdout


def test_repr_does_not_leak_argv() -> None:
    # repr() is emitted by logging (`%r`), f-strings, and tracebacks; it must not
    # render argv, so a secret passed as a flag can't leak through them. The
    # program name is safe to show; the full command line stays behind the crate's
    # explicit command_line() escape hatch.
    cmd = Command("login", ["--password", "hunter2-SECRET"])
    text = repr(cmd)
    assert "hunter2-SECRET" not in text
    assert "--password" not in text
    assert "login" in text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX exec-bit permission semantics")
def test_permission_denied_on_non_executable(tmp_path: pathlib.Path) -> None:
    script = tmp_path / "not_exec.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o644)  # readable but not executable
    with pytest.raises(PermissionError) as excinfo:  # PermissionDenied is a PermissionError
        Command(str(script)).run()
    assert isinstance(excinfo.value, ProcessError)


# --- Stage 3: interface stability -------------------------------------------


def _accepts_runner(runner: ProcessRunner) -> None:
    # The annotation is the test: if this type-checks for the calls below, the
    # concrete runners structurally satisfy the protocol.
    assert runner is not None


def test_runner_classes_satisfy_process_runner() -> None:
    _accepts_runner(Runner())  # static conformance (mypy) + runtime use
    _accepts_runner(ScriptedRunner())
    assert isinstance(Runner(), ProcessRunner)
    assert isinstance(ScriptedRunner(), ProcessRunner)


def test_record_replay_runner_satisfies_process_runner(tmp_path: pathlib.Path) -> None:
    rec = RecordReplayRunner.record(str(tmp_path / "c.json"))
    assert isinstance(rec, ProcessRunner)


def test_cli_client_is_not_a_process_runner() -> None:
    # CliClient verbs take per-call args (not a Command) and it has no start()/
    # astart() — so it is deliberately NOT a ProcessRunner.
    assert not isinstance(CliClient("git"), ProcessRunner)


# --- Whole-solution review: supervisor storm guard --------------------------


def test_supervisor_storm_pause_enables_guard() -> None:
    # With the failure-storm guard enabled (storm_pause set) + a low threshold, a
    # rapidly crash-looping command takes collective storm pauses (the field is no
    # longer permanently 0).
    out = Supervisor(
        Command(PY, ["-c", "import sys; sys.exit(1)"]),
        restart="always",
        max_restarts=30,
        backoff_initial=0.001,
        backoff_factor=1.0,
        jitter=False,
        storm_pause=0.01,
        failure_threshold=1.5,
        failure_decay=100.0,
    ).run()
    assert out.storm_pauses >= 1


def test_supervisor_storm_knobs_validate() -> None:
    base = Command(PY, ["-c", "pass"])
    with pytest.raises(ValueError):
        Supervisor(base, storm_pause=-1.0)
    with pytest.raises(ValueError):
        Supervisor(base, failure_threshold=0.0)
    with pytest.raises(ValueError):
        Supervisor(base, failure_decay=-1.0)


def test_supervisor_zero_failure_decay_is_accepted() -> None:
    # A zero half-life is a valid crate config (no history; every failure scores
    # 1.0) — the binding must not reject it.
    Supervisor(Command(PY, ["-c", "pass"]), restart="never", storm_pause=0.01, failure_decay=0.0)


# --- Whole-solution review: exception structured-field contracts -------------
# These fields are part of the public contract (documented + in the stub) but are
# set on the raised *instance*, so the static drift guard cannot see them. Pin
# them by actually raising the exception.


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal-kill semantics")
def test_signalled_carries_structured_fields() -> None:
    # A child that kills itself with a signal surfaces as `Signalled` carrying the
    # signal number plus the captured streams (not a generic NonZeroExit).
    killer = Command(PY, ["-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"])
    with pytest.raises(Signalled) as excinfo:
        killer.run()
    exc = excinfo.value
    assert exc.signal is not None and exc.signal > 0
    assert isinstance(exc.stdout, str) and isinstance(exc.stderr, str)
    assert exc.program


def test_output_too_large_carries_byte_fields() -> None:
    # The byte-cap overflow path carries `byte_limit`/`total_bytes` (the line-cap
    # path is covered elsewhere). Pins those two fields against a silent rename.
    flood = Command(PY, ["-c", "import sys; sys.stdout.write('x' * 100_000)"])
    with pytest.raises(OutputTooLarge) as excinfo:
        flood.output_limit(max_bytes=1024, on_overflow="error").run()
    exc = excinfo.value
    assert exc.byte_limit == 1024
    assert exc.total_bytes >= 1024
    assert exc.program
