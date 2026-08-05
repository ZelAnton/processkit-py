"""The `Command` surface — builder, run verbs, and configuration knobs (env,
output caps, encoding, stdout/stderr redirection, lifetime/privilege) exercised
by real subprocess runs against the host interpreter. A few async twins of sync
knobs (e.g. `aoutput_bytes`, `stdout("null")` + `astart`) live beside their sync
siblings here rather than in the async-focused files.

Using ``sys.executable`` keeps these portable across Windows / Linux / macOS
without assuming any system binary is present.
"""

from __future__ import annotations

import asyncio
import io
import json
import multiprocessing
import os
import pathlib
import pickle
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor

import pytest

import processkit
from processkit import (
    BytesResult,
    CancellationToken,
    Cancelled,
    CliClient,
    Command,
    Finished,
    IdleTimeout,
    InvalidJson,
    NonZeroExit,
    Outcome,
    OutputEvent,
    OutputTooLarge,
    PermissionDenied,
    Priority,
    ProcessError,
    ProcessNotFound,
    ProcessResult,
    RunProfile,
    Timeout,
    Unsupported,
)
from processkit.testing import RecordingRunner, Reply, ScriptedRunner

from ._liveness import wait_until
from .conftest import NO_SUCH_PROGRAM, PY


def _make_executable_command(directory: pathlib.Path, name: str, output: str) -> pathlib.Path:
    if os.name == "nt":
        path = directory / f"{name}.cmd"
        path.write_text(f"@echo off\r\necho {output}\r\n", encoding="utf-8")
        return path

    path = directory / name
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' {output!r}\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_output_captures_stdout_and_code() -> None:
    result = Command(PY, ["-c", "print('hello')"]).output()
    assert result.stdout.strip() == "hello"
    assert result.code == 0
    assert result.is_success
    assert not result.timed_out
    assert result.signal is None
    assert result.duration_seconds >= 0.0


def test_run_returns_trimmed_stdout() -> None:
    assert Command(PY, ["-c", "print('hi')"]).run() == "hi"


def test_command_run_json_parses_valid_json() -> None:
    value = Command(PY, ["-c", "import json; print(json.dumps({'ok': [1, True]}))"]).run_json()
    assert value == {"ok": [1, True]}


def test_command_arun_json_parses_valid_json() -> None:
    async def scenario() -> object:
        return await Command(PY, ["-c", "print('[1, 2, null]')"]).arun_json()

    assert asyncio.run(scenario()) == [1, 2, None]


def test_command_run_json_invalid_raises_typed_error() -> None:
    with pytest.raises(InvalidJson) as excinfo:
        Command(PY, ["-c", "print('not-json')"]).run_json()

    assert excinfo.value.program == PY
    # `run_json()` always attaches `.stdout` (unlike the streaming
    # `RunningProcess.stdout_json_lines()` case, where it is `None`).
    assert excinfo.value.stdout is not None
    assert "not-json" in excinfo.value.stdout
    assert not isinstance(excinfo.value, json.JSONDecodeError)


def test_command_arun_json_invalid_raises_typed_error() -> None:
    async def scenario() -> None:
        with pytest.raises(InvalidJson):
            await Command(PY, ["-c", "print('still-not-json')"]).arun_json()

    asyncio.run(scenario())


def test_command_run_json_requires_zero_exit() -> None:
    with pytest.raises(NonZeroExit):
        Command(PY, ["-c", "import sys; print('{}'); sys.exit(3)"]).run_json()


def test_combined_is_a_property_with_both_streams() -> None:
    code = "import sys; print('out'); print('err', file=sys.stderr)"
    result = Command(PY, ["-c", code]).output()
    # `combined` is a property (bare attribute, not a call): calling it would
    # `TypeError` on the returned str — pins the method->property change, which the
    # name-only drift guard cannot catch.
    combined = result.combined
    assert isinstance(combined, str)
    assert "out" in combined and "err" in combined


def test_output_nonzero_exit_is_data_not_error() -> None:
    result = Command(PY, ["-c", "import sys; sys.exit(3)"]).output()
    assert result.code == 3
    assert not result.is_success


def test_run_raises_on_nonzero_exit() -> None:
    with pytest.raises(NonZeroExit):
        Command(PY, ["-c", "import sys; sys.exit(3)"]).run()


def test_exit_code() -> None:
    assert Command(PY, ["-c", "import sys; sys.exit(7)"]).exit_code() == 7


def test_probe_true_and_false() -> None:
    assert Command(PY, ["-c", "import sys; sys.exit(0)"]).probe() is True
    assert Command(PY, ["-c", "import sys; sys.exit(1)"]).probe() is False


def test_missing_program_raises_process_not_found() -> None:
    with pytest.raises(ProcessNotFound):
        Command(NO_SUCH_PROGRAM).output()


def test_prefer_local_finds_program_before_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_dir = tmp_path / "local-bin"
    path_dir = tmp_path / "path-bin"
    local_dir.mkdir()
    path_dir.mkdir()
    _make_executable_command(local_dir, "pk-tool", "local")
    _make_executable_command(path_dir, "pk-tool", "path")
    monkeypatch.setenv("PATH", str(path_dir))

    assert Command("pk-tool").prefer_local(local_dir).run() == "local"


