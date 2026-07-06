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
import json
import os
import pathlib
import sys

import pytest

from processkit import (
    BytesResult,
    CancellationToken,
    Cancelled,
    Command,
    NonZeroExit,
    OutputTooLarge,
    PermissionDenied,
    Priority,
    ProcessError,
    ProcessNotFound,
    Timeout,
    Unsupported,
)

from .conftest import NO_SUCH_PROGRAM, PY


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


def test_builder_chaining_returns_new_command() -> None:
    base = Command(PY)
    chained = base.arg("-c").arg("print(1 + 1)")
    assert chained.output().stdout.strip() == "2"
    # The original is untouched (builder methods return a new Command). The
    # redacted repr shows the arg COUNT (not values), still 0 on the base.
    assert "args: 0" in repr(base)


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
    # `BytesResult.truncated` tracks only *stderr* capping — raw stdout bytes
    # are never line-capped (see the stub's `truncated` docstring) — so an
    # output_limit breach must still surface via stderr overflow.
    code = "import sys\nfor i in range(1000):\n    sys.stderr.write('x' * 80 + chr(10))"
    result = Command(PY, ["-c", code]).output_limit(max_lines=10).output_bytes()
    assert result.is_success
    assert result.truncated


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


# --- stdout/stderr redirection ----------------------------------------------


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


# --- lifetime / redirect / privilege knobs ----------------------------------


def test_builder_knobs_chain_builds() -> None:
    # Every lifetime / redirect / privilege knob builds into a valid Command.
    cmd = (
        Command(PY, ["-c", "print('ok')"])
        .kill_on_parent_death()
        .create_no_window()
        .timeout_grace(0.5)
        .timeout_signal("term")
        .uid(0)
        .gid(0)
        .groups([0])
        .setsid()
        .umask(0o022)
        .priority("normal")
    )
    assert isinstance(cmd, Command)
    # The cross-platform lifetime knobs actually run.
    assert "ok" in Command(PY, ["-c", "print('ok')"]).kill_on_parent_death().run()


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


def test_priority_rejects_unknown_preset() -> None:
    with pytest.raises(ValueError, match="priority"):
        Command(PY, ["-c", "print(1)"]).priority("bogus")  # type: ignore[arg-type]


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
    import ctypes

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
        # PROCESS_QUERY_LIMITED_INFORMATION — enough to read the priority class.
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, proc.pid)
        assert handle, "OpenProcess failed"
        try:
            got = ctypes.windll.kernel32.GetPriorityClass(handle)
            assert got == priority_class, f"expected {priority_class:#x}, got {got:#x}"
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
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


def test_unchecked_in_pipe_is_a_noop_outside_a_pipeline() -> None:
    # Outside a Pipeline, unchecked_in_pipe() has no effect: a single run's
    # status is already plain data, and success_codes/ensure_success are
    # unaffected either way.
    result = Command(PY, ["-c", "import sys; sys.exit(1)"]).unchecked_in_pipe().output()
    assert not result.is_success
    assert result.code == 1


# --- ensure_success (C7 batch A) ---------------------------------------------


def test_ensure_success_returns_self_on_success() -> None:
    result = Command(PY, ["-c", "print('ok')"]).output()
    same = result.ensure_success()
    assert same.stdout.strip() == "ok"
    assert same is not None


def test_ensure_success_raises_on_failure() -> None:
    result = Command(PY, ["-c", "import sys; sys.exit(3)"]).output()
    with pytest.raises(NonZeroExit) as excinfo:
        result.ensure_success()
    assert excinfo.value.code == 3


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
    other_child.cancel()
    assert other_child.is_cancelled()
    assert not other_parent.is_cancelled()


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
