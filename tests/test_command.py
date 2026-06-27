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
import os
import pathlib
import sys

import pytest

from processkit import (
    BytesResult,
    Command,
    NonZeroExit,
    OutputTooLarge,
    ProcessError,
    ProcessNotFound,
    Timeout,
    Unsupported,
)

PY = sys.executable


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
        Command("processkit-no-such-binary-xyzzy").output()


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


def test_env_remove_drops_inherited() -> None:
    os.environ["PK_REMOVE_ME"] = "parent"
    try:
        out = (
            Command(PY, ["-c", "import os; print(os.environ.get('PK_REMOVE_ME', 'GONE'))"])
            .env_remove("PK_REMOVE_ME")
            .run()
        )
        assert out == "GONE"
    finally:
        del os.environ["PK_REMOVE_ME"]


def test_env_clear_starts_from_empty() -> None:
    os.environ["PK_CLEAR_MARKER"] = "parent"
    try:
        cmd = Command(
            PY, ["-c", "import os; print(os.environ.get('PK_CLEAR_MARKER', 'GONE'))"]
        ).env_clear()
        # The interpreter needs SystemRoot to spawn on Windows; re-add just that
        # (env var names are case-insensitive on Windows).
        if sys.platform == "win32":
            cmd = cmd.env("SYSTEMROOT", os.environ.get("SYSTEMROOT", r"C:\Windows"))
        assert cmd.run() == "GONE"
    finally:
        del os.environ["PK_CLEAR_MARKER"]


def test_inherit_env_filters_to_allowlist() -> None:
    os.environ["PK_KEEP"] = "kept"
    os.environ["PK_DROP"] = "dropped"
    try:
        code = "import os; print(os.environ.get('PK_KEEP', '-'), os.environ.get('PK_DROP', '-'))"
        cmd = Command(PY, ["-c", code]).env_clear().inherit_env(["PK_KEEP"])
        if sys.platform == "win32":
            cmd = cmd.env("SYSTEMROOT", os.environ.get("SYSTEMROOT", r"C:\Windows"))
        assert cmd.run() == "kept -"
    finally:
        del os.environ["PK_KEEP"]
        del os.environ["PK_DROP"]


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
    assert excinfo.value.line_limit == 10
    assert excinfo.value.total_lines >= 1000


def test_output_limit_truncate_marks_truncated() -> None:
    code = "import sys\nfor i in range(1000):\n    print('x' * 80)"
    result = Command(PY, ["-c", code]).output_limit(max_lines=10).output()
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


# --- stdout/stderr redirection ----------------------------------------------


def test_stdout_null_rejects_capture_verbs() -> None:
    # null/inherit are non-capturing: the one-shot capture verbs error clearly
    # rather than silently returning empty output.
    with pytest.raises(ProcessError):
        Command(PY, ["-c", "print('hidden')"]).stdout("null").output()


def test_stdout_null_works_with_start_then_wait() -> None:
    async def scenario() -> int | None:
        proc = await Command(PY, ["-c", "print('hidden')"]).stdout("null").astart()
        return (await proc.wait()).code

    assert asyncio.run(scenario()) == 0


def test_stdout_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        # An invalid mode is the point of the test; mypy would flag the literal.
        Command(PY, ["-c", "pass"]).stdout("bogus")  # type: ignore[arg-type]


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
    )
    assert isinstance(cmd, Command)
    # The cross-platform lifetime knobs actually run.
    assert "ok" in Command(PY, ["-c", "print('ok')"]).kill_on_parent_death().run()


@pytest.mark.skipif(
    sys.platform != "win32", reason="privilege-drop behavior is POSIX-specific / root-dependent"
)
def test_privilege_drop_unsupported_on_windows() -> None:
    # Privilege drops are never silently skipped: on Windows the run raises.
    with pytest.raises(Unsupported) as excinfo:
        Command(PY, ["-c", "print('x')"]).uid(0).run()
    # The structured `.operation` field names what wasn't supported.
    assert excinfo.value.operation


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM trapping is POSIX-specific")
def test_timeout_grace_delivers_signal_before_kill(tmp_path: pathlib.Path) -> None:
    # On timeout the configured signal is sent and the grace window is honored: a
    # child that traps SIGTERM runs its handler before any hard kill.
    marker = tmp_path / "got_term"
    code = (
        "import signal, sys, time\n"
        "def handler(*_):\n"
        f"    open({str(marker)!r}, 'w').write('x')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, handler)\n"
        "time.sleep(30)\n"
    )
    Command(PY, ["-c", code]).timeout(0.3).timeout_signal("term").timeout_grace(3.0).output()
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