def test_prefer_local_accumulates_in_priority_order(tmp_path: pathlib.Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    _make_executable_command(first_dir, "pk-tool", "first")
    _make_executable_command(second_dir, "pk-tool", "second")

    output = Command("pk-tool").prefer_local(first_dir).prefer_local(second_dir).run()

    assert output == "first"


def test_prefer_local_does_not_affect_path_form_program(tmp_path: pathlib.Path) -> None:
    local_dir = tmp_path / "local-bin"
    explicit_dir = tmp_path / "explicit-bin"
    local_dir.mkdir()
    explicit_dir.mkdir()
    _make_executable_command(local_dir, "pk-tool", "local")
    explicit_program = _make_executable_command(explicit_dir, "pk-tool", "explicit")

    assert Command(explicit_program).prefer_local(local_dir).run() == "explicit"


def test_prefer_local_failure_diagnostics_include_preferred_dirs(
    tmp_path: pathlib.Path,
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()

    with pytest.raises(ProcessNotFound) as excinfo:
        Command(NO_SUCH_PROGRAM).prefer_local(first_dir).prefer_local(second_dir).output()

    searched = excinfo.value.searched
    assert searched is not None
    assert str(first_dir) in searched
    assert str(second_dir) in searched


# --- spawn-free program resolution: which() / resolve_program() (T-109) -------


def test_which_resolves_a_path_form_program() -> None:
    # `sys.executable` is an absolute path-form program, probed directly — a
    # portable success case with no assumption about any system binary.
    resolved = processkit.which(PY)
    assert os.path.isabs(resolved)
    assert pathlib.Path(resolved).samefile(PY)


def test_which_resolves_a_bare_name_on_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path_dir = tmp_path / "bin"
    path_dir.mkdir()
    tool = _make_executable_command(path_dir, "pk-tool", "hi")
    monkeypatch.setenv("PATH", str(path_dir))

    resolved = processkit.which("pk-tool")
    assert os.path.isabs(resolved)
    assert pathlib.Path(resolved).samefile(tool)


def test_which_missing_program_raises_process_not_found() -> None:
    with pytest.raises(ProcessNotFound):
        processkit.which(NO_SUCH_PROGRAM)


def test_which_matches_command_resolve_program(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `which(x)` is the module-level shim over `Command(x).resolve_program()` —
    # they must resolve the identical path.
    path_dir = tmp_path / "bin"
    path_dir.mkdir()
    _make_executable_command(path_dir, "pk-tool", "hi")
    monkeypatch.setenv("PATH", str(path_dir))

    assert processkit.which("pk-tool") == Command("pk-tool").resolve_program()


def test_resolve_program_returns_the_resolved_absolute_path() -> None:
    resolved = Command(PY).resolve_program()
    assert os.path.isabs(resolved)
    assert pathlib.Path(resolved).samefile(PY)


def test_resolve_program_finds_a_bare_name_on_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path_dir = tmp_path / "bin"
    path_dir.mkdir()
    tool = _make_executable_command(path_dir, "pk-tool", "hi")
    monkeypatch.setenv("PATH", str(path_dir))

    assert pathlib.Path(Command("pk-tool").resolve_program()).samefile(tool)


def test_resolve_program_honors_prefer_local(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_dir = tmp_path / "local-bin"
    path_dir = tmp_path / "path-bin"
    local_dir.mkdir()
    path_dir.mkdir()
    local_tool = _make_executable_command(local_dir, "pk-tool", "local")
    _make_executable_command(path_dir, "pk-tool", "path")
    monkeypatch.setenv("PATH", str(path_dir))

    # The preferred directory wins over PATH, exactly as it would at spawn.
    resolved = Command("pk-tool").prefer_local(local_dir).resolve_program()
    assert pathlib.Path(resolved).samefile(local_tool)


def test_resolve_program_honors_a_relocated_child_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # When the command relocates the child's PATH (here: env_clear() + an explicit
    # env("PATH", ...)), resolution runs against that *effective child* PATH — the
    # same one the spawn would search — not the parent's.
    tool_dir = tmp_path / "child-bin"
    empty_dir = tmp_path / "empty"
    tool_dir.mkdir()
    empty_dir.mkdir()
    tool = _make_executable_command(tool_dir, "pk-tool", "child")
    # Parent PATH holds only an empty directory — the bare name is not on it.
    monkeypatch.setenv("PATH", str(empty_dir))

    resolved = Command("pk-tool").env_clear().env("PATH", str(tool_dir)).resolve_program()
    assert pathlib.Path(resolved).samefile(tool)

    # Without the relocation the bare name is not found (the parent PATH has no
    # pk-tool) — proving the child env, not some ambient PATH, located it.
    with pytest.raises(ProcessNotFound):
        Command("pk-tool").resolve_program()


def test_resolve_program_missing_diagnostics_match_a_real_run(tmp_path: pathlib.Path) -> None:
    # The whole point of the preflight: a miss is the same ProcessNotFound a real
    # run of the same command would raise — down to the `searched` diagnostic.
    # Build ONE command, resolve it and run it, and compare the two failures.
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    command = Command(NO_SUCH_PROGRAM).prefer_local(first_dir).prefer_local(second_dir)

    with pytest.raises(ProcessNotFound) as preflight:
        command.resolve_program()
    with pytest.raises(ProcessNotFound) as real_run:
        command.output()

    assert preflight.value.searched is not None
    assert preflight.value.searched == real_run.value.searched
    assert str(first_dir) in preflight.value.searched
    assert str(second_dir) in preflight.value.searched


def test_resolve_program_has_no_async_twin() -> None:
    # The preflight is deliberately synchronous only (a few stats, no runtime), so
    # there is intentionally no `aresolve_program` — pin that so an accidental
    # async twin (or its removal from the no-twin decision) is caught.
    assert not hasattr(Command(PY), "aresolve_program")


def test_timeout_is_captured_by_output() -> None:
    result = Command(PY, ["-c", "import time; time.sleep(5)"]).timeout(0.3).output()
    assert result.timed_out
    assert result.code is None
    assert not result.is_success


def test_timeout_is_raised_by_run() -> None:
    with pytest.raises(Timeout):
        Command(PY, ["-c", "import time; time.sleep(5)"]).timeout(0.3).run()


def test_invalid_timeout_rejected() -> None:
    # Zero, negative, non-finite, and a value that overflows the underlying
    # Duration must all be rejected cleanly (never a Rust panic).
    for bad in (0.0, -1.0, float("inf"), float("nan"), 1e300):
        with pytest.raises(ValueError):
            Command(PY).timeout(bad)


def test_invalid_idle_timeout_rejected() -> None:
    # idle_timeout validates exactly like timeout (positive_duration): zero,
    # negative, non-finite, and overflow all raise ValueError — never a panic.
    for bad in (0.0, -1.0, float("inf"), float("nan"), 1e300):
        with pytest.raises(ValueError):
            Command(PY).idle_timeout(bad)


def test_idle_timeout_fires_on_a_silent_child() -> None:
    # A child that prints one line then goes silent past the idle window: the
    # streaming iterator raises the distinct IdleTimeout (carrying the configured
    # window), NOT StopAsyncIteration and NOT the wall-clock Timeout, and the
    # child is killed by the binding's watchdog.
    code = "import time; print('hi', flush=True); time.sleep(30)"

    async def scenario() -> tuple[list[str], float]:
        proc = Command(PY, ["-c", code]).idle_timeout(0.5).start()
        seen: list[str] = []
        async with proc:
            async for event in proc.output_events():
                seen.append(event.text)
        return seen, 0.0  # unreachable: the loop raises before returning

    with pytest.raises(IdleTimeout) as excinfo:
        asyncio.run(scenario())
    # A distinct signal — not a wall-clock Timeout — carrying the window it fired on.
    assert not isinstance(excinfo.value, Timeout)
    assert excinfo.value.idle_timeout_seconds == pytest.approx(0.5)


def test_idle_timeout_does_not_fire_while_output_keeps_flowing() -> None:
    # A child emitting a line every 0.2s under a 1.0s idle window never trips it:
    # each line resets the clock, so the stream ends cleanly (no spurious kill).
    code = "import time\nfor i in range(4):\n print(i, flush=True); time.sleep(0.2)\n"

    async def scenario() -> list[str]:
        proc = Command(PY, ["-c", code]).idle_timeout(1.0).start()
        seen: list[str] = []
        async with proc:
            async for event in proc.output_events():
                seen.append(event.text)
        return seen

    assert asyncio.run(scenario()) == ["0", "1", "2", "3"]


def test_idle_timeout_beats_a_larger_wall_clock_timeout() -> None:
    # When both thresholds are set and the child goes silent, the *shorter* idle
    # window wins: with idle_timeout(0.5) < timeout(30) the idle watchdog fires
    # first and surfaces as IdleTimeout, not the wall-clock Timeout. (The two
    # compose; whichever threshold the run reaches first tears it down, and they
    # stay distinguishable by exception type.)
    code = "import time; print('hi', flush=True); time.sleep(30)"

    async def scenario() -> None:
        proc = Command(PY, ["-c", code]).timeout(30).idle_timeout(0.5).start()
        async with proc:
            async for _event in proc.output_events():
                pass

    with pytest.raises(IdleTimeout):
        asyncio.run(scenario())


def test_idle_timeout_with_stdout_file_is_diagnosed_not_silently_ignored(
    tmp_path: pathlib.Path,
) -> None:
    # K-043: idle monitoring rides the streaming verbs, which the crate gates on
    # a piped stdout. Combined with stdout_file (stdout not piped), the streaming
    # setup raises the documented "not piped" ProcessError before any line is
    # read — so idle_timeout + a redirected stdout surfaces loudly there, it is
    # never a silent no-op. (stderr_file leaves stdout piped and is exercised by
    # test_idle_timeout_watches_stdout_when_only_stderr_is_redirected.)
    path = tmp_path / "out.log"
    code = "import time; print('to file', flush=True); time.sleep(30)"

    async def scenario() -> None:
        proc = Command(PY, ["-c", code]).stdout_file(path).idle_timeout(0.5).start()
        async with proc:
            async for _line in proc.stdout_lines():
                pass

    with pytest.raises(ProcessError, match="not piped"):
        asyncio.run(scenario())


def test_idle_timeout_watches_stdout_when_only_stderr_is_redirected(
    tmp_path: pathlib.Path,
) -> None:
    # The K-043 asymmetry: stderr_file leaves stdout piped, so the streaming
    # verbs keep working and idle monitoring watches the (still-piped) stdout
    # channel. A child that writes one stdout line then goes silent trips the
    # idle window normally.
    path = tmp_path / "err.log"
    code = "import time; print('one', flush=True); time.sleep(30)"

    async def scenario() -> None:
        proc = Command(PY, ["-c", code]).stderr_file(path).idle_timeout(0.5).start()
        async with proc:
            async for _line in proc.stdout_lines():
                pass

    with pytest.raises(IdleTimeout):
        asyncio.run(scenario())


def test_idle_timeout_survives_builder_chaining() -> None:
    # idle_timeout is a binding-only field the crate can't carry, so every
    # builder threads it through `rewrap`. Set it first, then chain several more
    # builders, and it must still fire — proving no builder drops it.
    code = "import time; print('hi', flush=True); time.sleep(30)"

    async def scenario() -> None:
        proc = (
            Command(PY)
            .idle_timeout(0.5)
            .arg("-c")
            .arg(code)
            .env("PROCESSKIT_SMOKE", "1")
            .stdout("pipe")
            .start()
        )
        async with proc:
            async for _event in proc.output_events():
                pass

    with pytest.raises(IdleTimeout):
        asyncio.run(scenario())


def test_builder_chaining_returns_new_command() -> None:
    base = Command(PY)
    chained = base.arg("-c").arg("print(1 + 1)")
    assert chained.output().stdout.strip() == "2"
    # The original is untouched (builder methods return a new Command). The
    # redacted repr shows the arg COUNT (not values), still 0 on the base.
    assert "args: 0" in repr(base)


def test_arg0_configured_arg0_is_last_write_wins() -> None:
    cmd = Command(PY, ["-c", "print(1)"]).arg0("first").arg0("second")
    assert cmd.configured_arg0 == "second"
    # Unset by default, and unaffected on a sibling Command that never called
    # arg0() (builder methods return a new Command, see
    # test_builder_chaining_returns_new_command).
    assert Command(PY, ["-c", "print(1)"]).configured_arg0 is None


@pytest.mark.skipif(sys.platform == "win32", reason="arg0 is a Unix argv[0] override")
def test_arg0_overrides_argv0_observed_by_the_child() -> None:
    # `$0` in a shell script is literally the delivered argv[0] -- the
    # standard way a multicall binary/login shell (`-bash`) convention is
    # tested. `program()` (`/bin/sh`) stays the executable actually looked up
    # and launched; only the argument vector the child observes changes.
    out = Command("/bin/sh", ["-c", 'echo "$0"']).arg0("login-shell-mode").run()
    assert out.strip() == "login-shell-mode"


@pytest.mark.skipif(sys.platform != "win32", reason="arg0 is Unix-only")
def test_arg0_unsupported_on_windows() -> None:
    # Never silently skipped: on a non-Unix platform the run raises
    # `Unsupported` rather than silently passing the executable name instead.
    # `configured_arg0` stays observable even though the run itself fails.
    cmd = Command(PY, ["-c", "print('x')"]).arg0("multicall-mode")
    assert cmd.configured_arg0 == "multicall-mode"
    with pytest.raises(Unsupported) as excinfo:
        cmd.run()
    assert excinfo.value.operation


def test_cwd_is_applied() -> None:
    result = Command(PY, ["-c", "import os; print(os.getcwd())"]).cwd(os.getcwd()).output()
    assert os.path.realpath(result.stdout.strip()) == os.path.realpath(os.getcwd())


def test_accepts_pathlike_program_and_cwd(tmp_path: pathlib.Path) -> None:
    # A pathlib.Path (os.PathLike) is accepted for both program and cwd, not
    # just str — matching Python's subprocess conventions.
    result = (
        Command(pathlib.Path(PY), ["-c", "import os; print(os.getcwd())"]).cwd(tmp_path).output()
    )
    assert os.path.realpath(result.stdout.strip()) == os.path.realpath(str(tmp_path))


def test_env_is_applied() -> None:
    code = "import os; print(os.environ.get('PROCESSKIT_TEST', 'unset'))"
    result = Command(PY, ["-c", code]).env("PROCESSKIT_TEST", "applied").output()
    assert result.stdout.strip() == "applied"


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT-to-self delivery differs on Windows")
def test_sync_run_is_interruptible() -> None:
    # A blocked sync run must honour Ctrl+C: fire SIGINT from a helper thread
    # while the main thread blocks in run(), and confirm it raises promptly
    # instead of waiting out the 30s child.
    import signal
    import threading
    import time

    def fire_sigint() -> None:
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGINT)

    firer = threading.Thread(target=fire_sigint)
    firer.start()
    started = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            Command(PY, ["-c", "import time; time.sleep(30)"]).run()
    finally:
        firer.join()
    assert time.monotonic() - started < 10.0


# --- environment control ----------------------------------------------------


def test_envs_sets_multiple() -> None:
    out = (
        Command(PY, ["-c", "import os; print(os.environ['A'], os.environ['B'])"])
        .envs({"A": "1", "B": "2"})
        .run()
    )
    assert out == "1 2"


def test_env_remove_drops_inherited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PK_REMOVE_ME", "parent")
    out = (
        Command(PY, ["-c", "import os; print(os.environ.get('PK_REMOVE_ME', 'GONE'))"])
        .env_remove("PK_REMOVE_ME")
        .run()
    )
    assert out == "GONE"


def test_env_clear_starts_from_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PK_CLEAR_MARKER", "parent")
    cmd = Command(
        PY, ["-c", "import os; print(os.environ.get('PK_CLEAR_MARKER', 'GONE'))"]
    ).env_clear()
    # The interpreter needs SystemRoot to spawn on Windows; re-add just that
    # (env var names are case-insensitive on Windows).
    if sys.platform == "win32":
        cmd = cmd.env("SYSTEMROOT", os.environ.get("SYSTEMROOT", r"C:\Windows"))
    assert cmd.run() == "GONE"


def test_inherit_env_filters_to_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PK_KEEP", "kept")
    monkeypatch.setenv("PK_DROP", "dropped")
    code = "import os; print(os.environ.get('PK_KEEP', '-'), os.environ.get('PK_DROP', '-'))"
    cmd = Command(PY, ["-c", code]).env_clear().inherit_env(["PK_KEEP"])
    if sys.platform == "win32":
        cmd = cmd.env("SYSTEMROOT", os.environ.get("SYSTEMROOT", r"C:\Windows"))
    assert cmd.run() == "kept -"


# --- bytes output -----------------------------------------------------------


def test_output_bytes_returns_raw_bytes() -> None:
    code = "import sys; sys.stdout.buffer.write(bytes([0, 1, 2, 255]))"
    result = Command(PY, ["-c", code]).output_bytes()
    assert isinstance(result, BytesResult)
    assert result.stdout == bytes([0, 1, 2, 255])
    assert isinstance(result.stderr, str)
    assert result.code == 0
    assert result.is_success
    assert not result.truncated
    # The remaining BytesResult accessors are populated like ProcessResult's.
    assert not result.timed_out
    assert result.signal is None
    assert result.duration_seconds >= 0.0
    assert "python" in result.program.lower() or result.program == PY


def test_aoutput_bytes_returns_raw_bytes() -> None:
    async def scenario() -> BytesResult:
        code = "import sys; sys.stdout.buffer.write(b'\\x00\\xff')"
        return await Command(PY, ["-c", code]).aoutput_bytes()

    result = asyncio.run(scenario())
    assert result.stdout == b"\x00\xff"


# --- output caps ------------------------------------------------------------


def test_output_limit_error_raises_output_too_large() -> None:
    code = "import sys\nfor i in range(1000):\n    print(i)"
    with pytest.raises(OutputTooLarge) as excinfo:
        Command(PY, ["-c", code]).output_limit(max_lines=10, on_overflow="error").run()
    assert excinfo.value.max_lines == 10
    assert excinfo.value.total_lines >= 1000


def test_output_limit_truncate_marks_truncated() -> None:
    code = "import sys\nfor i in range(1000):\n    print('x' * 80)"
    result = Command(PY, ["-c", code]).output_limit(max_lines=10).output()
    assert result.is_success
    assert result.truncated


def test_output_limit_drop_newest_keeps_earliest_lines() -> None:
    # The default (drop_oldest) keeps the LATEST max_lines as new ones arrive;
    # drop_newest is the opposite — it keeps the EARLIEST lines and discards
    # anything past the cap. Previously untested (only drop_oldest/error had
    # coverage). Distinguishable content (line numbers) proves which end won.
    code = "import sys\nfor i in range(20):\n    print(i)"
    result = Command(PY, ["-c", code]).output_limit(max_lines=5, on_overflow="drop_newest").output()
    assert result.is_success
    assert result.truncated
    assert result.stdout.split() == ["0", "1", "2", "3", "4"]


def test_output_bytes_truncated_reflects_stderr_cap() -> None:
    # A `max_lines` cap can only truncate the line-pumped stderr — raw stdout
    # bytes have no line count, so a *line* cap never bounds them (a `max_bytes`
    # cap does now, since processkit 2.1.0 — see
    # `test_output_bytes_byte_cap_drop_truncates_and_bounds_stdout`). Here the
    # breach is a stderr line-cap overflow, and that is what sets `truncated`.
    code = "import sys\nfor i in range(1000):\n    sys.stderr.write('x' * 80 + chr(10))"
    result = Command(PY, ["-c", code]).output_limit(max_lines=10).output_bytes()
    assert result.is_success
    assert result.truncated


def test_output_bytes_byte_cap_error_raises_output_too_large() -> None:
    # processkit 2.1.0 behavior change: a `max_bytes` ceiling now bounds the raw
    # stdout of `output_bytes()` too (not just line-pumped stderr). Under
    # `on_overflow="error"` an over-cap flood raises `OutputTooLarge` with
    # `max_lines=None` (raw bytes have no line count) where it once returned all
    # bytes. Exercises the byte path specifically — the line path is covered by
    # `test_output_limit_error_raises_output_too_large` above.
    code = "import sys; sys.stdout.buffer.write(b'x' * 100_000)"
    with pytest.raises(OutputTooLarge) as excinfo:
        Command(PY, ["-c", code]).output_limit(max_bytes=1024, on_overflow="error").output_bytes()
    exc = excinfo.value
    assert exc.max_bytes == 1024
    assert exc.max_lines is None
    assert exc.total_bytes >= 1024


def test_output_bytes_byte_cap_drop_truncates_and_bounds_stdout() -> None:
    # The drop-mode half of the 2.1.0 byte-cap change: retained raw stdout bytes
    # are bounded to a head/tail and `BytesResult.truncated` is set (before 2.1.0
    # the raw bytes came back in full, untruncated).
    code = "import sys; sys.stdout.buffer.write(b'x' * 100_000)"
    result = Command(PY, ["-c", code]).output_limit(max_bytes=1024).output_bytes()
    assert result.is_success
    assert result.truncated
    # Bounded to the cap, not the full 100_000-byte flood.
    assert len(result.stdout) <= 1024


def test_byte_cap_unit_differs_between_error_and_drop_modes() -> None:
    # processkit 3.0.0 made the byte accounting deliberately asymmetric, and the
    # documentation (`docs/commands.md`, "What `max_bytes` actually counts") says
    # so per mode. Pinned here so a future core bump that quietly unifies the two
    # units is caught by this suite rather than by a user whose cap moved:
    #   - `on_overflow="error"`: the ceiling counts the RAW bytes read from the
    #     pipe, line terminators included, cumulatively over the run;
    #   - the drop modes: the cap bounds the RETAINED decoded line *content*,
    #     terminators excluded — unchanged from 2.x.
    # Four 4-byte lines = 16 bytes of content, 20 bytes on the wire, so a cap of
    # 18 sits exactly between the two units. Written through `stdout.buffer` so
    # the line endings are LF on every platform (`print()` would emit CRLF on
    # Windows and change the arithmetic).
    code = "import sys; sys.stdout.buffer.write(b'aaaa\\n' * 4)"

    # Raw count (20) is over the cap, so the fail-loud ceiling fires. Under the
    # old decoded-content accounting (16) it would not have.
    with pytest.raises(OutputTooLarge) as excinfo:
        Command(PY, ["-c", code]).output_limit(max_bytes=18, on_overflow="error").run()
    assert excinfo.value.max_bytes == 18
    assert excinfo.value.total_bytes == 20

    # Same output, same cap, drop mode: 16 retained content bytes fit, so nothing
    # is dropped. A drop mode that had switched to raw counting would truncate.
    result = Command(PY, ["-c", code]).output_limit(max_bytes=18).output()
    assert result.is_success
    assert not result.truncated
    assert result.stdout.split() == ["aaaa"] * 4


def test_output_limit_requires_a_cap() -> None:
    with pytest.raises(ValueError):
        Command(PY, ["-c", "pass"]).output_limit()


def test_output_limit_rejects_unknown_overflow() -> None:
    with pytest.raises(ValueError):
        # An invalid literal is the point of the test; mypy would flag it.
        Command(PY, ["-c", "pass"]).output_limit(max_bytes=10, on_overflow="nope")  # type: ignore[arg-type]


# --- success_codes ----------------------------------------------------------


def test_success_codes_replaces_success_set() -> None:
    # success_codes replaces the default {0}: [0, 3] accepts both.
    assert Command(PY, ["-c", "import sys; sys.exit(3)"]).success_codes([0, 3]).output().is_success
    assert Command(PY, ["-c", "print(1)"]).success_codes([0, 3]).run() == "1"
    # [3] alone makes exit 0 a failure.
    with pytest.raises(NonZeroExit):
        Command(PY, ["-c", "print(1)"]).success_codes([3]).run()
    # An empty sequence is rejected (it would accept nothing).
    with pytest.raises(ValueError):
        Command(PY, ["-c", "print(1)"]).success_codes([])


# --- retry (C2) --------------------------------------------------------------


def test_retry_on_timeout_recovers_and_returns_success(tmp_path: pathlib.Path) -> None:
    # "transient_or_timeout" retries a Command.timeout() expiry. The first
    # attempt sleeps past the (short) timeout; a counter file makes the
    # RETRIED attempt behave differently (exit 0 immediately) — since a retry
    # re-executes the whole command from scratch, this is the only way an
    # otherwise-identical replay can actually recover.
    counter = tmp_path / "n"
    code = (
        "import pathlib, sys, time\n"
        f"p = pathlib.Path({str(counter)!r})\n"
        "n = int(p.read_text()) if p.exists() else 0\n"
        "p.write_text(str(n + 1))\n"
        "if n == 0:\n"
        "    time.sleep(30)\n"
        "sys.exit(0)\n"
    )
    result = (
        Command(PY, ["-c", code])
        .timeout(3.0)
        .retry("transient_or_timeout", max_retries=1, initial_backoff=0.01, jitter=False)
        .run()
    )
    assert result == ""
    assert counter.read_text() == "2"  # first attempt timed out, second succeeded


def test_retry_transient_preset_excludes_timeout(tmp_path: pathlib.Path) -> None:
    # "transient" alone does NOT cover Error::Timeout (only spawn/IO
    # conditions) — the same scenario that recovers under
    # "transient_or_timeout" above must raise on the very first attempt here.
    counter = tmp_path / "n"
    code = (
        "import pathlib, sys, time\n"
        f"p = pathlib.Path({str(counter)!r})\n"
        "n = int(p.read_text()) if p.exists() else 0\n"
        "p.write_text(str(n + 1))\n"
        "if n == 0:\n"
        "    time.sleep(30)\n"
        "sys.exit(0)\n"
    )
    with pytest.raises(Timeout):
        Command(PY, ["-c", code]).timeout(3.0).retry(
            "transient", max_retries=5, initial_backoff=0.01, jitter=False
        ).run()
    assert counter.read_text() == "1"  # no retry happened


def test_retry_max_retries_zero_never_retries(tmp_path: pathlib.Path) -> None:
    counter = tmp_path / "n"
    code = (
        "import pathlib, sys, time\n"
        f"p = pathlib.Path({str(counter)!r})\n"
        "n = int(p.read_text()) if p.exists() else 0\n"
        "p.write_text(str(n + 1))\n"
        "time.sleep(30)\n"
    )
    with pytest.raises(Timeout):
        Command(PY, ["-c", code]).timeout(3.0).retry(
            "transient_or_timeout", max_retries=0, initial_backoff=0.01
        ).run()
    assert counter.read_text() == "1"


def test_retry_rejects_unknown_retry_if() -> None:
    with pytest.raises(ValueError, match="retry_if"):
        Command(PY, ["-c", "print(1)"]).retry("bogus")  # type: ignore[arg-type]


def test_retry_output_never_raises_so_never_retries(tmp_path: pathlib.Path) -> None:
    # retry is inert for the non-erroring output()/output_bytes() paths — they
    # never raise, so there's nothing for retry_if to classify; a single
    # attempt's result comes back as-is even with retry configured.
    counter = tmp_path / "n"
    code = (
        "import pathlib, sys\n"
        f"p = pathlib.Path({str(counter)!r})\n"
        "n = int(p.read_text()) if p.exists() else 0\n"
        "p.write_text(str(n + 1))\n"
        "sys.exit(1)\n"
    )
    result = (
        Command(PY, ["-c", code])
        .retry("transient_or_timeout", max_retries=5, initial_backoff=0.01)
        .output()
    )
    assert not result.is_success
    assert counter.read_text() == "1"  # exactly one attempt, no retry


def _client_always_timing_out() -> tuple[CliClient, RecordingRunner]:
    # A ScriptedRunner that always times out, wrapped in a RecordingRunner so
    # the test can count how many times the runner was actually invoked —
    # verifying retry_never() without spawning a single real process.
    scripted = ScriptedRunner()
    scripted.fallback(Reply.timeout())
    recorder = RecordingRunner.new(scripted)
    client = CliClient(
        "tool",
        runner=recorder,
        default_retry_if="transient_or_timeout",
        default_max_retries=2,
        default_initial_backoff=0.0,
        default_jitter=False,
    )
    return client, recorder


def test_retry_never_opts_out_of_a_configured_client_default_retry() -> None:
    # Without retry_never(): the client's default_retry_if applies, so the
    # runner is invoked once plus once per retry.
    client, recorder = _client_always_timing_out()
    with pytest.raises(Timeout):
        client.run(["--flag"])
    assert len(recorder.calls()) == 3  # 1 attempt + 2 retries

    # With retry_never(): an explicit per-command opt-out from that same
    # client-wide default — exactly one call reaches the runner.
    client, recorder = _client_always_timing_out()
    cmd = client.command(["--flag"]).retry_never()
    with pytest.raises(Timeout):
        client.run(cmd)
    assert recorder.only_call().program == "tool"


# --- encoding ---------------------------------------------------------------


def test_encoding_decodes_non_utf8() -> None:
    # 0xe9 is 'é' in latin-1 but invalid UTF-8.
    code = "import sys; sys.stdout.buffer.write(b'\\xe9\\n')"
    assert Command(PY, ["-c", code]).encoding("iso-8859-1").run() == "é"


def test_encoding_rejects_unknown_label() -> None:
    with pytest.raises(ValueError):
        Command(PY, ["-c", "pass"]).encoding("not-a-real-encoding")


@pytest.mark.parametrize("label", ["latin_1", "latin-1", "utf_8", "euc_jp", "utf_16", "UTF_8"])
def test_encoding_accepts_python_aliases(label: str) -> None:
    # Common Python codec spellings the WHATWG label table doesn't contain
    # verbatim must still resolve (no exception).
    Command("x").encoding(label)


def test_encoding_unknown_label_gives_guidance() -> None:
    with pytest.raises(ValueError, match="WHATWG"):
        Command("x").encoding("cp437")  # no encoding_rs equivalent


def test_per_stream_encoding_overrides() -> None:
    # stdout_encoding / stderr_encoding decode a single stream (vs the
    # whole-command encoding()). 0xe9 is 'é' in latin-1 but invalid UTF-8.
    out_code = "import sys; sys.stdout.buffer.write(b'\\xe9\\n')"
    assert Command(PY, ["-c", out_code]).stdout_encoding("iso-8859-1").run() == "é"
    err_code = "import sys; sys.stderr.buffer.write(b'\\xe9\\n')"
    result = Command(PY, ["-c", err_code]).stderr_encoding("iso-8859-1").output()
    assert "é" in result.stderr


# --- VT/ANSI sanitization ----------------------------------------------------


def test_sanitize_vt_cleans_separate_stdout_and_stderr_capture() -> None:
    code = (
        "import sys; "
        "sys.stdout.write('\\x1b[31mout\\x1b[0m\\n'); "
        "sys.stderr.write('\\x1b]0;title\\x07\\x1b[32merr\\x1b[0m\\n')"
    )
    result = Command(PY, ["-c", code]).sanitize_vt().output()
    assert result.stdout == "out"
    assert result.stderr == "err"


def test_sanitize_vt_output_bytes_keeps_stdout_raw_but_cleans_stderr() -> None:
    code = (
        "import sys; "
        "sys.stdout.buffer.write(b'\\x1b[31mOUT\\x1b[0m'); "
        "sys.stderr.buffer.write(b'\\x1b[32mERR\\x1b[0m')"
    )
    result = Command(PY, ["-c", code]).sanitize_vt().output_bytes()
    assert result.stdout == b"\x1b[31mOUT\x1b[0m"
    assert result.stderr == "ERR"


def test_per_stream_sanitize_vt_only_changes_its_capture() -> None:
    code = (
        "import sys; "
        "sys.stdout.write('\\x1b[31mout\\x1b[0m\\n'); "
        "sys.stderr.write('\\x1b[32merr\\x1b[0m\\n')"
    )
    stdout_clean = Command(PY, ["-c", code]).stdout_sanitize_vt().output()
    assert stdout_clean.stdout == "out"
    assert "\x1b[32m" in stdout_clean.stderr

    stderr_clean = Command(PY, ["-c", code]).stderr_sanitize_vt().output()
    assert "\x1b[31m" in stderr_clean.stdout
    assert stderr_clean.stderr == "err"


def test_sanitize_vt_runs_after_decode_and_line_splitting() -> None:
    code = "import sys; sys.stdout.buffer.write(b'\\x1b[31m\\xe9\\x1b[0m\\rnext\\n')"
    result = (
        Command(PY, ["-c", code])
        .stdout_encoding("iso-8859-1")
        .stdout_line_terminator("carriage_return")
        .stdout_sanitize_vt()
        .output()
    )
    assert result.stdout.splitlines() == ["é", "next"]


# --- stdout/stderr redirection ----------------------------------------------


def test_pty_merges_terminal_output_and_sets_initial_size() -> None:
    code = (
        "import os, sys; "
        "print(f'tty={int(os.isatty(0))}{int(os.isatty(1))}{int(os.isatty(2))}'); "
        'print(f\'size={os.environ.get("COLUMNS")}x{os.environ.get("LINES")}\'); '
        "print('from-stderr', file=sys.stderr)"
    )
    result = Command(PY, ["-c", code]).pty(cols=101, rows=37).output()

    assert "tty=111" in result.stdout
    assert "size=101x37" in result.stdout
    assert "from-stderr" in result.stdout
    assert result.stderr == ""


def test_pty_size_requires_a_positive_pair() -> None:
    with pytest.raises(ValueError, match="provided together"):
        Command(PY).pty(cols=80)
    with pytest.raises(ValueError, match="provided together"):
        Command(PY).pty(rows=24)
    with pytest.raises(ValueError, match="positive"):
        Command(PY).pty(cols=0, rows=24)


def test_pty_rejects_conflicting_stdio_builders(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "redirect.txt"
    with pytest.raises(ValueError, match=r"pty\(\) cannot be combined"):
        Command(PY).inherit_stdin().pty()
    with pytest.raises(ValueError, match=r"pty\(\) cannot be combined"):
        Command(PY).pty().inherit_stdin()
    with pytest.raises(ValueError, match=r"pty\(\) cannot be combined"):
        Command(PY).stdout_file(target).pty()
    with pytest.raises(ValueError, match=r"pty\(\) cannot be combined"):
        Command(PY).pty().stderr_file(target)
    with pytest.raises(ValueError, match=r"pty\(\) cannot be combined"):
        Command(PY).stdout("inherit").pty()
    with pytest.raises(ValueError, match=r"pty\(\) cannot be combined"):
        Command(PY).pty().stderr("null")


def test_pty_conflict_can_be_cleared_by_restoring_a_pipe(tmp_path: pathlib.Path) -> None:
    result = (
        Command(PY, ["-c", "print('pty-ok')"])
        .stdout_file(tmp_path / "unused.txt")
        .stdout("pipe")
        .pty()
        .output()
    )
    assert "pty-ok" in result.stdout


@pytest.mark.parametrize("mode", ["piped", "PIPE", "Piped"])
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("pty_first", [False, True])
def test_pty_accepts_every_piped_stdio_spelling(mode: str, stream: str, pty_first: bool) -> None:
    cmd = Command(PY, ["-c", "print('pty-alias-ok')"])
    if pty_first:
        cmd = cmd.pty()
    cmd = getattr(cmd, stream)(mode)
    if not pty_first:
        cmd = cmd.pty()

    assert "pty-alias-ok" in cmd.output().stdout


def test_stdout_null_rejects_capture_verbs() -> None:
    # null/inherit are non-capturing: the one-shot capture verbs error clearly
    # rather than silently returning empty output.
    with pytest.raises(ProcessError, match="not piped"):
        Command(PY, ["-c", "print('hidden')"]).stdout("null").output()


def test_stdout_null_works_with_start_then_wait() -> None:
    async def scenario() -> int | None:
        proc = await Command(PY, ["-c", "print('hidden')"]).stdout("null").astart()
        return (await proc.aoutcome()).code

    assert asyncio.run(scenario()) == 0


def test_sanitize_vt_is_inert_for_null_and_inherited_stdout(
    capfd: pytest.CaptureFixture[str],
) -> None:
    raw_code = "import sys; sys.stdout.buffer.write(b'\\x1b[31mraw\\x1b[0m\\n')"
    with Command(PY, ["-c", raw_code]).stdout("null").sanitize_vt().start() as proc:
        assert proc.outcome().code == 0
    assert capfd.readouterr().out == ""

    with Command(PY, ["-c", raw_code]).stdout("inherit").sanitize_vt().start() as proc:
        assert proc.outcome().code == 0
    assert capfd.readouterr().out == "\x1b[31mraw\x1b[0m\n"


def test_stdout_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        # An invalid mode is the point of the test; mypy would flag the literal.
        Command(PY, ["-c", "pass"]).stdout("bogus")  # type: ignore[arg-type]


def test_stderr_null_works_with_start_then_wait() -> None:
    # stderr("null") is non-capturing (the twin of stdout("null")); start() then
    # aoutcome() still runs the child cleanly with stderr discarded.
    async def scenario() -> int | None:
        cmd = Command(PY, ["-c", "import sys; sys.stderr.write('x')"]).stderr("null")
        proc = await cmd.astart()
        return (await proc.aoutcome()).code

    assert asyncio.run(scenario()) == 0


# --- file-redirect sinks: stdout_file / stderr_file (T-140) ------------------
#
# `stdout_file`/`stderr_file` send a stream straight to a file at spawn time, with
# no parent-side pump/capture. A stdout redirect therefore has no pipe to read, so
# the capture verbs reject it — these tests drive such a command through the
# discard path (`start()` + `outcome()`), the same non-capturing path
# `test_stdout_null_works_with_start_then_wait` uses. A *stderr* redirect leaves
# stdout piped, so `output()` keeps working there (stderr just lands in the file).


def test_stdout_file_writes_child_output_to_the_file(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "out.log"
    cmd = Command(PY, ["-c", "print('to-file')"]).stdout_file(path)
    with cmd.start() as proc:
        outcome = proc.outcome()
    assert outcome.code == 0
    # The child wrote directly to the file — no parent capture involved.
    assert path.read_text(encoding="utf-8").strip() == "to-file"


def test_stdout_sanitize_vt_is_inert_for_direct_file_redirect(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "raw-vt.log"
    code = "import sys; sys.stdout.buffer.write(b'\\x1b[36mraw\\x1b[0m\\n')"
    cmd = Command(PY, ["-c", code]).stdout_file(path).stdout_sanitize_vt()
    with cmd.start() as proc:
        outcome = proc.outcome()
    assert outcome.code == 0
    assert path.read_bytes() == b"\x1b[36mraw\x1b[0m\n"


def test_stdout_file_truncate_overwrites_on_each_spawn(tmp_path: pathlib.Path) -> None:
    # The default (truncate) recreates/truncates the file on every spawn, so a
    # pre-existing file's content is gone and a re-run of the same built command
    # does not accumulate.
    path = tmp_path / "out.log"
    path.write_text("STALE-PREEXISTING\n", encoding="utf-8")
    cmd = Command(PY, ["-c", "print('fresh')"]).stdout_file(path)
    for _ in range(2):
        with cmd.start() as proc:
            proc.outcome()
    text = path.read_text(encoding="utf-8")
    assert "STALE" not in text  # the pre-existing content was truncated away
    assert text.strip() == "fresh"  # a second spawn truncated too, not doubled


def test_stdout_file_append_preserves_previous_content(tmp_path: pathlib.Path) -> None:
    # append mode creates-or-appends, never truncating — the shared-log mode for
    # Supervisor incarnations / retries: a pre-seeded file is kept and successive
    # spawns of the same command add to it with no separator.
    path = tmp_path / "shared.log"
    path.write_text("preamble\n", encoding="utf-8")
    cmd = Command(PY, ["-c", "print('run')"]).stdout_file(path, append=True)
    for _ in range(2):  # simulate two incarnations writing to one log
        with cmd.start() as proc:
            proc.outcome()
    assert path.read_text(encoding="utf-8").splitlines() == ["preamble", "run", "run"]


def test_stdout_file_rejects_capture_verbs(tmp_path: pathlib.Path) -> None:
    # A redirected stdout has no pipe, so the one-shot capture verbs raise the
    # documented "not piped" ProcessError (the same clear failure as stdout("null"))
    # rather than returning silently-empty output.
    path = tmp_path / "out.log"
    with pytest.raises(ProcessError, match="not piped"):
        Command(PY, ["-c", "print('x')"]).stdout_file(path).output()


def test_stdout_pipe_after_file_redirect_restores_capture(tmp_path: pathlib.Path) -> None:
    # A later stdout(mode) call clears the file redirect and restores the normal
    # stdio mode — the crate documents this reset, and the builder chain must keep
    # it. After stdout("pipe") the capture verbs work again and the file is never
    # touched (the redirect was cleared before spawn).
    path = tmp_path / "out.log"
    result = Command(PY, ["-c", "print('captured')"]).stdout_file(path).stdout("pipe").output()
    assert result.stdout.strip() == "captured"
    assert not path.exists()


def test_stderr_file_writes_child_stderr_to_the_file(tmp_path: pathlib.Path) -> None:
    # A stderr redirect leaves stdout piped, so output() still works: stdout is
    # captured as usual while stderr is diverted to the file (result.stderr empty).
    path = tmp_path / "err.log"
    code = "import sys; print('on-stdout'); sys.stderr.write('err-to-file\\n')"
    result = Command(PY, ["-c", code]).stderr_file(path).output()
    assert result.is_success
    assert result.stdout.strip() == "on-stdout"
    assert result.stderr == ""  # stderr went to the file, not the capture buffer
    assert path.read_text(encoding="utf-8").strip() == "err-to-file"


def test_stderr_file_truncate_overwrites_on_each_spawn(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "err.log"
    path.write_text("STALE\n", encoding="utf-8")
    code = "import sys; sys.stderr.write('fresh\\n')"
    Command(PY, ["-c", code]).stderr_file(path).output()
    text = path.read_text(encoding="utf-8")
    assert "STALE" not in text
    assert text.strip() == "fresh"


def test_stderr_file_append_preserves_previous_content(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "shared.log"
    path.write_text("preamble\n", encoding="utf-8")
    code = "import sys; sys.stderr.write('run\\n')"
    cmd = Command(PY, ["-c", code]).stderr_file(path, append=True)
    for _ in range(2):
        cmd.output()
    assert path.read_text(encoding="utf-8").splitlines() == ["preamble", "run", "run"]


def test_stderr_pipe_after_file_redirect_restores_normal_mode(tmp_path: pathlib.Path) -> None:
    # Mirror of the stdout reset: stderr(mode) after stderr_file clears the
    # redirect, so stderr is captured again and the file is never written.
    path = tmp_path / "err.log"
    code = "import sys; sys.stderr.write('back-to-pipe\\n')"
    result = Command(PY, ["-c", code]).stderr_file(path).stderr("pipe").output()
    assert "back-to-pipe" in result.stderr
    assert not path.exists()


# --- lifetime / redirect / privilege knobs ----------------------------------


def test_builder_knobs_chain_builds() -> None:
    # Every lifetime / redirect / privilege knob builds into a valid Command.
    cmd = (
        Command(PY, ["-c", "print('ok')"])
        .kill_on_parent_death()
        .create_no_window()
        .windows_graceful_ctrl_break()
        .timeout_grace(0.5)
        .timeout_signal("term")
        .uid(0)
        .gid(0)
        .groups([0])
        .setsid()
        .umask(0o022)
        .rlimit("no_file", 100, 200)
        .priority("normal")
    )
    assert isinstance(cmd, Command)
    # The cross-platform lifetime knobs actually run.
    assert "ok" in Command(PY, ["-c", "print('ok')"]).kill_on_parent_death().run()


def test_windows_graceful_ctrl_break_is_a_platform_honest_no_op() -> None:
    # Like `create_no_window`, this is a Windows-only opt-in that is a harmless
    # no-op elsewhere — never an `Unsupported` raise (unlike the POSIX-only
    # uid/gid/groups/setsid/umask knobs). The builder accepts the call, returns
    # a `Command`, and a run configured with it succeeds on every platform. We
    # do NOT try to exercise a real CTRL_BREAK teardown here — that is a
    # processkit-core behavior, not a property of this binding; we only pin that
    # the opt-in builds and does not derail an ordinary run.
    cmd = Command(PY, ["-c", "print('ok')"]).windows_graceful_ctrl_break()
    assert isinstance(cmd, Command)
    assert "ok" in cmd.run()


def test_kill_on_parent_death_scope_reports_a_valid_platform_scope() -> None:
    # `kill_on_parent_death_scope()` is a read-only capability query: it reports
    # the reach of `kill_on_parent_death()` on this platform as a stable string.
    # It is a staticmethod fixed at build time — it needs no prior
    # `kill_on_parent_death()` call and returns the same value whether read off
    # the class or an instance. We assert only that it returns a valid value from
    # the documented set (not a specific one): the concrete scope is a
    # processkit-core, per-platform decision — Windows reports whole-tree, Linux
    # direct-child-only, macOS/BSD unsupported — so pinning one here would make
    # the test host-specific for no gain.
    valid = {"whole_tree", "direct_child_only", "unsupported"}

    from_class = Command.kill_on_parent_death_scope()
    assert isinstance(from_class, str)
    assert from_class in valid, f"unexpected parent-death scope: {from_class!r}"

    # Same answer off an instance, and unaffected by whether the hardening was
    # opted into on that instance (it is a platform capability, not a per-command
    # flag).
    cmd = Command(PY, ["-c", "print('ok')"])
    assert cmd.kill_on_parent_death_scope() == from_class
    assert cmd.kill_on_parent_death().kill_on_parent_death_scope() == from_class


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() != 0,
    reason="dropping privilege requires starting as root on POSIX (e.g. the Docker test harness)",
)
def test_privilege_drop_args_actually_drop_privilege() -> None:
    # `test_builder_knobs_chain_builds` only pins that `.uid()/.gid()/.groups()/
    # .setsid()` chain and build a valid Command (name-pinned); this actually
    # RUNS with them active and checks the child's real effective ids — only
    # possible when the calling process starts as root (this repo's `docker/`
    # harness runs as root by default; CI's native runners do not, hence the
    # euid guard above rather than a bare POSIX skip).
    code = "import json, os; print(json.dumps([os.getuid(), os.getgid(), os.getgroups()]))"
    # 65534 is the conventional nobody:nogroup uid/gid on Debian-family images
    # (this repo's Docker harness is `rust:1-bookworm`).
    out = Command(PY, ["-c", code]).uid(65534).gid(65534).groups([65534]).run()
    uid, gid, groups = json.loads(out)
    assert uid == 65534, "the child did not drop to the requested uid"
    assert gid == 65534, "the child did not drop to the requested gid"
    assert groups == [65534], (
        "the child's supplementary groups were not replaced with the requested set"
    )


@pytest.mark.skipif(
    sys.platform != "win32", reason="privilege-drop behavior is POSIX-specific / root-dependent"
)
def test_privilege_drop_unsupported_on_windows() -> None:
    # Privilege drops are never silently skipped: on Windows the run raises.
    with pytest.raises(Unsupported) as excinfo:
        Command(PY, ["-c", "print('x')"]).uid(0).run()
    # The structured `.operation` field names what wasn't supported.
    assert excinfo.value.operation


@pytest.mark.skipif(sys.platform == "win32", reason="umask is a POSIX file-mode creation mask")
def test_umask_actually_applies_to_child(tmp_path: pathlib.Path) -> None:
    # `.umask()` does not require privilege (unlike uid/gid/groups above) — it
    # actually runs and is checked here, not just chain-built. A restrictive
    # 0o077 mask should strip group/other bits off a file the child creates
    # with an otherwise-permissive 0o666 open mode.
    target = tmp_path / "umask_probe"
    path_repr = repr(str(target))
    code = f"import os; fd = os.open({path_repr}, os.O_CREAT | os.O_WRONLY, 0o666); os.close(fd)"
    Command(PY, ["-c", code]).umask(0o077).run()
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600, f"umask(0o077) should leave only owner rw bits, got {oct(mode)}"


@pytest.mark.skipif(
    sys.platform != "win32", reason="umask is POSIX-only; Windows has no such file-mode mask"
)
def test_umask_unsupported_on_windows() -> None:
    # Never silently skipped: on Windows the run raises `Unsupported`.
    with pytest.raises(Unsupported) as excinfo:
        Command(PY, ["-c", "print('x')"]).umask(0o022).run()
    assert excinfo.value.operation


def test_rlimit_rejects_unknown_resource_name() -> None:
    with pytest.raises(ValueError, match="rlimit"):
        Command(PY, ["-c", "print(1)"]).rlimit("bogus", 1, 1)  # type: ignore[arg-type]


@pytest.mark.skipif(
    sys.platform == "win32", reason="rlimit is a POSIX per-process setrlimit(2) limit"
)
def test_rlimit_actually_applies_to_child_and_accumulates_across_resources() -> None:
    # Different resources accumulate: both a `no_file` and a `cpu` limit
    # configured on the same command must both reach the child.
    resource = pytest.importorskip("resource")
    _, hard_nofile = resource.getrlimit(resource.RLIMIT_NOFILE)
    nofile = 256 if hard_nofile == resource.RLIM_INFINITY else min(256, hard_nofile)
    _, hard_cpu = resource.getrlimit(resource.RLIMIT_CPU)
    cpu = 30 if hard_cpu == resource.RLIM_INFINITY else min(30, hard_cpu)
    code = (
        "import json, resource; "
        "print(json.dumps([list(resource.getrlimit(resource.RLIMIT_NOFILE)), "
        "list(resource.getrlimit(resource.RLIMIT_CPU))]))"
    )
    out = Command(PY, ["-c", code]).rlimit("no_file", nofile, nofile).rlimit("cpu", cpu, cpu).run()
    nofile_seen, cpu_seen = json.loads(out)
    assert tuple(nofile_seen) == (nofile, nofile)
    assert tuple(cpu_seen) == (cpu, cpu)


@pytest.mark.skipif(
    sys.platform == "win32", reason="rlimit is a POSIX per-process setrlimit(2) limit"
)
def test_rlimit_same_resource_repeated_call_is_last_write_wins() -> None:
    resource = pytest.importorskip("resource")
    _, hard_nofile = resource.getrlimit(resource.RLIMIT_NOFILE)
    first = 200 if hard_nofile == resource.RLIM_INFINITY else min(200, hard_nofile)
    second = 100 if hard_nofile == resource.RLIM_INFINITY else min(100, hard_nofile)
    code = (
        "import json, resource; print(json.dumps(list(resource.getrlimit(resource.RLIMIT_NOFILE))))"
    )
    out = (
        Command(PY, ["-c", code])
        .rlimit("no_file", first, first)
        .rlimit("no_file", second, second)
        .run()
    )
    assert tuple(json.loads(out)) == (second, second), (
        "repeating rlimit() for the same resource should be last-write-wins"
    )


@pytest.mark.skipif(
    sys.platform == "win32", reason="soft>hard validation happens on the POSIX spawn path"
)
def test_rlimit_rejects_soft_greater_than_hard_before_spawn() -> None:
    # A predictable error before the child is ever spawned, not a panic and
    # not a silent correction to a valid pair.
    with pytest.raises(ProcessError, match="exceeds hard value"):
        Command(PY, ["-c", "print('never')"]).rlimit("no_file", 100, 50).run()


@pytest.mark.skipif(sys.platform != "win32", reason="rlimit is POSIX-only")
def test_rlimit_unsupported_on_windows() -> None:
    # Never silently skipped: on Windows the run raises `Unsupported`, even for
    # an otherwise-valid soft<=hard pair.
    with pytest.raises(Unsupported) as excinfo:
        Command(PY, ["-c", "print('x')"]).rlimit("no_file", 100, 100).run()
    assert excinfo.value.operation


def test_priority_rejects_unknown_preset() -> None:
    with pytest.raises(ValueError, match="priority"):
        Command(PY, ["-c", "print(1)"]).priority("bogus")  # type: ignore[arg-type]


@pytest.mark.skipif(
    sys.platform not in {"linux", "win32"}, reason="CPU affinity is Linux/Windows-only"
)
def test_cpu_affinity_applies_to_child() -> None:
    code = (
        "import sys\n"
        "if sys.platform == 'linux':\n"
        " import os\n"
        " cpus = sorted(os.sched_getaffinity(0))\n"
        "else:\n"
        " import ctypes\n"
        " k = ctypes.WinDLL('kernel32', use_last_error=True)\n"
        " k.GetCurrentProcess.restype = ctypes.c_void_p\n"
        " k.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, "
        "ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]\n"
        " k.GetProcessAffinityMask.restype = ctypes.c_int\n"
        " p = ctypes.c_size_t(); s = ctypes.c_size_t()\n"
        " ok = k.GetProcessAffinityMask(k.GetCurrentProcess(), ctypes.byref(p), ctypes.byref(s))\n"
        " assert ok\n"
        " cpus = [i for i in range(p.value.bit_length()) if p.value & (1 << i)]\n"
        "print(','.join(map(str, cpus)))\n"
    )
    cpu = int(Command(PY, ["-c", code]).run().split(",", maxsplit=1)[0])
    assert Command(PY, ["-c", code]).cpu_affinity([cpu, cpu]).run() == str(cpu)


@pytest.mark.skipif(
    sys.platform in {"linux", "win32"}, reason="CPU affinity is supported on Linux/Windows"
)
def test_cpu_affinity_is_unsupported_at_launch_elsewhere() -> None:
    with pytest.raises(Unsupported) as excinfo:
        Command(PY, ["-c", "print('x')"]).cpu_affinity([0]).run()
    assert "cpu_affinity" in excinfo.value.operation


@pytest.mark.parametrize(
    ("class_name", "level"),
    [("idle", None), ("best_effort", 0), ("best_effort", 7), ("real_time", 3)],
)
def test_io_priority_accepts_supported_classes(class_name: str, level: int | None) -> None:
    cmd = Command(PY, ["-c", "print('ok')"])
    configured = cmd.io_priority(class_name, level=level)  # type: ignore[arg-type]
    assert isinstance(configured, Command)


@pytest.mark.parametrize(
    ("class_name", "level"),
    [
        ("idle", 0),
        ("best_effort", None),
        ("real_time", None),
        ("best_effort", -1),
        ("best_effort", 8),
        ("best_effort", 2**100),
        ("bogus", 0),
    ],
)
def test_io_priority_rejects_invalid_class_level_pairs(class_name: str, level: int | None) -> None:
    with pytest.raises(ValueError, match="io_priority"):
        Command(PY).io_priority(class_name, level=level)  # type: ignore[arg-type]


def test_io_priority_rejects_bool_and_non_integer_levels() -> None:
    with pytest.raises(TypeError, match="not a bool"):
        Command(PY).io_priority("best_effort", level=True)
    with pytest.raises(TypeError, match="must be an integer"):
        Command(PY).io_priority("best_effort", level=1.5)  # type: ignore[arg-type]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="I/O priority is Linux-only")
def test_io_priority_applies_on_linux() -> None:
    assert Command(PY, ["-c", "print('ok')"]).io_priority("idle").run() == "ok"


@pytest.mark.skipif(sys.platform.startswith("linux"), reason="I/O priority is supported on Linux")
def test_io_priority_is_unsupported_at_launch_off_linux() -> None:
    with pytest.raises(Unsupported) as excinfo:
        Command(PY, ["-c", "print('x')"]).io_priority("idle").run()
    assert "io_priority" in excinfo.value.operation


def test_spawn_detached_child_survives_launcher_and_handle_drop(
    tmp_path: pathlib.Path,
) -> None:
    marker = tmp_path / "detached-alive"
    child_code = (
        "import pathlib, time; "
        "time.sleep(0.5); "
        f"pathlib.Path({str(marker)!r}).write_text('alive'); "
        "time.sleep(0.5)"
    )
    launcher_code = (
        "import sys; "
        "from processkit import Command; "
        f"child = Command(sys.executable, ['-c', {child_code!r}]).spawn_detached(); "
        "assert repr(child) == f'DetachedChild(pid={child.pid})'; "
        "print(child.pid, flush=True); "
        "del child"
    )

    launcher = subprocess.run(
        [PY, "-c", launcher_code],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert int(launcher.stdout.strip()) > 0
    assert wait_until(marker.is_file, 5), "detached child did not outlive its launcher"
    assert marker.read_text() == "alive"


@pytest.mark.parametrize(
    "configure",
    [
        lambda cmd: cmd.timeout(1),
        lambda cmd: cmd.idle_timeout(1),
        lambda cmd: cmd.pty(),
        lambda cmd: cmd.keep_stdin_open(),
    ],
)
def test_spawn_detached_rejects_owner_dependent_configuration(
    configure: Callable[[Command], Command],
) -> None:
    configured = configure(Command(PY, ["-c", "print('never')"]))
    with pytest.raises(Unsupported) as excinfo:
        configured.spawn_detached()
    assert "spawn_detached" in excinfo.value.operation


def test_spawn_detached_maps_missing_program() -> None:
    with pytest.raises(ProcessNotFound):
        Command(NO_SUCH_PROGRAM).spawn_detached()


# `nice(2)` value each preset maps to on Unix (see `Priority`'s doc comment in
# the crate); mirrored below for the Windows priority-class flags.
_POSIX_NICE = {
    "idle": 19,
    "below_normal": 10,
    "normal": 0,
    "above_normal": -5,
    "high": -10,
}


@pytest.mark.skipif(sys.platform == "win32", reason="os.getpriority is POSIX-only")
@pytest.mark.parametrize("preset", ["idle", "below_normal", "normal"])
def test_priority_actually_applies_nice_value_on_posix(preset: Priority) -> None:
    # These three never *lower* the nice value below the inherited default (0),
    # so no privilege is needed — real effect checked via the child's own
    # `os.getpriority()`, not just a chain-build.
    code = "import os; print(os.getpriority(os.PRIO_PROCESS, 0))"
    out = Command(PY, ["-c", code]).priority(preset).run()
    assert int(out) == _POSIX_NICE[preset]


@pytest.mark.skipif(sys.platform == "win32", reason="os.getpriority is POSIX-only")
@pytest.mark.parametrize("preset", ["above_normal", "high"])
def test_priority_negative_nice_applies_or_needs_privilege_on_posix(preset: Priority) -> None:
    # `above_normal`/`high` *lower* the nice value below the inherited default
    # (0), which an unprivileged POSIX user typically cannot do (needs
    # `CAP_SYS_NICE`/root) — real effect where the runner has the privilege
    # (e.g. this repo's root Docker harness), a clean `PermissionDenied`
    # (never a silent downgrade to a less-negative nice value) otherwise.
    code = "import os; print(os.getpriority(os.PRIO_PROCESS, 0))"
    cmd = Command(PY, ["-c", code]).priority(preset)
    try:
        out = cmd.run()
    except PermissionDenied:
        return
    assert int(out) == _POSIX_NICE[preset]


@pytest.mark.skipif(sys.platform != "win32", reason="priority class is a Windows-only concept")
@pytest.mark.parametrize("preset", ["idle", "below_normal", "normal", "above_normal", "high"])
def test_priority_actually_applies_priority_class_on_windows(preset: Priority) -> None:
    # No privilege is needed for any Windows priority class (unlike Unix's
    # negative-nice presets) — real effect checked via `GetPriorityClass`
    # through `ctypes` (no extra dependency needed for a one-off syscall).
    #
    # The `ctypes.windll` calls are wrapped in a static `if sys.platform ==
    # "win32":` block (mirroring tests/_liveness.py) so a type checker
    # analyses only the branch for the platform it is run on — `windll` is
    # invisible to mypy on Linux, hence the explicit `WinDLL(...)` construction
    # instead of the pre-bound `ctypes.windll` module attribute.
    priority_class = {
        "idle": 0x0000_0040,  # IDLE_PRIORITY_CLASS
        "below_normal": 0x0000_4000,  # BELOW_NORMAL_PRIORITY_CLASS
        "normal": 0x0000_0020,  # NORMAL_PRIORITY_CLASS
        "above_normal": 0x0000_8000,  # ABOVE_NORMAL_PRIORITY_CLASS
        "high": 0x0000_0080,  # HIGH_PRIORITY_CLASS
    }[preset]
    proc = Command(PY, ["-c", "import time; time.sleep(30)"]).priority(preset).start()
    try:
        assert proc.pid is not None
        if sys.platform == "win32":
            from ctypes import WinDLL

            _kernel32 = WinDLL("kernel32", use_last_error=True)
            # PROCESS_QUERY_LIMITED_INFORMATION — enough to read the priority class.
            handle = _kernel32.OpenProcess(0x1000, False, proc.pid)
            assert handle, "OpenProcess failed"
            try:
                got = _kernel32.GetPriorityClass(handle)
                assert got == priority_class, f"expected {priority_class:#x}, got {got:#x}"
            finally:
                _kernel32.CloseHandle(handle)
    finally:
        proc.kill()
        proc.outcome()


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM trapping is POSIX-specific")
def test_timeout_grace_delivers_signal_before_kill(tmp_path: pathlib.Path) -> None:
    # On timeout the configured signal is sent and the grace window is honored: a
    # child that traps SIGTERM runs its handler before any hard kill. A generous
    # timeout (not the tight 0.3s this used to use) gives interpreter startup
    # room to install the handler even on a loaded CI runner — otherwise SIGTERM
    # can race startup and land before the handler exists, flaking the test.
    marker = tmp_path / "got_term"
    code = (
        "import signal, sys, time\n"
        "def handler(*_):\n"
        f"    open({str(marker)!r}, 'w').write('x')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, handler)\n"
        "time.sleep(30)\n"
    )
    Command(PY, ["-c", code]).timeout(1.5).timeout_signal("term").timeout_grace(5.0).output()
    assert marker.is_file()  # the child received SIGTERM and ran its handler


# --- path-like args + repr redaction ----------------------------------------


def test_arg_args_accept_path_like() -> None:
    p = pathlib.Path("sub/file")
    # arg()/args() and the constructor accept os.PathLike without a manual str().
    # A mixed str/Path argv is spelled as a tuple, not a list, since `Args`
    # names concrete homogeneous list element types (see `_types.py`).
    cmd = Command("tool").arg(p).args((p, "literal"))
    assert isinstance(cmd, Command)
    Command("tool", (p, "x"))
    # The path value is actually passed through to the child as an argument.
    echo = "import sys; print(sys.argv[1])"
    echoed = Command(PY, ("-c", echo, pathlib.Path("xyz") / "abc")).output()
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


def test_program_and_arguments_getters() -> None:
    cmd = Command("login", ["--password", "hunter2-SECRET"])
    assert cmd.program == "login"
    assert cmd.arguments == ["--password", "hunter2-SECRET"]


def test_command_line_is_the_explicit_escape_hatch() -> None:
    # Unlike repr() (redacted), command_line() is opt-in and DOES include argv —
    # the escape hatch test_repr_does_not_leak_argv's docstring refers to.
    cmd = Command("login", ["--password", "hunter2-SECRET"])
    line = cmd.command_line()
    assert "login" in line
    assert "hunter2-SECRET" in line


# --- no_timeout / unchecked_in_pipe (C7 batch A) -----------------------------


def test_no_timeout_clears_a_prior_timeout() -> None:
    # no_timeout() clears an earlier timeout() — the last of the two wins, so a
    # command that would otherwise time out completes normally.
    result = Command(PY, ["-c", "import time; time.sleep(0.3)"]).timeout(0.05).no_timeout().output()
    assert result.is_success
    assert not result.timed_out


def test_timeout_opt_none_behaves_like_no_timeout() -> None:
    # timeout_opt(None) must CLEAR a prior timeout(), same as no_timeout() —
    # not merely "no call at all" (which would leave the earlier timeout()
    # in effect).
    result = (
        Command(PY, ["-c", "import time; time.sleep(0.3)"]).timeout(0.05).timeout_opt(None).output()
    )
    assert result.is_success
    assert not result.timed_out


def test_timeout_opt_with_a_value_behaves_like_timeout() -> None:
    result = Command(PY, ["-c", "import time; time.sleep(5)"]).timeout_opt(0.3).output()
    assert result.timed_out
    assert result.code is None
    assert not result.is_success


def test_timeout_opt_invalid_value_rejected() -> None:
    # Some(seconds) is validated the same way as timeout()'s own argument.
    for bad in (0.0, -1.0, float("inf"), float("nan"), 1e300):
        with pytest.raises(ValueError):
            Command(PY).timeout_opt(bad)


def test_unchecked_in_pipe_is_a_noop_outside_a_pipeline() -> None:
    # Outside a Pipeline, unchecked_in_pipe() has no effect: a single run's
    # status is already plain data, and success_codes/ensure_success are
    # unaffected either way.
    result = Command(PY, ["-c", "import sys; sys.exit(1)"]).unchecked_in_pipe().output()
    assert not result.is_success
    assert result.code == 1


def test_merge_stderr_in_pipe_is_a_noop_outside_a_pipeline() -> None:
    # Outside a Pipeline, merge_stderr_in_pipe() has no effect: stdout and
    # stderr are captured separately exactly as if it had never been called.
    code = (
        "import sys; "
        "sys.stdout.write('OUT\\n'); sys.stdout.flush(); "
        "sys.stderr.write('ERR\\n'); sys.stderr.flush()"
    )
    result = Command(PY, ["-c", code]).merge_stderr_in_pipe().output()
    assert result.is_success
    assert result.stdout.splitlines() == ["OUT"]
    assert result.stderr.splitlines() == ["ERR"]


# --- ensure_success (C7 batch A) ---------------------------------------------


def test_ensure_success_returns_self_on_success() -> None:
    result = Command(PY, ["-c", "print('ok')"]).output()
    same = result.ensure_success()
    assert same.stdout.strip() == "ok"
    assert same is result


def test_ensure_success_raises_on_failure() -> None:
    result = Command(PY, ["-c", "import sys; sys.exit(3)"]).output()
    with pytest.raises(NonZeroExit) as excinfo:
        result.ensure_success()
    assert excinfo.value.code == 3


def test_bytes_ensure_success_returns_self_on_success() -> None:
    result = Command(PY, ["-c", "print('ok')"]).output_bytes()
    same = result.ensure_success()
    assert bytes(same.stdout).strip() == b"ok"
    assert same is result


def test_bytes_ensure_success_raises_on_failure() -> None:
    result = Command(PY, ["-c", "import sys; sys.exit(3)"]).output_bytes()
    with pytest.raises(NonZeroExit):
        result.ensure_success()


# --- diagnostic (C7 batch A) --------------------------------------------------


def test_nonzero_exit_diagnostic_prefers_stderr() -> None:
    code = "import sys; print('out'); sys.stderr.write('err'); sys.exit(1)"
    with pytest.raises(NonZeroExit) as excinfo:
        Command(PY, ["-c", code]).run()
    assert excinfo.value.diagnostic == "err"


def test_nonzero_exit_diagnostic_falls_back_to_stdout() -> None:
    code = "import sys; print('only stdout'); sys.exit(1)"
    with pytest.raises(NonZeroExit) as excinfo:
        Command(PY, ["-c", code]).run()
    assert excinfo.value.diagnostic == "only stdout"


def test_nonzero_exit_diagnostic_is_none_when_both_streams_blank() -> None:
    with pytest.raises(NonZeroExit) as excinfo:
        Command(PY, ["-c", "import sys; sys.exit(1)"]).run()
    assert excinfo.value.diagnostic is None


def test_timeout_diagnostic_reflects_partial_output() -> None:
    # A generous timeout margin (not 0.2-0.3s): under heavy parallel test-suite
    # load, interpreter startup itself can occasionally take longer than a
    # tight deadline, which would kill the child before it even reaches the
    # `print` — see the retry tests' own note on this same class of flake.
    code = "import sys, time; print('partial', flush=True); time.sleep(30)"
    with pytest.raises(Timeout) as excinfo:
        Command(PY, ["-c", code]).timeout(3.0).run()
    assert excinfo.value.diagnostic == "partial"


# --- ProcessResult/BytesResult.diagnostic and .outcome (T-040) ---------------


def test_process_result_diagnostic_prefers_stderr() -> None:
    code = "import sys; print('out'); sys.stderr.write('err'); sys.exit(1)"
    result = Command(PY, ["-c", code]).output()
    assert result.diagnostic == "err"


def test_process_result_diagnostic_falls_back_to_stdout() -> None:
    code = "import sys; print('only stdout'); sys.exit(1)"
    result = Command(PY, ["-c", code]).output()
    assert result.diagnostic == "only stdout"


def test_process_result_diagnostic_is_none_when_both_streams_blank() -> None:
    result = Command(PY, ["-c", "import sys; sys.exit(1)"]).output()
    assert result.diagnostic is None


def test_bytes_result_diagnostic_prefers_stderr() -> None:
    code = "import sys; print('out'); sys.stderr.write('err'); sys.exit(1)"
    result = Command(PY, ["-c", code]).output_bytes()
    assert result.diagnostic == "err"


def test_bytes_result_diagnostic_falls_back_to_stdout() -> None:
    code = "import sys; print('only stdout'); sys.exit(1)"
    result = Command(PY, ["-c", code]).output_bytes()
    assert result.diagnostic == "only stdout"


def test_bytes_result_diagnostic_is_none_when_both_streams_blank() -> None:
    result = Command(PY, ["-c", "import sys; sys.exit(1)"]).output_bytes()
    assert result.diagnostic is None


def test_process_result_outcome_matches_run_profile_outcome_on_success() -> None:
    cmd = Command(PY, ["-c", "import sys; sys.exit(0)"])
    result = cmd.output()
    with cmd.start() as proc:
        profile = proc.profile(every_seconds=0.05)
    assert result.outcome.code == profile.outcome.code == 0
    assert result.outcome.timed_out == profile.outcome.timed_out is False
    assert result.outcome.signal == profile.outcome.signal is None


def test_process_result_outcome_matches_on_nonzero_exit() -> None:
    result = Command(PY, ["-c", "import sys; sys.exit(3)"]).output()
    assert result.outcome.code == 3
    assert not result.outcome.timed_out
    assert result.outcome.signal is None
    assert not result.outcome.exited_zero


def test_process_result_outcome_matches_on_timeout() -> None:
    code = "import time; time.sleep(30)"
    result = Command(PY, ["-c", code]).timeout(3.0).output()
    assert result.outcome.timed_out
    assert result.outcome.code is None


def test_bytes_result_outcome_matches_on_nonzero_exit() -> None:
    result = Command(PY, ["-c", "import sys; sys.exit(3)"]).output_bytes()
    assert result.outcome.code == 3
    assert not result.outcome.timed_out
    assert not result.outcome.exited_zero


# --- signal as a raw int (C7 batch A) ----------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="raw signal numbers are POSIX-only")
def test_timeout_signal_accepts_a_raw_int() -> None:
    import signal as signal_module

    # `getattr`, not `signal_module.SIGUSR1` directly: typeshed declares SIGUSR1
    # behind a POSIX-only platform guard, so a direct attribute access fails
    # mypy on a Windows dev machine even though this test itself only runs
    # (skipif above) on POSIX, and CI's mypy job runs on Linux either way.
    sigusr1 = getattr(signal_module, "SIGUSR1")  # noqa: B009
    code = (
        "import signal, time\n"
        "signal.signal(signal.SIGUSR1, lambda *a: (_ for _ in ()).throw(SystemExit(7)))\n"
        "time.sleep(30)\n"
    )
    # A generous margin (not 0.2-0.3s) — see the diagnostic test's note on the
    # same interpreter-startup-under-load flake class.
    result = Command(PY, ["-c", code]).timeout(3.0).timeout_signal(int(sigusr1)).output()
    assert result.timed_out


def test_timeout_signal_rejects_bool() -> None:
    # `bool` is a Python `int` subtype; without an explicit guard `True`/`False`
    # would silently mean raw signal 1/0 — and raw 0 is the POSIX existence probe
    # that delivers nothing. Rejected with TypeError before the number path, on
    # every platform.
    with pytest.raises(TypeError):
        Command("x").timeout_signal(True)
    with pytest.raises(TypeError):
        Command("x").timeout_signal(False)


def test_timeout_signal_rejects_int_outside_i32_range() -> None:
    # `timeout_signal` shares the same converter as `ProcessGroup.signal`; the
    # arbitrary-precision Python int must be diagnosed as an invalid raw value,
    # not as a failed conversion to a signal-name string.
    with pytest.raises(ValueError, match="invalid signal number"):
        Command("x").timeout_signal(1 << 40)


@pytest.mark.skipif(sys.platform == "win32", reason="raw signal numbers are POSIX-only")
def test_timeout_signal_rejects_zero_negative_and_out_of_range_on_posix() -> None:
    # Signal 0 is the POSIX existence probe (`kill(pid, 0)`) — it delivers
    # nothing, so it must not be accepted as a real signal; a negative or a
    # number past SIGRTMAX would likewise be a silent no-op on the process-group
    # backend, so all three raise ValueError up front.
    for bad in (0, -1, 100_000):
        with pytest.raises(ValueError):
            Command("x").timeout_signal(bad)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows has no POSIX signals")
def test_timeout_signal_raw_int_unsupported_on_windows() -> None:
    # A Job Object has no POSIX signals, so a raw number can never be delivered:
    # rejected immediately from the builder (consistently with
    # `ProcessGroup.signal`), rather than only failing when the timeout fires.
    with pytest.raises(Unsupported):
        Command("x").timeout_signal(9)
    # The named "kill" still configures fine — the raw-number guard leaves the
    # name path untouched.
    Command("x").timeout_signal("kill")


# --- CancellationToken / cancel_on (C7 batch B) ------------------------------


def test_cancellation_token_starts_uncancelled_and_reports_cancel() -> None:
    token = CancellationToken()
    assert not token.is_cancelled()
    token.cancel()
    assert token.is_cancelled()
    token.cancel()  # idempotent
    assert token.is_cancelled()


def test_cancellation_token_child_token_reflects_parent_state() -> None:
    parent = CancellationToken()
    child = parent.child_token()
    assert not child.is_cancelled()
    parent.cancel()
    assert child.is_cancelled()

    # The reverse does not hold: cancelling a child leaves the parent (and its
    # other children) alone.
    other_parent = CancellationToken()
    other_child = other_parent.child_token()
    sibling = other_parent.child_token()
    other_child.cancel()
    assert other_child.is_cancelled()
    assert not other_parent.is_cancelled()
    assert not sibling.is_cancelled()


def test_cancel_on_tears_down_the_run_and_raises_cancelled() -> None:
    async def scenario() -> None:
        token = CancellationToken()
        cmd = Command(PY, ["-c", "import time; time.sleep(30)"]).cancel_on(token)
        task = asyncio.ensure_future(cmd.arun())
        await asyncio.sleep(0.2)  # let the child actually start
        token.cancel()
        with pytest.raises(Cancelled) as excinfo:
            await task
        assert excinfo.value.program == PY

    asyncio.run(scenario())


# --- stdout_tee / stderr_tee — file sink (T-004) -----------------------------

# Two flushed stdout lines; the tee writes each decoded line + "\n" as it lands,
# while capture keeps the whole output.
_TEE_TWO_LINES = "print('alpha', flush=True); print('beta', flush=True)"


def test_stdout_tee_writes_lines_and_keeps_capture(tmp_path: pathlib.Path) -> None:
    # The live stream reaches the file sink line by line (each terminated with a
    # single "\n", CRLF normalized by the pump), AND the captured result is
    # intact — the tee does not steal output from ProcessResult.stdout.
    sink = tmp_path / "out.log"
    result = Command(PY, ["-c", _TEE_TWO_LINES]).stdout_tee(sink).output()
    assert result.is_success
    assert result.stdout.splitlines() == ["alpha", "beta"]
    assert sink.read_bytes() == b"alpha\nbeta\n"


def test_stdout_sanitize_vt_coexists_with_tee_without_rewriting_it(
    tmp_path: pathlib.Path,
) -> None:
    sink = tmp_path / "raw.log"
    code = "import sys; sys.stdout.write('\\x1b[35mclean\\x1b[0m\\n'); sys.stdout.flush()"
    result = Command(PY, ["-c", code]).stdout_tee(sink).stdout_sanitize_vt().output()
    assert result.stdout == "clean"
    assert sink.read_bytes() == b"\x1b[35mclean\x1b[0m\n"


def test_stderr_tee_writes_lines_and_keeps_capture(tmp_path: pathlib.Path) -> None:
    sink = tmp_path / "err.log"
    code = "import sys; print('to-err', file=sys.stderr, flush=True); print('to-out', flush=True)"
    result = Command(PY, ["-c", code]).stderr_tee(sink).output()
    assert result.stdout.strip() == "to-out"
    assert "to-err" in result.stderr
    assert sink.read_bytes() == b"to-err\n"


def test_stdout_and_stderr_tee_to_separate_files(tmp_path: pathlib.Path) -> None:
    # Both sinks can be active at once, each receiving only its own stream.
    out = tmp_path / "out.log"
    err = tmp_path / "err.log"
    code = (
        "import sys; print('o1', flush=True); "
        "print('e1', file=sys.stderr, flush=True); print('o2', flush=True)"
    )
    result = Command(PY, ["-c", code]).stdout_tee(out).stderr_tee(err).output()
    assert result.stdout.splitlines() == ["o1", "o2"]
    assert "e1" in result.stderr
    assert out.read_bytes() == b"o1\no2\n"
    assert err.read_bytes() == b"e1\n"


def test_tee_truncates_the_sink_by_default(tmp_path: pathlib.Path) -> None:
    # The file is opened create/truncate by default — stale content is gone.
    sink = tmp_path / "out.log"
    sink.write_bytes(b"stale-content\nmore-stale\n")
    Command(PY, ["-c", "print('fresh', flush=True)"]).stdout_tee(sink).output()
    assert sink.read_bytes() == b"fresh\n"


def test_tee_append_mode_preserves_existing_content(tmp_path: pathlib.Path) -> None:
    # append=True opens the file in append mode instead of truncating it.
    sink = tmp_path / "out.log"
    sink.write_bytes(b"prior\n")
    Command(PY, ["-c", "print('added', flush=True)"]).stdout_tee(sink, append=True).output()
    assert sink.read_bytes() == b"prior\nadded\n"


def test_tee_reused_command_appends_across_sequential_runs(tmp_path: pathlib.Path) -> None:
    # The sink is opened once, at build time, and the single open handle is shared
    # across runs of the same built Command — so sequential re-runs append to the
    # one file (the crate holds the sink in an Arc<Mutex<…>>), with no delimiter.
    sink = tmp_path / "out.log"
    cmd = Command(PY, ["-c", "print('run', flush=True)"]).stdout_tee(sink)
    cmd.output()
    cmd.output()
    assert sink.read_bytes() == b"run\nrun\n"


def test_tee_opens_the_file_at_build_time_not_at_run(tmp_path: pathlib.Path) -> None:
    # The crate takes a concrete AsyncWrite on stdout_tee(), so the file is opened
    # the moment the builder method is called — a bad path (missing parent dir)
    # raises an OSError right here, before any run verb, not a panic.
    cmd = Command(PY, ["-c", "pass"])
    bad = tmp_path / "no-such-dir" / "out.log"
    with pytest.raises(OSError):
        cmd.stdout_tee(bad)


def test_tee_directory_path_raises_oserror(tmp_path: pathlib.Path) -> None:
    # A directory can't be opened as a writable file — a clean OSError, not a panic.
    with pytest.raises(OSError):
        Command(PY, ["-c", "pass"]).stderr_tee(tmp_path)


def test_stdout_tee_is_inert_under_output_bytes(tmp_path: pathlib.Path) -> None:
    # output_bytes() captures stdout raw (no line pump), so the tee — which fires
    # from the line pump — is a no-op: the file stays empty, capture is unaffected.
    sink = tmp_path / "out.log"
    result = Command(PY, ["-c", _TEE_TWO_LINES]).stdout_tee(sink).output_bytes()
    assert result.stdout.split() == [b"alpha", b"beta"]
    assert sink.read_bytes() == b""


# --- stdin_file — streaming file-backed stdin (T-039) ------------------------

# Echoes each stdin line uppercased until EOF (same helper as test_streaming.py).
_ECHO_UPPER = (
    "import sys; [(sys.stdout.write(line.upper()), sys.stdout.flush()) for line in sys.stdin]"
)


def test_stdin_file_feeds_input(tmp_path: pathlib.Path) -> None:
    src = tmp_path / "in.txt"
    src.write_text("abc\n", encoding="utf-8")
    assert Command(PY, ["-c", _ECHO_UPPER]).stdin_file(src).run() == "ABC"


def test_stdin_file_accepts_pathlike(tmp_path: pathlib.Path) -> None:
    # Same StrPath contract as arg()/cwd(): a pathlib.Path works, not just str.
    src = tmp_path / "in.txt"
    src.write_text("xyz\n", encoding="utf-8")
    assert Command(PY, ["-c", _ECHO_UPPER]).stdin_file(src).run() == "XYZ"


def test_stdin_file_does_not_touch_filesystem_at_build_time(tmp_path: pathlib.Path) -> None:
    # Unlike stdout_tee()/stderr_tee(), stdin_file() does not open (or even stat)
    # the path when called — a not-yet-existing path is accepted here; matches
    # the rest of the builder, which never touches the filesystem at build time.
    missing = tmp_path / "does-not-exist-yet.txt"
    cmd = Command(PY, ["-c", "pass"]).stdin_file(missing)
    assert isinstance(cmd, Command)


def test_stdin_file_missing_path_fails_at_run_not_build(tmp_path: pathlib.Path) -> None:
    # The error is deferred to spawn time (when the crate actually opens the
    # file) — surfaced as the generic ProcessError, not FileNotFoundError: a
    # stdin-write failure is not classified as a launch condition, since the
    # child process has already spawned successfully by then.
    missing = tmp_path / "does-not-exist.txt"
    cmd = Command(PY, ["-c", _ECHO_UPPER]).stdin_file(missing)  # no raise here
    with pytest.raises(ProcessError):
        cmd.run()


def test_stdin_file_does_not_buffer_whole_file_in_python(tmp_path: pathlib.Path) -> None:
    # The point of stdin_file() over stdin_bytes()/stdin_text() is that a large
    # input streams straight from disk to the child, never fully materialized as
    # a Python object. Feed a file bigger than any reasonable line/record and
    # confirm the child receives it all — a full-read-into-Python approach would
    # still pass this, so the real guarantee is architectural (see stdin_file()'s
    # docstring), but this at least pins that large inputs survive intact.
    src = tmp_path / "big.bin"
    payload = b"a" * (8 * 1024 * 1024)  # 8 MiB
    src.write_bytes(payload)
    code = (
        "import sys; data = sys.stdin.buffer.read(); "
        "print(len(data)); print(data == b'a' * (8 * 1024 * 1024))"
    )
    result = Command(PY, ["-c", code]).stdin_file(src).output()
    lines = result.stdout.splitlines()
    assert lines[0] == str(8 * 1024 * 1024)
    assert lines[1] == "True"


def test_stdin_file_overrides_earlier_stdin_bytes(tmp_path: pathlib.Path) -> None:
    # Last stdin-configuring call wins — same convention already in force for
    # stdin_bytes()/stdin_text()/keep_stdin_open().
    src = tmp_path / "in.txt"
    src.write_text("from-file\n", encoding="utf-8")
    result = Command(PY, ["-c", _ECHO_UPPER]).stdin_bytes(b"from-bytes\n").stdin_file(src).run()
    assert result == "FROM-FILE"


def test_stdin_bytes_overrides_earlier_stdin_file(tmp_path: pathlib.Path) -> None:
    # The reverse order also wins for the later call, confirming stdin_file()
    # participates in the same "last stdin method wins" chain as the others.
    src = tmp_path / "in.txt"
    src.write_text("from-file\n", encoding="utf-8")
    result = Command(PY, ["-c", _ECHO_UPPER]).stdin_file(src).stdin_bytes(b"from-bytes\n").run()
    assert result == "FROM-BYTES"


# --- inherit_stdin — child reads the parent's real stdin (T-110) -------------


def test_inherit_stdin_builds_without_conflicting_settings() -> None:
    # A plain inherit_stdin() (no mediated source, no keep_stdin_open) is a valid
    # build — the conflict guard fires only at launch, never here.
    cmd = Command(PY, ["-c", "pass"]).inherit_stdin()
    assert isinstance(cmd, Command)


def test_inherit_stdin_alone_runs_and_still_captures_stdout() -> None:
    # A child that inherits the parent's stdin but never reads it runs normally;
    # only stdin is shared, so stdout stays piped and is captured as usual.
    result = Command(PY, ["-c", "print('inherited')"]).inherit_stdin().run()
    assert result == "inherited"


def _mk_stdin_file(tmp_path: pathlib.Path) -> pathlib.Path:
    src = tmp_path / "in.txt"
    src.write_text("x\n", encoding="utf-8")
    return src


# Each factory builds a Command that combines inherit_stdin() with a mediated
# stdin knob — both call orders, for every mediated source and keep_stdin_open().
_INHERIT_STDIN_CONFLICTS = [
    pytest.param(
        lambda tp: Command(PY, ["-c", "pass"]).inherit_stdin().stdin_bytes(b"x"),
        id="inherit-then-stdin_bytes",
    ),
    pytest.param(
        lambda tp: Command(PY, ["-c", "pass"]).stdin_bytes(b"x").inherit_stdin(),
        id="stdin_bytes-then-inherit",
    ),
    pytest.param(
        lambda tp: Command(PY, ["-c", "pass"]).inherit_stdin().stdin_text("x"),
        id="inherit-then-stdin_text",
    ),
    pytest.param(
        lambda tp: Command(PY, ["-c", "pass"]).stdin_text("x").inherit_stdin(),
        id="stdin_text-then-inherit",
    ),
    pytest.param(
        lambda tp: Command(PY, ["-c", "pass"]).inherit_stdin().stdin_file(_mk_stdin_file(tp)),
        id="inherit-then-stdin_file",
    ),
    pytest.param(
        lambda tp: Command(PY, ["-c", "pass"]).stdin_file(_mk_stdin_file(tp)).inherit_stdin(),
        id="stdin_file-then-inherit",
    ),
    pytest.param(
        lambda tp: Command(PY, ["-c", "pass"]).inherit_stdin().keep_stdin_open(),
        id="inherit-then-keep_stdin_open",
    ),
    pytest.param(
        lambda tp: Command(PY, ["-c", "pass"]).keep_stdin_open().inherit_stdin(),
        id="keep_stdin_open-then-inherit",
    ),
]


@pytest.mark.parametrize("build", _INHERIT_STDIN_CONFLICTS)
@pytest.mark.parametrize("verb", ["run", "output"])
def test_inherit_stdin_conflict_raises_at_run_not_build(
    build: object, verb: str, tmp_path: pathlib.Path
) -> None:
    # inherit_stdin() cannot be combined with a mediated stdin (a configured
    # source, or keep_stdin_open()'s interactive pipe): a child either reads the
    # parent's stdin or has its stdin driven by the crate, not both. Building the
    # combination never raises — the crate rejects the contradiction at the launch
    # seam, surfaced as ProcessError from the run/output verb (before any spawn),
    # not at build time. Both call orders and both verbs are covered.
    cmd = build(tmp_path)  # type: ignore[operator]
    assert isinstance(cmd, Command)  # the conflicting build itself is inert
    with pytest.raises(ProcessError):
        getattr(cmd, verb)()


def test_stdout_tee_is_inert_under_stdout_null(tmp_path: pathlib.Path) -> None:
    # stdout("null") runs no capture pump — the tee is inert (empty file). null is
    # non-capturing, so the run goes through start() + outcome() (the capture verbs
    # reject a non-piped stdout), which still completes the child cleanly.
    sink = tmp_path / "out.log"
    outcome = Command(PY, ["-c", _TEE_TWO_LINES]).stdout("null").stdout_tee(sink).start().outcome()
    assert outcome.exited_zero
    assert sink.read_bytes() == b""


def test_stdout_tee_is_inert_under_stdout_inherit(tmp_path: pathlib.Path) -> None:
    # stdout("inherit") sends the child's stdout to the parent's — no capture pump,
    # so the tee is inert. Like null, inherit is non-capturing, so run it via
    # start() + outcome().
    sink = tmp_path / "out.log"
    cmd = Command(PY, ["-c", _TEE_TWO_LINES]).stdout("inherit").stdout_tee(sink)
    outcome = cmd.start().outcome()
    assert outcome.exited_zero
    assert sink.read_bytes() == b""


@pytest.mark.skipif(
    sys.platform in ("win32", "darwin"),
    reason="/dev/full (a sink whose every write fails with ENOSPC) is Linux-only"
    " - absent on win32 and not usable the same way on darwin",
)
def test_tee_write_error_is_isolated_from_the_run(tmp_path: pathlib.Path) -> None:
    # /dev/full accepts open() but fails every write with ENOSPC. The crate
    # disables the tee on the write error and keeps going — the run and its
    # captured result are unaffected, and no exception surfaces to the caller.
    # The captured stdout must still be whole even though the sink took nothing.
    result = Command(PY, ["-c", _TEE_TWO_LINES]).stdout_tee("/dev/full").output()
    assert result.is_success
    assert result.stdout.splitlines() == ["alpha", "beta"]


# --- stdout_tee / stderr_tee — Python writer sink (T-038) --------------------


def test_stdout_tee_to_stringio_mirrors_lines_and_keeps_capture() -> None:
    # A Python writer (here io.StringIO) receives every decoded line + "\n" as it
    # lands — the text-object twin of the file-path tee — while capture stays
    # whole (the tee does not steal output from ProcessResult.stdout).
    buf = io.StringIO()
    result = Command(PY, ["-c", _TEE_TWO_LINES]).stdout_tee(buf).output()
    assert result.is_success
    assert result.stdout.splitlines() == ["alpha", "beta"]
    assert buf.getvalue() == "alpha\nbeta\n"


def test_stderr_tee_to_stringio_mirrors_lines_and_keeps_capture() -> None:
    buf = io.StringIO()
    code = "import sys; print('to-err', file=sys.stderr, flush=True); print('to-out', flush=True)"
    result = Command(PY, ["-c", code]).stderr_tee(buf).output()
    assert result.stdout.strip() == "to-out"
    assert "to-err" in result.stderr
    assert buf.getvalue() == "to-err\n"


def test_stdout_tee_to_custom_writer_object() -> None:
    # Any object with a callable write(str) qualifies — not just io.StringIO.
    class Collector:
        def __init__(self) -> None:
            self.chunks: list[str] = []

        def write(self, data: str) -> int:
            self.chunks.append(data)
            return len(data)

    sink = Collector()
    result = Command(PY, ["-c", _TEE_TWO_LINES]).stdout_tee(sink).output()
    assert result.is_success
    assert "".join(sink.chunks) == "alpha\nbeta\n"


def test_stdout_tee_retries_partial_text_writer_by_character() -> None:
    class PartialWriter:
        def __init__(self) -> None:
            self.data = ""
            self.calls = 0

        def write(self, data: str) -> int:
            self.data += data[:1]
            self.calls += 1
            return min(1, len(data))

    sink = PartialWriter()
    result = Command(PY, ["-c", "print('h\u00e9llo', flush=True)"]).stdout_tee(sink).output()

    assert sink.calls > 1
    assert sink.data == "h\u00e9llo\n"
    assert result.stdout == "h\u00e9llo"


def test_tee_writer_receives_str_not_bytes() -> None:
    # The sink is a TEXT sink: the decoded line is passed to write() as `str`,
    # not `bytes` (so io.StringIO / sys.stderr fit; a binary sink would not).
    seen_types: set[type] = set()

    class TypeProbe:
        def write(self, data: object) -> int:
            seen_types.add(type(data))
            return len(data) if isinstance(data, str | bytes) else 0

    Command(PY, ["-c", _TEE_TWO_LINES]).stdout_tee(TypeProbe()).output()
    assert seen_types == {str}


def test_tee_writer_raising_write_is_isolated_and_disables_the_tee() -> None:
    # A write() that raises does not derail the run: the exception is surfaced via
    # sys.unraisablehook (never propagated to the caller), the tee is disabled
    # after the first failure (a permanently-broken writer is not re-invoked once
    # per line), and the captured result stays intact.
    captured: list[BaseException] = []
    calls: list[str] = []

    def hook(unraisable: object) -> None:
        exc = getattr(unraisable, "exc_value", None)
        if isinstance(exc, BaseException):
            captured.append(exc)

    class Boom:
        def write(self, data: str) -> None:
            calls.append(data)
            raise ValueError("writer exploded")

    old_hook = sys.unraisablehook
    sys.unraisablehook = hook
    try:
        result = Command(PY, ["-c", _TEE_TWO_LINES]).stdout_tee(Boom()).output()
    finally:
        sys.unraisablehook = old_hook

    assert result.is_success
    assert result.stdout.splitlines() == ["alpha", "beta"]
    assert captured
    assert isinstance(captured[0], ValueError)
    # Disabled after the first error: only the first line's write was attempted.
    assert calls == ["alpha"]


def test_stdout_tee_file_and_stderr_tee_object_coexist(tmp_path: pathlib.Path) -> None:
    # Both sink forms active at once on one command: a file path on stdout and a
    # Python writer on stderr, each receiving only its own stream.
    out = tmp_path / "out.log"
    err_buf = io.StringIO()
    code = (
        "import sys; print('o1', flush=True); "
        "print('e1', file=sys.stderr, flush=True); print('o2', flush=True)"
    )
    result = Command(PY, ["-c", code]).stdout_tee(out).stderr_tee(err_buf).output()
    assert result.stdout.splitlines() == ["o1", "o2"]
    assert out.read_bytes() == b"o1\no2\n"
    assert err_buf.getvalue() == "e1\n"


def test_tee_writer_rejects_append_true() -> None:
    # append tunes how a FILE is opened; it is meaningless for a writer object, so
    # passing it is a loud ValueError rather than a silent no-op.
    with pytest.raises(ValueError, match="append"):
        Command(PY, ["-c", "pass"]).stdout_tee(io.StringIO(), append=True)
    with pytest.raises(ValueError, match="append"):
        Command(PY, ["-c", "pass"]).stderr_tee(io.StringIO(), append=True)


def test_tee_writer_is_not_closed_after_the_run() -> None:
    # The tee does not own the object (you passed your own sys.stderr / open
    # file), so it must stay open and usable once the run is done.
    buf = io.StringIO()
    Command(PY, ["-c", _TEE_TWO_LINES]).stdout_tee(buf).output()
    assert not buf.closed
    buf.write("still-usable")  # would raise on a closed StringIO
    assert buf.getvalue() == "alpha\nbeta\nstill-usable"


def test_tee_writer_is_inert_under_output_bytes() -> None:
    # Same no-op family as the file tee: output_bytes() captures stdout raw (no
    # line pump), so the stdout writer tee never fires.
    buf = io.StringIO()
    result = Command(PY, ["-c", _TEE_TWO_LINES]).stdout_tee(buf).output_bytes()
    assert result.stdout.split() == [b"alpha", b"beta"]
    assert buf.getvalue() == ""


# --- stdout_raw_tee / stderr_raw_tee — undecoded byte tee (T-219) ------------

# Writes raw bytes with an explicit CRLF line ending via the binary stream
# (sys.stdout.buffer), bypassing Python's own text-mode newline translation —
# the raw tee must preserve these bytes verbatim, unlike the decoded
# stdout_tee (which normalizes to a single "\n" per line, see
# test_stdout_tee_writes_lines_and_keeps_capture).
_RAW_TEE_CRLF_BYTES = b"alpha\r\nbeta\r\n"
_RAW_TEE_CRLF_CODE = (
    "import sys; sys.stdout.buffer.write(b'alpha\\r\\nbeta\\r\\n'); sys.stdout.buffer.flush()"
)


def test_stdout_raw_tee_preserves_bytes_verbatim_unlike_decoded_tee(
    tmp_path: pathlib.Path,
) -> None:
    sink = tmp_path / "out.raw"
    result = Command(PY, ["-c", _RAW_TEE_CRLF_CODE]).stdout_raw_tee(sink).output()
    assert result.is_success
    # The raw tee kept the CRLF bytes exactly as the child wrote them...
    assert sink.read_bytes() == _RAW_TEE_CRLF_BYTES
    # ...while the decoded capture went through the crate's line splitting,
    # which does not fabricate or preserve the "\r" as line content.
    assert result.stdout.splitlines() == ["alpha", "beta"]


def test_stderr_raw_tee_preserves_bytes_verbatim(tmp_path: pathlib.Path) -> None:
    sink = tmp_path / "err.raw"
    code = _RAW_TEE_CRLF_CODE.replace("sys.stdout", "sys.stderr")
    result = Command(PY, ["-c", code]).stderr_raw_tee(sink).output()
    assert result.is_success
    assert sink.read_bytes() == _RAW_TEE_CRLF_BYTES


def test_stdout_raw_tee_keeps_capture_intact(tmp_path: pathlib.Path) -> None:
    # Strictly additive: capture is unaffected whether or not a raw tee is set.
    sink = tmp_path / "out.raw"
    result = Command(PY, ["-c", _TEE_TWO_LINES]).stdout_raw_tee(sink).output()
    assert result.stdout.splitlines() == ["alpha", "beta"]


def test_stdout_raw_tee_independent_of_decoded_tee_and_on_stdout_line(
    tmp_path: pathlib.Path,
) -> None:
    # All three stdout sinks — decoded tee, raw tee, and the per-line callback
    # — coexist and fire independently from the same pump.
    decoded_sink = tmp_path / "decoded.log"
    raw_sink = tmp_path / "raw.log"
    seen: list[str] = []
    result = (
        Command(PY, ["-c", _RAW_TEE_CRLF_CODE])
        .stdout_tee(decoded_sink)
        .stdout_raw_tee(raw_sink)
        .on_stdout_line(seen.append)
        .output()
    )
    assert result.is_success
    assert raw_sink.read_bytes() == _RAW_TEE_CRLF_BYTES
    assert decoded_sink.read_bytes() == b"alpha\nbeta\n"
    assert seen == ["alpha", "beta"]


def test_stdout_raw_tee_to_bytesio_object() -> None:
    # The Python-writer sink form: a BINARY writer receives each raw chunk as
    # `bytes`, verbatim — the binary-sink twin of stdout_tee's text writer.
    buf = io.BytesIO()
    result = Command(PY, ["-c", _RAW_TEE_CRLF_CODE]).stdout_raw_tee(buf).output()
    assert result.is_success
    assert buf.getvalue() == _RAW_TEE_CRLF_BYTES


def test_stdout_raw_tee_retries_partial_writer_without_truncating_capture() -> None:
    class PartialWriter:
        def __init__(self, quota: int) -> None:
            self.quota = quota
            self.data = bytearray()
            self.calls = 0

        def write(self, data: bytes) -> int:
            accepted = data[: self.quota]
            self.data.extend(accepted)
            self.calls += 1
            return len(accepted)

    sink = PartialWriter(quota=3)
    result = Command(PY, ["-c", _RAW_TEE_CRLF_CODE]).stdout_raw_tee(sink).output()

    assert sink.calls > 1
    assert bytes(sink.data) == _RAW_TEE_CRLF_BYTES
    assert result.stdout.splitlines() == ["alpha", "beta"]


def test_stderr_raw_tee_to_bytesio_object() -> None:
    buf = io.BytesIO()
    code = _RAW_TEE_CRLF_CODE.replace("sys.stdout", "sys.stderr")
    result = Command(PY, ["-c", code]).stderr_raw_tee(buf).output()
    assert result.is_success
    assert buf.getvalue() == _RAW_TEE_CRLF_BYTES


def test_raw_tee_writer_receives_bytes_not_str() -> None:
    # The raw sink is a BINARY sink: a text writer's write(bytes) raises
    # TypeError, the inverse of test_tee_writer_receives_str_not_bytes.
    seen_types: set[type] = set()

    class TypeProbe:
        def write(self, data: object) -> int:
            seen_types.add(type(data))
            return len(data) if isinstance(data, str | bytes) else 0

    Command(PY, ["-c", _TEE_TWO_LINES]).stdout_raw_tee(TypeProbe()).output()
    assert seen_types == {bytes}


def test_raw_tee_writer_rejects_append_true() -> None:
    with pytest.raises(ValueError, match="append"):
        Command(PY, ["-c", "pass"]).stdout_raw_tee(io.BytesIO(), append=True)
    with pytest.raises(ValueError, match="append"):
        Command(PY, ["-c", "pass"]).stderr_raw_tee(io.BytesIO(), append=True)


def test_raw_tee_writer_is_not_closed_after_the_run() -> None:
    buf = io.BytesIO()
    Command(PY, ["-c", _RAW_TEE_CRLF_CODE]).stdout_raw_tee(buf).output()
    assert not buf.closed
    buf.write(b"still-usable")  # would raise on a closed BytesIO
    assert buf.getvalue() == _RAW_TEE_CRLF_BYTES + b"still-usable"


def test_raw_tee_writer_raising_write_is_isolated_and_disables_the_tee() -> None:
    # Same isolation contract as the decoded tee: a raising write() is
    # reported via sys.unraisablehook, never propagated, and the tee is
    # disabled after the first failure while the captured result stays intact.
    captured: list[BaseException] = []
    calls: list[bytes] = []

    def hook(unraisable: object) -> None:
        exc = getattr(unraisable, "exc_value", None)
        if isinstance(exc, BaseException):
            captured.append(exc)

    class Boom:
        def write(self, data: bytes) -> None:
            calls.append(data)
            raise ValueError("raw writer exploded")

    old_hook = sys.unraisablehook
    sys.unraisablehook = hook
    try:
        result = Command(PY, ["-c", _TEE_TWO_LINES]).stdout_raw_tee(Boom()).output()
    finally:
        sys.unraisablehook = old_hook

    assert result.is_success
    assert result.stdout.splitlines() == ["alpha", "beta"]
    assert captured
    assert isinstance(captured[0], ValueError)
    assert calls  # at least the first chunk was attempted


def test_stdout_raw_tee_is_inert_under_stdout_null(tmp_path: pathlib.Path) -> None:
    sink = tmp_path / "out.raw"
    cmd = Command(PY, ["-c", _TEE_TWO_LINES]).stdout("null").stdout_raw_tee(sink)
    outcome = cmd.start().outcome()
    assert outcome.exited_zero
    assert sink.read_bytes() == b""


def test_stdout_raw_tee_is_inert_under_stdout_inherit(tmp_path: pathlib.Path) -> None:
    sink = tmp_path / "out.raw"
    cmd = Command(PY, ["-c", _TEE_TWO_LINES]).stdout("inherit").stdout_raw_tee(sink)
    outcome = cmd.start().outcome()
    assert outcome.exited_zero
    assert sink.read_bytes() == b""


def test_stdout_raw_tee_is_inert_under_stdout_file_redirect(tmp_path: pathlib.Path) -> None:
    # K-043: stdout_file()'s capture gate is stdout-only — drive via
    # start()/outcome() (the capture verbs reject a non-piped stdout).
    redirect = tmp_path / "redirected.out"
    raw_sink = tmp_path / "out.raw"
    cmd = Command(PY, ["-c", _TEE_TWO_LINES]).stdout_file(redirect).stdout_raw_tee(raw_sink)
    outcome = cmd.start().outcome()
    assert outcome.exited_zero
    assert raw_sink.read_bytes() == b""
    assert redirect.exists()  # the child's stdout went straight to the file


def test_stdout_raw_tee_is_inert_under_output_bytes(tmp_path: pathlib.Path) -> None:
    # output_bytes()'s own return value already *is* the raw stdout (a
    # separate raw drain, no line pump), so the raw tee never fires.
    sink = tmp_path / "out.raw"
    result = Command(PY, ["-c", _TEE_TWO_LINES]).stdout_raw_tee(sink).output_bytes()
    assert result.stdout.split() == [b"alpha", b"beta"]
    assert sink.read_bytes() == b""


def test_stdout_and_stderr_raw_tee_to_separate_files(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.raw"
    err = tmp_path / "err.raw"
    code = (
        "import sys; sys.stdout.buffer.write(b'o1\\r\\n'); "
        "sys.stderr.buffer.write(b'e1\\r\\n'); sys.stdout.buffer.write(b'o2\\r\\n')"
    )
    result = Command(PY, ["-c", code]).stdout_raw_tee(out).stderr_raw_tee(err).output()
    assert result.is_success
    assert out.read_bytes() == b"o1\r\no2\r\n"
    assert err.read_bytes() == b"e1\r\n"


# --- on_stdout_line / on_stderr_line — live per-line callbacks (T-037) -------


def test_on_stdout_line_called_in_order_and_keeps_capture() -> None:
    seen: list[str] = []
    result = Command(PY, ["-c", _TEE_TWO_LINES]).on_stdout_line(seen.append).output()
    assert result.is_success
    assert seen == ["alpha", "beta"]
    assert result.stdout.splitlines() == ["alpha", "beta"]


def test_on_stderr_line_called_in_order_and_keeps_capture() -> None:
    seen: list[str] = []
    code = (
        "import sys; "
        "print('e1', file=sys.stderr, flush=True); "
        "print('e2', file=sys.stderr, flush=True); "
        "print('to-out', flush=True)"
    )
    result = Command(PY, ["-c", code]).on_stderr_line(seen.append).output()
    assert result.stdout.strip() == "to-out"
    assert seen == ["e1", "e2"]
    assert result.stderr.splitlines() == ["e1", "e2"]


def test_on_stdout_and_on_stderr_line_both_fire_independently() -> None:
    out_seen: list[str] = []
    err_seen: list[str] = []
    code = (
        "import sys; "
        "print('o1', flush=True); "
        "print('e1', file=sys.stderr, flush=True); "
        "print('o2', flush=True)"
    )
    result = (
        Command(PY, ["-c", code])
        .on_stdout_line(out_seen.append)
        .on_stderr_line(err_seen.append)
        .output()
    )
    assert out_seen == ["o1", "o2"]
    assert err_seen == ["e1"]
    assert result.stdout.splitlines() == ["o1", "o2"]


def test_aoutput_on_stdout_line_fires_on_the_async_path() -> None:
    # Same callback, driven through the async verb — one bridge, both paths.
    seen: list[str] = []

    async def scenario() -> ProcessResult:
        return await Command(PY, ["-c", _TEE_TWO_LINES]).on_stdout_line(seen.append).aoutput()

    result = asyncio.run(scenario())
    assert result.is_success
    assert seen == ["alpha", "beta"]
    assert result.stdout.splitlines() == ["alpha", "beta"]


def test_on_stdout_line_raising_callback_is_swallowed_and_capture_is_intact() -> None:
    # Infallible from the binding's perspective: an exception inside the
    # callback is surfaced via the unraisable hook (like
    # DryRunRunner.on_invocation / ScriptedRunner.when), never propagated to
    # the caller and never corrupting the captured result.
    captured: list[BaseException] = []

    def hook(unraisable: object) -> None:
        exc = getattr(unraisable, "exc_value", None)
        if isinstance(exc, BaseException):
            captured.append(exc)

    def boom(_line: str) -> None:
        raise ValueError("callback exploded")

    old_hook = sys.unraisablehook
    sys.unraisablehook = hook
    try:
        result = Command(PY, ["-c", _TEE_TWO_LINES]).on_stdout_line(boom).output()
    finally:
        sys.unraisablehook = old_hook

    assert result.is_success
    assert result.stdout.splitlines() == ["alpha", "beta"]
    assert captured
    assert isinstance(captured[0], ValueError)


def test_on_stderr_line_raising_callback_is_swallowed_and_capture_is_intact() -> None:
    captured: list[BaseException] = []

    def hook(unraisable: object) -> None:
        exc = getattr(unraisable, "exc_value", None)
        if isinstance(exc, BaseException):
            captured.append(exc)

    def boom(_line: str) -> None:
        raise ValueError("stderr callback exploded")

    old_hook = sys.unraisablehook
    sys.unraisablehook = hook
    try:
        code = "import sys; print('e1', file=sys.stderr, flush=True)"
        result = Command(PY, ["-c", code]).on_stderr_line(boom).output()
    finally:
        sys.unraisablehook = old_hook

    assert result.is_success
    assert result.stderr.splitlines() == ["e1"]
    assert captured
    assert isinstance(captured[0], ValueError)


def test_on_stdout_line_is_inert_under_stdout_null() -> None:
    seen: list[str] = []
    cmd = Command(PY, ["-c", _TEE_TWO_LINES]).stdout("null").on_stdout_line(seen.append)
    outcome = cmd.start().outcome()
    assert outcome.exited_zero
    assert seen == []


def test_on_stdout_line_is_inert_under_stdout_inherit() -> None:
    seen: list[str] = []
    cmd = Command(PY, ["-c", _TEE_TWO_LINES]).stdout("inherit").on_stdout_line(seen.append)
    outcome = cmd.start().outcome()
    assert outcome.exited_zero
    assert seen == []


def test_on_stdout_line_is_inert_under_output_bytes() -> None:
    # output_bytes() captures stdout raw (no line pump) — same no-op family as
    # stdout_tee under output_bytes().
    seen: list[str] = []
    result = Command(PY, ["-c", _TEE_TWO_LINES]).on_stdout_line(seen.append).output_bytes()
    assert result.stdout.split() == [b"alpha", b"beta"]
    assert seen == []


def test_on_stderr_line_still_fires_under_output_bytes() -> None:
    # Unlike on_stdout_line, output_bytes() does NOT silence on_stderr_line:
    # only the stdout capture goes raw there — stderr still decodes through
    # the line pump exactly as it does under output().
    seen: list[str] = []
    code = "import sys; print('e1', file=sys.stderr, flush=True)"
    result = Command(PY, ["-c", code]).on_stderr_line(seen.append).output_bytes()
    assert seen == ["e1"]
    assert result.stderr.splitlines() == ["e1"]


def test_on_stdout_line_repeat_call_replaces_the_previous_handler() -> None:
    first_seen: list[str] = []
    second_seen: list[str] = []
    result = (
        Command(PY, ["-c", _TEE_TWO_LINES])
        .on_stdout_line(first_seen.append)
        .on_stdout_line(second_seen.append)
        .output()
    )
    assert result.is_success
    assert first_seen == []
    assert second_seen == ["alpha", "beta"]


def test_cancel_on_replaces_a_prior_token() -> None:
    # Command.cancel_on REPLACES (not gap-fills) — the last call wins, so
    # firing the FIRST token must not cancel a command whose cancel_on() was
    # called again with a second token.
    async def scenario() -> str:
        first = CancellationToken()
        second = CancellationToken()
        cmd = Command(PY, ["-c", "print('unaffected')"]).cancel_on(first).cancel_on(second)
        first.cancel()  # the replaced, no-longer-wired token
        return await cmd.arun()

    assert asyncio.run(scenario()) == "unaffected"


def test_cancelled_is_never_retried() -> None:
    # A cancelled run is terminal: retry_if="transient_or_timeout" (the
    # broadest preset) must not retry it — Error::Cancelled is excluded from
    # both is_transient() and is_timeout() by the crate itself.
    async def scenario() -> None:
        token = CancellationToken()
        cmd = (
            Command(PY, ["-c", "import time; time.sleep(30)"])
            .cancel_on(token)
            .retry("transient_or_timeout", max_retries=5, initial_backoff=0.01)
        )
        task = asyncio.ensure_future(cmd.arun())
        await asyncio.sleep(0.2)
        token.cancel()
        with pytest.raises(Cancelled):
            await task

    asyncio.run(scenario())


# --- value semantics: __eq__/__hash__/pickle (T-041, T-079) ------------------
#
# Scope decision (documented here + in CHANGELOG.md): `ProcessResult`,
# `BytesResult`, `Outcome`, `Finished`, and `RunProfile` all get `__eq__`
# (the crate's own `PartialEq`, not `object`'s identity comparison) and, since
# none of their fields are stored floats, a consistent `__hash__`.
#
# Pickle is narrower, and only for the types that reconstruct *exactly* (T-079).
# `Outcome` and `Finished` support it: the crate has no public constructor for
# either, so unpickling reconstructs one via `testing.ScriptedRunner` (an
# in-memory, no-subprocess "run"), and that is faithful because an `Outcome` is
# fully determined by its Python-visible `code`/`signal`/`timed_out` and a
# `Finished` adds only its `stderr` (carried through verbatim).
#
# `ProcessResult` and `SupervisionOutcome` (tested in test_supervisor.py) do
# NOT pickle — they raise `TypeError`. Their equality (the crate's own
# comparison) also spans a command's configured `timeout` and accepted
# `success_codes`, two fields the crate exposes through no accessor: a pickle
# can't read them back, so a result from a command that set `.timeout(...)`/
# `.success_codes(...)` would unpickle unequal to its original. Rather than a
# silently-wrong round trip, both refuse loudly — pickle `result.outcome` (an
# `Outcome`) or persist the fields you need instead. `BytesResult` (raw bytes
# may not be valid UTF-8, and the reconstruction channel is text-only) and
# `RunProfile` (live OS resource-sampling telemetry has no synthesis path
# outside a real monitored run) likewise raise `TypeError`.


def test_process_result_eq_and_hash_compare_by_value() -> None:
    a = Command(PY, ["-c", "print('same')"]).output()
    b = Command(PY, ["-c", "print('same')"]).output()
    assert a is not b
    assert a == b
    assert hash(a) == hash(b)


def test_process_result_not_equal_when_a_field_differs() -> None:
    a = Command(PY, ["-c", "print('one')"]).output()
    b = Command(PY, ["-c", "print('two')"]).output()
    assert a != b


def test_process_result_eq_against_an_unrelated_type_is_false() -> None:
    # Comparing against a non-`ProcessResult` must return `False` (via the
    # `NotImplemented` protocol), not raise `TypeError`.
    result = Command(PY, ["-c", "print('x')"]).output()
    assert result != 5
    assert (result == "not a result") is False


def test_process_result_is_hashable_in_a_set_and_as_a_dict_key() -> None:
    a = Command(PY, ["-c", "print('same')"]).output()
    b = Command(PY, ["-c", "print('same')"]).output()
    assert {a, b} == {a}
    cache = {a: "cached"}
    assert cache[b] == "cached"


def test_process_result_pickle_raises_type_error() -> None:
    # ProcessResult is NOT picklable (T-079): its equality also spans the hidden
    # timeout/success_codes, which have no accessor to reconstruct, so a round
    # trip could not preserve `==`. Refuse loudly rather than hand back a value
    # that silently breaks the pickle invariant — pickle `result.outcome`
    # (an Outcome) or persist the fields you need instead.
    result = Command(PY, ["-c", "print('roundtrip')"]).output()
    with pytest.raises(TypeError, match="ProcessResult cannot be pickled"):
        pickle.dumps(result)


def test_process_result_pickle_refusal_is_config_independent() -> None:
    # The refusal does not depend on whether the command actually customized
    # timeout/success_codes — a plain command's result is unpicklable too, so
    # the contract ("ProcessResult is not picklable") is simple and total, not a
    # per-instance guess that would surprise callers.
    plain = Command(PY, ["-c", "print('plain')"]).output()
    customized = Command(PY, ["-c", "import sys; sys.exit(3)"]).success_codes([0, 3]).output()
    for result in (plain, customized):
        with pytest.raises(TypeError, match="ProcessResult cannot be pickled"):
            pickle.dumps(result)


def _summarize_in_worker_process() -> Outcome:
    # Runs *inside* the `ProcessPoolExecutor` worker: capture a result in one
    # process and hand its picklable `outcome` back across a real process
    # boundary (pickled on the way out, unpickled by the pool). This is the
    # documented migration path now that `ProcessResult` itself is not picklable
    # (T-079) — the exactly-reconstructable `Outcome` summary crosses the seam.
    return Command(PY, ["-c", "import sys; sys.exit(0)"]).output().outcome


def test_outcome_round_trips_through_a_real_process_pool_executor() -> None:
    # Force "spawn" explicitly rather than relying on the platform default.
    # The Rust extension starts a tokio runtime with background worker
    # threads on import; forking a multi-threaded process is unsafe (only the
    # forking thread survives in the child, so a lock held by another tokio
    # worker at fork time is stuck forever) and deadlocks the child the
    # moment it drives the async runtime again. Linux (pre-3.14) defaults to
    # "fork" for `ProcessPoolExecutor`, so this must be pinned to "spawn" to
    # avoid reintroducing that hang there; Windows/macOS/3.14 already default
    # to spawn-like behavior, which is why the hazard didn't show up there.
    mp_context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=mp_context) as pool:
        outcome = pool.submit(_summarize_in_worker_process).result(timeout=30)
    assert isinstance(outcome, Outcome)
    assert outcome.code == 0
    assert outcome.exited_zero
    assert not outcome.timed_out
    assert outcome.signal is None


def test_bytes_result_eq_and_hash_compare_by_value() -> None:
    code = "import sys; sys.stdout.buffer.write(b'same')"
    a = Command(PY, ["-c", code]).output_bytes()
    b = Command(PY, ["-c", code]).output_bytes()
    assert a == b
    assert hash(a) == hash(b)
    other_code = "import sys; sys.stdout.buffer.write(b'different')"
    c = Command(PY, ["-c", other_code]).output_bytes()
    assert a != c
    assert a != 5


def test_bytes_result_pickle_raises_type_error() -> None:
    # Raw stdout may not be valid UTF-8 and the only crate-sanctioned
    # reconstruction channel (`testing.Reply`) is text-only — an explicit,
    # documented refusal rather than a lossy/silent round trip.
    result = Command(PY, ["-c", "import sys; sys.stdout.buffer.write(b'x')"]).output_bytes()
    with pytest.raises(TypeError, match="BytesResult cannot be pickled"):
        pickle.dumps(result)


def test_outcome_eq_hash_and_pickle_round_trip() -> None:
    a = Command(PY, ["-c", "import sys; sys.exit(3)"]).output().outcome
    b = Command(PY, ["-c", "import sys; sys.exit(3)"]).output().outcome
    assert isinstance(a, Outcome)
    assert a == b
    assert hash(a) == hash(b)
    assert a != 5

    restored = pickle.loads(pickle.dumps(a))
    assert restored == a
    assert restored.code == 3
    assert not restored.timed_out
    assert restored.signal is None


@pytest.mark.parametrize(
    ("reply", "expect_code", "expect_signal", "expect_timed_out"),
    [
        (Reply.ok("done"), 0, None, False),
        (Reply.fail(3, "boom"), 3, None, False),
        (Reply.signalled(None), None, None, False),
        (Reply.signalled(9), None, 9, False),
        (Reply.timeout(), None, None, True),
    ],
    ids=["exited_zero", "exited_nonzero", "signalled_unknown", "signalled_9", "timed_out"],
)
def test_outcome_pickle_round_trip_over_every_outcome_kind(
    reply: Reply,
    expect_code: int | None,
    expect_signal: int | None,
    expect_timed_out: bool,
) -> None:
    # An Outcome is fully determined by (code, signal, timed_out), all
    # Python-visible, so it round-trips exactly for every terminal disposition —
    # exactly why Outcome pickles while ProcessResult (whose identity also spans
    # the accessor-less timeout/success_codes) does not. A ScriptedRunner
    # produces each disposition hermetically (no real process, and cross-platform
    # — the fake reports Signalled even on Windows).
    scripted = ScriptedRunner()
    scripted.fallback(reply)
    original = scripted.output(Command("tool")).outcome
    assert isinstance(original, Outcome)
    assert original.code == expect_code
    assert original.signal == expect_signal
    assert original.timed_out == expect_timed_out

    restored = pickle.loads(pickle.dumps(original))
    assert restored == original
    assert hash(restored) == hash(original)
    assert restored.code == expect_code
    assert restored.signal == expect_signal
    assert restored.timed_out == expect_timed_out


def test_finished_eq_hash_and_pickle_round_trip() -> None:
    async def scenario() -> Finished:
        code = "import sys; print('out'); print('e1', file=sys.stderr)"
        proc = await Command(PY, ["-c", code]).astart()
        async for _line in proc.stdout_lines():
            pass
        return await proc.afinish()

    a = asyncio.run(scenario())
    b = asyncio.run(scenario())
    assert isinstance(a, Finished)
    assert a == b
    assert hash(a) == hash(b)
    assert a != 5

    restored = pickle.loads(pickle.dumps(a))
    assert restored == a
    assert restored.code == 0
    assert restored.stderr == a.stderr == "e1"


def test_finished_pickle_round_trip_carries_nonzero_outcome_and_stderr() -> None:
    # Finished reconstructs its outcome via the same exact `scripted_outcome`
    # path Outcome uses, and carries `stderr` through verbatim — so a non-zero
    # exit with captured stderr round-trips exactly too.
    async def scenario() -> Finished:
        code = "import sys; print('e2', file=sys.stderr); sys.exit(3)"
        proc = await Command(PY, ["-c", code]).astart()
        async for _line in proc.stdout_lines():
            pass
        return await proc.afinish()

    original = asyncio.run(scenario())
    restored = pickle.loads(pickle.dumps(original))
    assert restored == original
    assert hash(restored) == hash(original)
    assert restored.code == 3
    assert not restored.exited_zero
    assert restored.stderr == original.stderr == "e2"


def test_run_profile_eq_is_value_based_not_identity() -> None:
    quick = Command(PY, ["-c", "pass"]).start().profile(1.0)
    slow = Command(PY, ["-c", "import time; time.sleep(0.2)"]).start().profile(0.02)
    assert isinstance(quick, RunProfile)
    assert quick != slow
    assert quick == quick  # pins reflexive value equality
    assert hash(quick) == hash(quick)
    assert quick != 5


def test_run_profile_pickle_raises_type_error() -> None:
    # Live OS resource-sampling telemetry (cpu_time/peak_memory/samples) has no
    # synthesis path outside an actual monitored run — an explicit, documented
    # refusal rather than fabricating/discarding the numbers.
    proc = Command(PY, ["-c", "import time; time.sleep(0.1)"]).start()
    profile = proc.profile(0.02)
    with pytest.raises(TypeError, match="RunProfile cannot be pickled"):
        pickle.dumps(profile)


# --- value semantics: OutputEvent (T-151) ------------------------------------
#
# `OutputEvent` completes the value-type family above: it gets `__eq__`/`__hash__`
# over its two exact fields (`is_stderr`/`text`) and — unlike ProcessResult /
# BytesResult / RunProfile — supports pickle with an exact round trip. It is the
# simplest picklable type here: it wraps no crate value (it derives and keeps its
# own pair in `from_event`), so unpickling is a plain field copy, no
# `ScriptedRunner` detour. Only produced by streaming, so these collect real
# events off `output_events()`.


def _output_events(code: str) -> list[OutputEvent]:
    async def scenario() -> list[OutputEvent]:
        proc = await Command(PY, ["-c", code]).astart()
        events = [event async for event in proc.output_events()]
        await proc.aoutcome()
        return events

    return asyncio.run(scenario())


def test_output_event_eq_and_hash_compare_by_value() -> None:
    # Same single stdout line from two independent runs -> two distinct objects
    # that compare equal by value (and hash consistently), not by identity.
    first = _output_events("print('same-line')")
    second = _output_events("print('same-line')")
    assert first == second  # element-wise OutputEvent.__eq__
    a, b = first[0], second[0]
    assert isinstance(a, OutputEvent)
    assert a is not b
    assert a == b
    assert hash(a) == hash(b)


def test_output_event_not_equal_when_a_field_differs() -> None:
    # Differ by `text`.
    a = _output_events("print('one')")[0]
    b = _output_events("print('two')")[0]
    assert a != b

    # Differ only by `stream`/`is_stderr`: identical text, opposite stream, so
    # still unequal (both fields participate in equality, not just the text).
    on_stdout = _output_events("print('x')")[0]
    on_stderr = _output_events("import sys; print('x', file=sys.stderr)")[0]
    assert on_stdout.text == on_stderr.text
    assert on_stdout.is_stderr != on_stderr.is_stderr
    assert on_stdout != on_stderr


def test_output_event_eq_against_an_unrelated_type_is_false() -> None:
    # Comparing against a non-`OutputEvent` must return `False` (via the
    # `NotImplemented` protocol), not raise `TypeError`.
    event = _output_events("print('x')")[0]
    assert event != 5
    assert (event == "not an event") is False


def test_output_event_is_hashable_in_a_set_and_as_a_dict_key() -> None:
    a = _output_events("print('same')")[0]
    b = _output_events("print('same')")[0]
    assert {a, b} == {a}
    cache = {a: "cached"}
    assert cache[b] == "cached"


def test_output_event_pickle_round_trip() -> None:
    # Unlike ProcessResult/BytesResult/RunProfile (which refuse), OutputEvent
    # round-trips exactly: it stores its own two exact fields directly, so
    # reconstruction is a plain field copy — text is already decoded, so nothing
    # can fail to reconstruct. Cover both streams (stdout and stderr) so the
    # `is_stderr` half round-trips too.
    on_stdout = _output_events("print('round-trip')")[0]
    on_stderr = _output_events("import sys; print('to-stderr', file=sys.stderr)")[0]
    for original in (on_stdout, on_stderr):
        restored = pickle.loads(pickle.dumps(original))
        assert isinstance(restored, OutputEvent)
        assert restored == original
        assert hash(restored) == hash(original)
        assert restored.stream == original.stream
        assert restored.is_stderr == original.is_stderr
        assert restored.text == original.text
