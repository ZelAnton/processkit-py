"""`python -m processkit run -- ...` — the CLI wrapper (`src/processkit/__main__.py`,
delegating to the private `src/processkit/_cli/` package).

Every test here spawns a **real** `sys.executable -m processkit ...` subprocess
rather than importing `processkit._cli` and calling `main()` directly: the
whole point under test is argv parsing and process exit-code plumbing, neither
of which a direct import would actually exercise (an in-process call can't
observe `sys.exit()`/the real process exit code the way a subprocess round
trip does).
"""

from __future__ import annotations

import json
import os
import pathlib
import signal
import socket
import subprocess
import sys

from .conftest import NO_SUCH_PROGRAM, PY

#: Generous but bounded — these are short-lived child interpreters; a hang
#: here means the CLI itself is stuck, which should fail loud, not time out
#: the whole test session.
_SUBPROCESS_TIMEOUT = 30


def _run_cli(
    *args: str, env: dict[str, str] | None = None, input: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PY, "-m", "processkit", *args],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
        env=env,
        input=input,
    )


def _parent_env_with(**extra: str) -> dict[str, str]:
    """This test process's own environment, plus marker variables — the
    "parent" environment the CLI subprocess (and, in turn, its own child) is
    launched with, for the `--env-clear`/`--inherit-env` tests below."""
    env = os.environ.copy()
    env.update(extra)
    return env


def test_top_level_help_does_not_raise() -> None:
    result = _run_cli("--help")
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
    assert "Traceback (most recent call last)" not in result.stderr


def test_run_help_does_not_raise() -> None:
    result = _run_cli("run", "--help")
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
    assert "--timeout" in result.stdout
    assert "--profile" in result.stdout
    assert "--create-no-window" in result.stdout
    assert "--output-limit" in result.stdout
    assert "--stdout-file" in result.stdout
    assert "--stderr-file" in result.stdout
    assert "--kill-on-parent-death" in result.stdout
    assert "--priority" in result.stdout
    assert "--io-priority" in result.stdout
    assert "--pty" in result.stdout
    assert "--pty-cols" in result.stdout
    assert "--pty-rows" in result.stdout
    assert "--env-file" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_successful_run_exits_zero_and_streams_stdout() -> None:
    result = _run_cli("run", "--", PY, "-c", "print('hello from child')")
    assert result.returncode == 0
    assert "hello from child" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_run_passes_piped_stdin_to_the_child() -> None:
    payload = "first line\nsecond line\n"
    result = _run_cli(
        "run",
        "--",
        PY,
        "-c",
        "import sys; print(sys.stdin.read(), end='')",
        input=payload,
    )
    assert result.returncode == 0
    assert result.stdout == payload
    assert "Traceback (most recent call last)" not in result.stderr


def test_nonzero_child_exit_code_is_passed_through_unchanged() -> None:
    result = _run_cli("run", "--", PY, "-c", "import sys; sys.exit(7)")
    assert result.returncode == 7
    assert "Traceback (most recent call last)" not in result.stderr


def test_timeout_gives_predictable_exit_code_and_stderr_message() -> None:
    result = _run_cli(
        "run",
        "--timeout",
        "0.5",
        "--",
        PY,
        "-c",
        "import time; time.sleep(30)",
    )
    assert result.returncode == 124
    assert "timed out" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_missing_program_gives_predictable_exit_code_and_stderr_message() -> None:
    result = _run_cli("run", "--", NO_SUCH_PROGRAM)
    assert result.returncode == 127
    assert "not found" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_idle_timeout_gives_its_own_exit_code_distinct_from_wall_clock_timeout() -> None:
    # A child that prints once then goes silent trips --idle-timeout: exit 123
    # (deliberately NOT 124, the wall-clock --timeout code), a one-line message,
    # never a traceback. The one stdout line it did emit is re-streamed.
    result = _run_cli(
        "run",
        "--idle-timeout",
        "2",
        "--",
        PY,
        "-c",
        "import time; print('hi', flush=True); time.sleep(30)",
    )
    assert result.returncode == 123
    assert "idle" in result.stderr.lower()
    assert "hi" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_idle_timeout_lets_a_chatty_child_finish_and_passes_its_code_through() -> None:
    # Output keeps flowing well within the idle window, so it never trips; the
    # child exits normally and its code passes through, with every line
    # re-emitted (decoded, line by line) by the streaming path.
    code = (
        "import time\n"
        "for i in range(3):\n"
        "    print('line', i, flush=True)\n"
        "    time.sleep(0.1)\n"
        "import sys; sys.exit(0)\n"
    )
    result = _run_cli("run", "--idle-timeout", "2", "--", PY, "-c", code)
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["line 0", "line 1", "line 2"]
    assert "Traceback (most recent call last)" not in result.stderr
    # The `== 0` above is load-bearing beyond the exit-code passthrough it
    # reads as: this exact invocation intermittently returned -11 (SIGSEGV)
    # from the *wrapper* — all three lines already streamed, stderr empty — in
    # a teardown race at interpreter finalization. The bridge now completes on
    # the loop thread, and the stress coverage in test_hardening exercises this
    # same last-await shape under load.


def test_cli_runs_interpreter_finalization_after_async_bridge_is_done() -> None:
    """The root bridge fix restores ordinary CLI interpreter shutdown.

    The temporary T-161 workaround used ``os._exit`` to avoid finalization
    while a detached completion thread might still be inside Python. The
    completion now runs on the event-loop thread, so the wrapper can use
    `SystemExit` again. This probe arms an `atexit` hook around the one CLI path
    that drives the async surface and proves normal finalization really runs.
    """
    probe = (
        "import atexit, runpy, sys\n"
        "atexit.register(lambda: sys.stderr.write('FINALIZATION-RAN\\n'))\n"
        # This test proves finalization, not process-start latency. Leave enough
        # idle headroom for a child interpreter to start under full xdist load;
        # the outer subprocess timeout still bounds a genuine hang at 30 seconds.
        f"sys.argv = ['processkit', 'run', '--idle-timeout', '15', '--', {PY!r}, "
        "'-c', 'print(\"from child\", flush=True)']\n"
        "runpy.run_module('processkit', run_name='__main__')\n"
        "sys.stderr.write('RETURNED-TO-CALLER\\n')\n"
    )
    result = subprocess.run(
        [PY, "-c", probe],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["from child"]
    assert result.stderr == "FINALIZATION-RAN\n"
    assert "RETURNED-TO-CALLER" not in result.stderr


def test_idle_timeout_streams_more_output_than_one_stdio_buffer() -> None:
    """The explicit final flush delivers block-buffered redirected output.

    The child emits far more than one 8 KiB stdio buffer through the re-emitting
    ``--idle-timeout`` path, and every line must arrive before `SystemExit`.
    """
    lines = 3000
    code = f"for i in range({lines}):\n    print('line', i, flush=True)\n"
    result = _run_cli("run", "--idle-timeout", "10", "--", PY, "-c", code)
    assert result.returncode == 0
    assert result.stdout.splitlines() == [f"line {i}" for i in range(lines)]
    assert "Traceback (most recent call last)" not in result.stderr


def test_intermediate_broken_pipe_is_silent_and_preserves_the_cli_verdict() -> None:
    probe = (
        "import runpy, sys\n"
        "class _BrokenPipe:\n"
        "    def write(self, text): raise BrokenPipeError()\n"
        "    def flush(self): pass\n"
        "sys.stdout = _BrokenPipe()\n"
        "sys.argv = ['processkit', 'doctor']\n"
        "runpy.run_module('processkit', run_name='__main__')\n"
    )
    result = subprocess.run(
        [PY, "-c", probe],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode in (0, 1, 3, 4)
    assert result.stderr == ""


def test_intermediate_output_oserror_exits_119_without_a_traceback() -> None:
    probe = (
        "import runpy, sys\n"
        "class _FailedOutput:\n"
        "    def write(self, text): raise OSError(5, 'I/O error')\n"
        "    def flush(self): pass\n"
        "sys.stdout = _FailedOutput()\n"
        "sys.argv = ['processkit', 'doctor']\n"
        "runpy.run_module('processkit', run_name='__main__')\n"
    )
    result = subprocess.run(
        [PY, "-c", probe],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 119
    assert "could not write stdout" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_failed_final_flush_is_reported_instead_of_a_clean_exit_code() -> None:
    """A final flush that *lost* output must not exit as if the run were fine.

    The wrapper checks its own final flush before `SystemExit`, and swallowing
    a failure there would report
    the child's own exit code for a run whose output was silently truncated (a
    full or failing disk, a stream closed underneath it). The
    ordinary interpreter shutdown is loud about exactly that failure too:
    CPython prints ``Exception ignored`` and can turn the status into 120. The
    explicit check stays loud in this CLI's vocabulary — exit 119
    (`EXIT_OUTPUT_LOST`) and one line on
    stderr, never the child's 0 (which here would be a *false success*, the
    most dangerous direction for a wrapper whose only contract is an exact
    exit code plus a faithful output relay).

    A vanished receiver (`BrokenPipeError`, e.g. ``... | head``) is
    deliberately not this case and stays silent — see
    `test_broken_stdout_pipe_still_reports_the_child_code` below.
    """
    probe = (
        "import runpy, sys\n"
        "class _FullDisk:\n"
        "    def __init__(self, wrapped): self._wrapped = wrapped\n"
        "    def __getattr__(self, name): return getattr(self._wrapped, name)\n"
        "    def flush(self): raise OSError(28, 'No space left on device')\n"
        "sys.stdout = _FullDisk(sys.stdout)\n"
        f"sys.argv = ['processkit', 'run', '--', {PY!r}, '-c', 'raise SystemExit(0)']\n"
        "runpy.run_module('processkit', run_name='__main__')\n"
    )
    result = subprocess.run(
        [PY, "-c", probe],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 119
    assert "processkit: could not flush stdout" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_broken_stdout_pipe_still_reports_the_child_code() -> None:
    """The other half of the flush contract: a receiver that already walked
    away is *not* an error.

    No exit code can deliver output to a closed pipe, and ``python -m
    processkit run ... | head`` is an ordinary way to use this wrapper — so a
    `BrokenPipeError` from the final flush stays silent and the child's own
    code still comes through, exactly as it did when interpreter shutdown
    performed that flush.
    """
    probe = (
        "import runpy, sys\n"
        "class _BrokenPipe:\n"
        "    def __init__(self, wrapped): self._wrapped = wrapped\n"
        "    def __getattr__(self, name): return getattr(self._wrapped, name)\n"
        "    def flush(self): raise BrokenPipeError(32, 'Broken pipe')\n"
        "sys.stdout = _BrokenPipe(sys.stdout)\n"
        f"sys.argv = ['processkit', 'run', '--', {PY!r}, '-c', 'raise SystemExit(3)']\n"
        "runpy.run_module('processkit', run_name='__main__')\n"
    )
    result = subprocess.run(
        [PY, "-c", probe],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 3
    assert result.stderr == ""


def test_child_exit_code_survives_absent_standard_streams() -> None:
    """`sys.stdout` / `sys.stderr` are `None` whenever the interpreter has no
    usable standard streams — ``pythonw.exe`` on Windows, a service or
    launcher that closed fd 0-2 before exec, an embedded interpreter. The CLI
    itself works in that configuration (`print` to a `None` stream is a
    no-op), so the exit path must not be the one thing that breaks there: an
    `AttributeError` out of ``None.flush()`` would lose the child's documented
    exit code.
    CPython's own shutdown flush (``flush_std_files``) skips a `None` stream
    for the same reason.
    """
    probe = (
        "import runpy, sys\n"
        f"sys.argv = ['processkit', 'run', '--', {PY!r}, '-c', 'raise SystemExit(7)']\n"
        "sys.stdout = sys.stderr = None\n"
        "runpy.run_module('processkit', run_name='__main__')\n"
    )
    result = subprocess.run(
        [PY, "-c", probe],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 7


def test_out_of_range_exit_status_does_not_escape_the_exit_path() -> None:
    """The final `SystemExit` receives a normalized, portable status.

    No subcommand produces an out-of-range status today, so the probe supplies
    one directly; what is pinned is that the wrapper folds it the way the OS
    would (low 32 bits: ``2**40 + 7`` → ``7``) instead of leaving the result to
    platform-specific overflow behavior.
    """
    probe = (
        "import runpy, sys\n"
        "import processkit._cli as cli\n"
        "cli._doctor = lambda *args, **kwargs: 2**40 + 7\n"
        "sys.argv = ['processkit', 'doctor']\n"
        "runpy.run_module('processkit', run_name='__main__')\n"
    )
    result = subprocess.run(
        [PY, "-c", probe],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 7
    assert "Traceback (most recent call last)" not in result.stderr


def test_interrupt_outside_a_guarded_block_exits_128_plus_sigint() -> None:
    """Ctrl+C anywhere in the entry point reports the documented
    ``128 + SIGINT``, not a traceback and exit 1.

    ``run`` and ``supervise`` catch `KeyboardInterrupt` around their own
    blocks, but an interrupt during imports, argparse, or `doctor` lands
    outside all of them. For `doctor` the generic traceback-and-1 fallback
    would be worse than untidy:
    1 is a *valid* `doctor` verdict ("containment enforced, limits not"), so
    an interrupted probe would be indistinguishable from a DEGRADED answer to
    the CI gate reading that code.

    The interrupt is injected by making the `doctor` implementation raise
    `KeyboardInterrupt` — precisely what CPython's SIGINT handler does at that
    point — because delivering a real Ctrl+C to a child process is
    platform-specific (Windows has no per-process SIGINT), while the code path
    under test is identical either way.
    """
    probe = (
        "import runpy, sys\n"
        "import processkit._cli as cli\n"
        "def _interrupt(*args, **kwargs):\n"
        "    raise KeyboardInterrupt\n"
        "cli._doctor = _interrupt\n"
        "sys.argv = ['processkit', 'doctor']\n"
        "runpy.run_module('processkit', run_name='__main__')\n"
    )
    result = subprocess.run(
        [PY, "-c", probe],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 128 + signal.SIGINT
    assert "processkit: interrupted" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_idle_timeout_with_profile_is_a_usage_error() -> None:
    # The two need incompatible consuming verbs on the one handle, so the combo
    # is rejected up front as a usage error (exit 2), not silently.
    result = _run_cli("run", "--idle-timeout", "1", "--profile", "--", PY, "-c", "print(1)")
    assert result.returncode == 2
    assert "--idle-timeout cannot be combined with --profile" in result.stderr
    assert "usage: python -m processkit run" in result.stderr


def test_idle_timeout_rejects_nonpositive_value_as_usage_error() -> None:
    # Shares the parser's _positive_float type with --timeout, so 0/negative are
    # argparse usage errors (exit 2), never a spawned child.
    result = _run_cli("run", "--idle-timeout", "0", "--", PY, "-c", "print(1)")
    assert result.returncode == 2
    assert "positive number" in result.stderr


def test_timeout_grace_without_timeout_is_a_usage_error() -> None:
    result = _run_cli("run", "--timeout-grace", "1", "--", PY, "-c", "print(1)")
    assert result.returncode == 2
    assert "--timeout-grace requires --timeout" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_missing_command_after_run_is_a_usage_error() -> None:
    result = _run_cli("run", "--timeout", "1")
    assert result.returncode == 2
    assert "missing command" in result.stderr
    # Must be the `run` subparser's usage line (mentions its own flags), not
    # the top-level `usage: python -m processkit [-h] {run} ...` — regression
    # guard for reporting via `run_parser.error(...)` instead of `parser.error(...)`.
    assert "usage: python -m processkit run" in result.stderr
    assert "--timeout" in result.stderr
    assert "usage: python -m processkit [-h]" not in result.stderr


def test_fallback_process_group_failure_is_reported_not_raised() -> None:
    # Simulates the "should not happen on any supported platform" case: even
    # the plain, uncapped `ProcessGroup()` fallback (after a rejected
    # resource-limit request) raises `Unsupported`. This must still surface
    # as `_fail(...)` + exit 125, never an unhandled traceback — the same
    # contract the sibling `not limits_requested` branch already has.
    script = (
        "import sys\n"
        "import processkit\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.run as run_mod\n"
        "class _AlwaysUnsupported:\n"
        "    def __init__(self, *a, **k):\n"
        "        raise processkit.Unsupported('containment is unavailable')\n"
        "run_mod.ProcessGroup = _AlwaysUnsupported\n"
        "sys.exit(cli.main(['run', '--max-memory', '1', '--', 'irrelevant']))\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 125
    assert len(result.stderr.strip().splitlines()) == 1
    assert "containment is unavailable" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_process_group_operational_errors_are_reported_not_raised() -> None:
    # An OSError means containment probing failed operationally (for example,
    # cgroup state could not be read), not that requested limits are known to
    # be unsupported. Cover both the initially capped construction and its
    # uncapped fallback so neither path can leak a traceback.
    # _supervise (src/processkit/_cli/supervise.py) was checked: it has no
    # ProcessGroup(...) constructor of its own, so no equivalent OSError
    # handling is needed there.
    cases = (
        (
            "_OperationalFailure",
            "class _OperationalFailure:\n"
            "    def __init__(self, *a, **k):\n"
            "        raise OSError('cannot read containment state')\n",
            ["run", "--", "irrelevant"],
            "cannot read containment state",
        ),
        (
            "_FallbackOperationalFailure",
            "class _FallbackOperationalFailure:\n"
            "    def __init__(self, *a, **k):\n"
            "        if k:\n"
            "            raise processkit.ResourceLimit('limit not delegated')\n"
            "        raise OSError('cannot create containment group')\n",
            ["run", "--max-memory", "1", "--", "irrelevant"],
            "cannot create containment group",
        ),
    )
    for mock_class_name, mock_class_body, argv, error_message in cases:
        script = (
            "import sys\n"
            "import processkit\n"
            "import processkit._cli as cli\n"
            "import processkit._cli.run as run_mod\n"
            f"{mock_class_body}"
            f"run_mod.ProcessGroup = {mock_class_name}\n"
            f"sys.exit(cli.main({argv!r}))\n"
        )
        result = subprocess.run(
            [PY, "-c", script],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
        assert result.returncode == 125
        assert len(result.stderr.strip().splitlines()) == 1
        assert "could not initialize containment in this environment" in result.stderr
        assert error_message in result.stderr
        assert "OSError" not in result.stderr
        assert "Traceback (most recent call last)" not in result.stderr


def test_double_dash_inside_child_argv_is_passed_through_verbatim() -> None:
    # Only the *first* "--" is this wrapper's separator; a further one belongs
    # to the child's own argv, untouched.
    result = _run_cli(
        "run",
        "--",
        PY,
        "-c",
        "import sys; print(sys.argv[1:])",
        "--",
        "foo",
    )
    assert result.returncode == 0
    assert "['--', 'foo']" in result.stdout


# --- environment and cwd flags -----------------------------------------------


def test_env_clear_strips_the_parent_environment() -> None:
    # The marker is set on the CLI subprocess's own environment (its
    # "parent", from the child's point of view) so a real --env-clear must
    # make it disappear from the grandchild's environment.
    parent_env = _parent_env_with(PK_CLI_MARKER="present")
    args = ["run", "--env-clear"]
    if sys.platform == "win32":
        # The interpreter needs SystemRoot to spawn at all on Windows
        # (env var names are case-insensitive there); re-add just that.
        systemroot = os.environ.get("SYSTEMROOT", r"C:\Windows")
        args += ["--env", f"SYSTEMROOT={systemroot}"]
    args += ["--", PY, "-c", "import os; print(os.environ.get('PK_CLI_MARKER', 'GONE'))"]
    result = _run_cli(*args, env=parent_env)
    assert result.returncode == 0
    assert result.stdout.strip() == "GONE"
    assert "Traceback (most recent call last)" not in result.stderr


def test_inherit_env_allowlists_only_the_named_variable() -> None:
    parent_env = _parent_env_with(PK_CLI_KEEP="kept", PK_CLI_DROP="dropped")
    args = ["run", "--inherit-env", "PK_CLI_KEEP"]
    if sys.platform == "win32":
        args += ["--inherit-env", "SYSTEMROOT"]
    code = (
        "import os; print(os.environ.get('PK_CLI_KEEP', '-'), os.environ.get('PK_CLI_DROP', '-'))"
    )
    args += ["--", PY, "-c", code]
    result = _run_cli(*args, env=parent_env)
    assert result.returncode == 0
    assert result.stdout.strip() == "kept -"
    assert "Traceback (most recent call last)" not in result.stderr


def test_env_flag_sets_a_child_variable() -> None:
    result = _run_cli(
        "run",
        "--env",
        "PK_CLI_ENV=applied",
        "--",
        PY,
        "-c",
        "import os; print(os.environ.get('PK_CLI_ENV', 'unset'))",
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "applied"
    assert "Traceback (most recent call last)" not in result.stderr


def test_env_flag_without_equals_is_a_usage_error() -> None:
    result = _run_cli("run", "--env", "NOEQUALSHERE", "--", PY, "-c", "print(1)")
    assert result.returncode == 2
    assert "--env" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_env_flag_with_empty_key_is_a_usage_error() -> None:
    result = _run_cli("run", "--env", "=VALUE", "--", PY, "-c", "print(1)")
    assert result.returncode == 2
    assert "key must not be empty" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_env_file_loads_entries_and_explicit_env_wins(tmp_path: pathlib.Path) -> None:
    env_file = tmp_path / "build.env"
    env_file.write_text(
        "\ufeff# build settings\n\nPK_FILE_ONLY=from-file\nPK_OVERRIDE=from-file\n"
        "PK_WITH_EQUALS=left=right\n",
        encoding="utf-8",
    )
    code = (
        "import os; print(os.environ['PK_FILE_ONLY'], os.environ['PK_OVERRIDE'], "
        "os.environ['PK_WITH_EQUALS'])"
    )
    result = _run_cli(
        "run",
        "--env-file",
        str(env_file),
        "--env",
        "PK_OVERRIDE=explicit",
        "--",
        PY,
        "-c",
        code,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "from-file explicit left=right"
    assert "Traceback (most recent call last)" not in result.stderr


def test_later_env_file_overrides_an_earlier_file(tmp_path: pathlib.Path) -> None:
    first = tmp_path / "first.env"
    second = tmp_path / "second.env"
    first.write_text("PK_ORDER=first\n", encoding="utf-8")
    second.write_text("PK_ORDER=second\n", encoding="utf-8")
    result = _run_cli(
        "run",
        "--env-file",
        str(first),
        "--env-file",
        str(second),
        "--",
        PY,
        "-c",
        "import os; print(os.environ['PK_ORDER'])",
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "second"


def test_env_file_errors_are_usage_diagnostics_without_tracebacks(
    tmp_path: pathlib.Path,
) -> None:
    malformed = tmp_path / "bad.env"
    malformed.write_text("GOOD=value\nnot-a-pair\n", encoding="utf-8")
    for path, expected in [
        (malformed, "line 2"),
        (tmp_path / "missing.env", "could not read file"),
    ]:
        result = _run_cli("run", "--env-file", str(path), "--", PY, "-c", "print(1)")
        assert result.returncode == 2
        assert "--env-file" in result.stderr
        assert expected in result.stderr
        assert "Traceback (most recent call last)" not in result.stderr


def test_cwd_flag_changes_the_child_working_directory(tmp_path: pathlib.Path) -> None:
    result = _run_cli(
        "run",
        "--cwd",
        str(tmp_path),
        "--",
        PY,
        "-c",
        "import os; print(os.getcwd())",
    )
    assert result.returncode == 0
    assert os.path.realpath(result.stdout.strip()) == os.path.realpath(str(tmp_path))
    assert "Traceback (most recent call last)" not in result.stderr


# --- --create-no-window ----------------------------------------------------


def _run_with_command_spy(*run_args: str) -> subprocess.CompletedProcess[str]:
    """Run `main(["run", *run_args, "--", "irrelevant"])` in-process with
    `processkit._cli.run.Command` monkeypatched to a spy that records whether
    `create_no_window()` was called on the built command, then prints that
    flag before exiting with the real `main()` return code — the same
    fake-`ProcessGroup` technique
    `test_fallback_process_group_failure_is_reported_not_raised` already uses
    for `run`, extended with a `Command` spy since the built command itself
    (not just `ProcessGroup`) is what `--create-no-window` touches."""
    script = (
        "import sys\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.run as run_mod\n"
        "class _SpyCommand:\n"
        "    create_no_window_called = False\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def inherit_stdin(self): return self\n"
        "    def stdout(self, *a): return self\n"
        "    def stderr(self, *a): return self\n"
        "    def create_no_window(self):\n"
        "        _SpyCommand.create_no_window_called = True\n"
        "        return self\n"
        "class _FakeOutcome:\n"
        "    code = 0\n"
        "    signal = None\n"
        "    timed_out = False\n"
        "class _FakeProc:\n"
        "    def outcome(self): return _FakeOutcome()\n"
        "class _FakeGroup:\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *a): return False\n"
        "    def start(self, command): return _FakeProc()\n"
        "run_mod.Command = _SpyCommand\n"
        "run_mod.ProcessGroup = _FakeGroup\n"
        f"code = cli.main(['run', {', '.join(repr(a) for a in run_args)}"
        f"{', ' if run_args else ''}'--', 'irrelevant'])\n"
        "print(_SpyCommand.create_no_window_called)\n"
        "sys.exit(code)\n"
    )
    return subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )


def test_create_no_window_flag_applies_create_no_window() -> None:
    result = _run_with_command_spy("--create-no-window")
    assert result.returncode == 0
    assert result.stdout.strip() == "True"
    assert "Traceback (most recent call last)" not in result.stderr


def test_without_create_no_window_flag_create_no_window_is_not_called() -> None:
    result = _run_with_command_spy()
    assert result.returncode == 0
    assert result.stdout.strip() == "False"
    assert "Traceback (most recent call last)" not in result.stderr


def test_run_redirects_stdout_and_stderr_directly_to_files(tmp_path: pathlib.Path) -> None:
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    result = _run_cli(
        "run",
        "--stdout-file",
        str(stdout_path),
        "--stderr-file",
        str(stderr_path),
        "--",
        PY,
        "-c",
        "import sys; print('out'); print('err', file=sys.stderr)",
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert stdout_path.read_text(encoding="utf-8").strip() == "out"
    assert stderr_path.read_text(encoding="utf-8").strip() == "err"


def test_run_output_limit_fails_loud_without_emitting_over_limit_output() -> None:
    result = _run_cli("run", "--output-limit", "16", "--", PY, "-c", "print('x' * 100)")
    assert result.returncode == 125
    assert result.stdout == ""
    assert "output exceeded its capture ceiling" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_run_rejects_output_limit_with_direct_stdout_redirect(tmp_path: pathlib.Path) -> None:
    result = _run_cli(
        "run",
        "--output-limit",
        "16",
        "--stdout-file",
        str(tmp_path / "out.log"),
        "--",
        PY,
    )
    assert result.returncode == 2
    assert "--output-limit cannot be combined with --stdout-file" in result.stderr


def test_run_rejects_idle_timeout_with_direct_stdout_redirect(tmp_path: pathlib.Path) -> None:
    result = _run_cli(
        "run",
        "--idle-timeout",
        "1",
        "--stdout-file",
        str(tmp_path / "out.log"),
        "--",
        PY,
    )
    assert result.returncode == 2
    assert "--idle-timeout cannot be combined with --stdout-file" in result.stderr


def test_run_passes_priority_and_parent_death_flags_to_command() -> None:
    script = (
        "import json, sys\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.run as run_mod\n"
        "class _SpyCommand:\n"
        "    calls = []\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def inherit_stdin(self): return self\n"
        "    def stdout(self, *a): return self\n"
        "    def stderr(self, *a): return self\n"
        "    def kill_on_parent_death(self): self.calls.append(['parent']); return self\n"
        "    def priority(self, value): self.calls.append(['priority', value]); return self\n"
        "    def io_priority(self, value, *, level=None): "
        "self.calls.append(['io', value, level]); return self\n"
        "class _Outcome:\n"
        "    code = 0\n"
        "    signal = None\n"
        "    timed_out = False\n"
        "class _Proc:\n"
        "    def outcome(self): return _Outcome()\n"
        "class _Group:\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *a): return False\n"
        "    def start(self, command): return _Proc()\n"
        "run_mod.Command = _SpyCommand\n"
        "run_mod.ProcessGroup = _Group\n"
        "code = cli.main(['run', '--kill-on-parent-death', '--priority', 'high', "
        "'--io-priority', 'best_effort:3', '--', 'irrelevant'])\n"
        "print(json.dumps(_SpyCommand.calls))\n"
        "sys.exit(code)\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == [["parent"], ["priority", "high"], ["io", "best_effort", 3]]


def test_run_rejects_malformed_io_priority() -> None:
    result = _run_cli("run", "--io-priority", "best_effort", "--", PY)
    assert result.returncode == 2
    assert "best_effort:LEVEL" in result.stderr


def test_run_pty_gives_child_a_terminal_and_merges_stderr_into_stdout() -> None:
    code = (
        "import os, sys; "
        "print(f'tty={os.isatty(1)}', flush=True); "
        "print('from-stderr', file=sys.stderr, flush=True)"
    )
    result = _run_cli("run", "--pty", "--", PY, "-c", code)
    assert result.returncode == 0
    assert "tty=True" in result.stdout
    assert "from-stderr" in result.stdout
    assert result.stderr == ""


def test_run_pty_applies_initial_terminal_size() -> None:
    result = _run_cli(
        "run",
        "--pty",
        "--pty-cols",
        "91",
        "--pty-rows",
        "37",
        "--",
        PY,
        "-c",
        "import os; size = os.get_terminal_size(1); print(size.columns, size.lines)",
    )
    assert result.returncode == 0
    # ConPTY may wrap the payload in terminal-control sequences; the reported
    # geometry itself must still be present in the merged terminal stream.
    assert "91 37" in result.stdout


def test_run_pty_rejects_incomplete_size_and_conflicting_sinks(tmp_path: pathlib.Path) -> None:
    cases = [
        (["--pty-cols", "80"], "requires --pty"),
        (["--pty", "--pty-cols", "80"], "must be provided together"),
        (["--pty", "--profile"], "cannot be combined with --profile"),
        (
            ["--pty", "--stderr-file", str(tmp_path / "stderr.log")],
            "cannot be combined with --stdout-file/--stderr-file",
        ),
    ]
    for flags, message in cases:
        result = _run_cli("run", *flags, "--", PY)
        assert result.returncode == 2
        assert message in result.stderr
        assert "Traceback (most recent call last)" not in result.stderr


# --- --profile ------------------------------------------------------------

_PROFILE_JSON_KEYS = {
    "duration_seconds",
    "cpu_time_seconds",
    "peak_memory_bytes",
    "avg_cpu_cores",
    "samples",
    "code",
    "signal",
    "timed_out",
}


def test_without_profile_flag_behavior_is_unchanged() -> None:
    # Regression guard: the flag is purely additive — omitting it must leave
    # stdout/stderr and the exit code exactly as before this feature existed.
    result = _run_cli("run", "--", PY, "-c", "print('plain')")
    assert result.returncode == 0
    assert result.stdout.strip() == "plain"
    assert result.stderr == ""


def test_profile_flag_emits_json_profile_to_stderr() -> None:
    result = _run_cli("run", "--profile", "--", PY, "-c", "print('child output')")
    assert result.returncode == 0
    assert result.stdout.strip() == "child output"
    assert "Traceback (most recent call last)" not in result.stderr
    profile = json.loads(result.stderr.strip())
    assert set(profile) == _PROFILE_JSON_KEYS
    assert profile["code"] == 0
    assert profile["signal"] is None
    assert profile["timed_out"] is False
    assert profile["duration_seconds"] >= 0.0
    assert profile["samples"] >= 1
    assert profile["cpu_time_seconds"] is None or profile["cpu_time_seconds"] >= 0.0
    assert profile["peak_memory_bytes"] is None or profile["peak_memory_bytes"] >= 0
    assert profile["avg_cpu_cores"] is None or profile["avg_cpu_cores"] >= 0.0


def test_profile_flag_writes_json_profile_to_a_file(tmp_path: pathlib.Path) -> None:
    profile_path = tmp_path / "profile.json"
    result = _run_cli(
        "run", "--profile", str(profile_path), "--", PY, "-c", "print('hi from child')"
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "hi from child"
    # Written to the file, not to stderr -- the two destinations are mutually
    # exclusive.
    assert result.stderr == ""
    assert "Traceback (most recent call last)" not in result.stderr
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert set(profile) == _PROFILE_JSON_KEYS
    assert profile["code"] == 0
    assert profile["timed_out"] is False


def test_profile_output_is_never_interleaved_with_child_stdio() -> None:
    # The profile is only ever emitted after proc.profile(...) returns, which
    # blocks until the child has fully exited (the same as outcome()) -- so
    # its one JSON line must trail the child's own stderr output, never split
    # across/inside it.
    result = _run_cli(
        "run",
        "--profile",
        "--",
        PY,
        "-c",
        "import sys; print('child-stdout'); print('child-stderr', file=sys.stderr)",
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "child-stdout"
    stderr_lines = result.stderr.strip().splitlines()
    assert stderr_lines[0] == "child-stderr"
    assert len(stderr_lines) == 2
    profile = json.loads(stderr_lines[-1])
    assert profile["code"] == 0


def test_profile_flag_reports_a_nonzero_child_exit_code() -> None:
    result = _run_cli("run", "--profile", "--", PY, "-c", "import sys; sys.exit(7)")
    assert result.returncode == 7
    profile = json.loads(result.stderr.strip())
    assert profile["code"] == 7
    assert profile["signal"] is None
    assert profile["timed_out"] is False


def test_profile_flag_degrades_to_null_fields_when_unavailable() -> None:
    # Simulates the without-Job-Object/cgroup-v2 case: `RunningProcess.profile()`
    # itself already reports the unavailable fields as `None` rather than
    # failing -- this must survive straight through to JSON `null`, not a
    # traceback or a dropped key.
    script = (
        "import sys\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.run as run_mod\n"
        "class _FakeOutcome:\n"
        "    code = 0\n"
        "    signal = None\n"
        "    timed_out = False\n"
        "class _FakeProfile:\n"
        "    duration_seconds = 0.01\n"
        "    cpu_time_seconds = None\n"
        "    peak_memory_bytes = None\n"
        "    avg_cpu_cores = None\n"
        "    samples = 0\n"
        "    code = 0\n"
        "    signal = None\n"
        "    timed_out = False\n"
        "    outcome = _FakeOutcome()\n"
        "class _FakeProc:\n"
        "    def profile(self, every_seconds):\n"
        "        return _FakeProfile()\n"
        "class _FakeGroup:\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *a): return False\n"
        "    def start(self, command): return _FakeProc()\n"
        "run_mod.ProcessGroup = _FakeGroup\n"
        "sys.exit(cli.main(['run', '--profile', '--', 'irrelevant']))\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0
    assert "Traceback (most recent call last)" not in result.stderr
    profile = json.loads(result.stderr.strip())
    assert set(profile) == _PROFILE_JSON_KEYS
    assert profile["cpu_time_seconds"] is None
    assert profile["peak_memory_bytes"] is None
    assert profile["avg_cpu_cores"] is None
    assert profile["samples"] == 0
    assert profile["duration_seconds"] == 0.01


# --- doctor -------------------------------------------------------------


_DOCTOR_JSON_KEYS = {
    "mechanism",
    "verdict",
    "exit_code",
    "resource_limits",
    "caveat",
}
_DOCTOR_RESOURCE_LIMIT_KEYS = {"max_memory", "max_processes", "cpu_quota"}


def test_doctor_help_does_not_raise() -> None:
    result = _run_cli("doctor", "--help")
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
    assert "Traceback (most recent call last)" not in result.stderr


def test_doctor_rejects_a_trailing_command() -> None:
    # "doctor" is read-only and diagnostic-only — it never takes a "--
    # PROGRAM ..." tail the way "run" does.
    result = _run_cli("doctor", "--", PY, "-c", "print(1)")
    assert result.returncode == 2
    assert "does not take a trailing command" in result.stderr
    assert "usage: python -m processkit doctor" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_doctor_prints_a_report_and_exits_with_one_of_the_documented_codes() -> None:
    # A real, unmocked run: the actual verdict depends on what this CI
    # runner's kernel grants (see the deterministic mapping tests below for
    # the runner-independent exit-code contract itself), but the shape of the
    # report and the exit-code range are not environment-dependent. `2` is
    # deliberately excluded: it is argparse's usage-error code, never a
    # `doctor` diagnostic verdict (see the exit-code-namespace tests below).
    result = _run_cli("doctor")
    assert result.returncode in (0, 1, 3, 4)
    assert "containment mechanism" in result.stdout
    assert "verdict:" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def _run_doctor_with_mocked_process_group(
    mock_class_body: str, *doctor_args: str
) -> subprocess.CompletedProcess[str]:
    """Run ``main(["doctor", *doctor_args])`` with its ``ProcessGroup`` patched.

    ``mock_class_body`` is a verbatim ``class _MockGroup: ...`` definition —
    the same technique
    `test_fallback_process_group_failure_is_reported_not_raised` already uses
    for `run`, needed here because the live probe's outcome depends on
    whatever container primitives (or lack thereof) this CI runner's kernel
    actually grants."""
    script = (
        "import sys\n"
        "import processkit\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.doctor as doctor_mod\n"
        f"{mock_class_body}\n"
        "doctor_mod.ProcessGroup = _MockGroup\n"
        f"sys.exit(cli.main({['doctor', *doctor_args]!r}))\n"
    )
    return subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )


def test_doctor_json_has_a_stable_schema_and_replaces_the_text_report() -> None:
    mock_group = (
        "class _MockGroup:\n"
        "    def __init__(self, *, max_memory=None, max_processes=None,\n"
        "                 cpu_quota=None, **kwargs):\n"
        "        self.mechanism = 'cgroup_v2'\n"
    )
    result = _run_doctor_with_mocked_process_group(mock_group, "--json")

    assert result.returncode == 0
    assert "Traceback (most recent call last)" not in result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == _DOCTOR_JSON_KEYS
    assert isinstance(payload["mechanism"], str)
    assert payload["mechanism"] == "cgroup_v2"
    assert isinstance(payload["verdict"], str)
    assert payload["verdict"] == "OK"
    assert isinstance(payload["exit_code"], int)
    assert payload["exit_code"] == 0
    assert isinstance(payload["caveat"], str)
    assert "Windows Job Object" in payload["caveat"]
    resource_limits = payload["resource_limits"]
    assert isinstance(resource_limits, dict)
    assert set(resource_limits) == _DOCTOR_RESOURCE_LIMIT_KEYS
    assert all(isinstance(available, bool) for available in resource_limits.values())
    assert resource_limits == {
        "max_memory": True,
        "max_processes": True,
        "cpu_quota": True,
    }


def test_doctor_json_and_text_modes_have_identical_exit_codes() -> None:
    mock_group = (
        "class _MockGroup:\n"
        "    def __init__(self, *, max_memory=None, max_processes=None,\n"
        "                 cpu_quota=None, **kwargs):\n"
        "        if max_memory is not None:\n"
        "            raise processkit.ResourceLimit('cgroup-v2 root required')\n"
        "        self.mechanism = 'process_group'\n"
    )
    text_result = _run_doctor_with_mocked_process_group(mock_group)
    json_result = _run_doctor_with_mocked_process_group(mock_group, "--json")

    assert text_result.returncode == json_result.returncode == 1
    assert "verdict: DEGRADED" in text_result.stdout
    payload = json.loads(json_result.stdout)
    assert payload["verdict"] == "DEGRADED"
    assert payload["exit_code"] == text_result.returncode
    assert payload["resource_limits"] == {
        "max_memory": False,
        "max_processes": True,
        "cpu_quota": True,
    }


def test_doctor_json_reports_operational_probe_failures() -> None:
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *, max_memory=None, max_processes=None,\n"
        "                 cpu_quota=None, **kwargs):\n"
        "        if max_processes is not None:\n"
        "            raise OSError('cannot read pids.max')\n"
        "        self.mechanism = 'cgroup_v2'\n",
        "--json",
    )

    assert result.returncode == 4
    payload = json.loads(result.stdout)
    assert set(payload) == _DOCTOR_JSON_KEYS | {"error_probe_failures"}
    assert payload["verdict"] == "ERROR"
    assert payload["resource_limits"] == {
        "max_memory": True,
        "max_processes": False,
        "cpu_quota": True,
    }
    assert payload["error_probe_failures"] == ["--max-processes (cannot read pids.max)"]


def test_doctor_json_exits_three_when_containment_itself_is_unavailable() -> None:
    mock_group = (
        "class _MockGroup:\n"
        "    def __init__(self, *a, **k):\n"
        "        raise processkit.Unsupported('containment is unavailable')\n"
    )
    text_result = _run_doctor_with_mocked_process_group(mock_group)
    result = _run_doctor_with_mocked_process_group(mock_group, "--json")

    assert text_result.returncode == result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "UNAVAILABLE"
    assert payload["mechanism"] == "unavailable"
    assert payload["exit_code"] == 3
    assert payload["resource_limits"] == {
        "max_memory": False,
        "max_processes": False,
        "cpu_quota": False,
    }
    assert "error_probe_failures" not in payload


def test_doctor_json_exits_four_when_mechanism_probe_hits_an_operational_error() -> None:
    mock_group = (
        "class _MockGroup:\n"
        "    def __init__(self, *a, **k):\n"
        "        raise PermissionError('cannot read /sys/fs/cgroup')\n"
    )
    text_result = _run_doctor_with_mocked_process_group(mock_group)
    result = _run_doctor_with_mocked_process_group(mock_group, "--json")

    assert text_result.returncode == result.returncode == 4
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "ERROR"
    assert payload["mechanism"] == "unknown"
    assert payload["exit_code"] == 4
    assert payload["resource_limits"] == {
        "max_memory": False,
        "max_processes": False,
        "cpu_quota": False,
    }
    assert payload["error_probe_failures"] == ["containment mechanism (cannot read /sys/fs/cgroup)"]


def test_doctor_exits_zero_when_resource_limits_are_available() -> None:
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *, max_memory=None, max_processes=None,\n"
        "                 cpu_quota=None, **kwargs):\n"
        "        self.mechanism = 'cgroup_v2'\n"
    )
    assert result.returncode == 0
    assert "cgroup_v2" in result.stdout
    assert "resource limits        : available" in result.stdout
    assert "verdict: OK" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_doctor_exits_one_when_containment_available_but_max_memory_unavailable() -> None:
    # R-1 regression guard: only --max-memory is rejected here (--max-processes
    # and --cpu-quota still construct fine), and the verdict must still be
    # DEGRADED, reporting specifically which limit is unavailable.
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *, max_memory=None, max_processes=None,\n"
        "                 cpu_quota=None, **kwargs):\n"
        "        if max_memory is not None:\n"
        "            raise processkit.ResourceLimit('cgroup-v2 root required')\n"
        "        self.mechanism = 'process_group'\n"
    )
    assert result.returncode == 1
    assert "process_group" in result.stdout
    assert "resource limits        : unavailable --max-memory" in result.stdout
    assert "verdict: DEGRADED" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_doctor_exits_one_when_only_max_processes_unavailable() -> None:
    # R-1 regression guard: --max-memory and --cpu-quota both construct fine;
    # only the --max-processes (pids.max) controller is rejected. This must
    # still surface as DEGRADED, not OK — the earlier implementation only
    # ever probed --max-memory and would have missed this.
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *, max_memory=None, max_processes=None,\n"
        "                 cpu_quota=None, **kwargs):\n"
        "        if max_processes is not None:\n"
        "            raise processkit.ResourceLimit('pids controller not delegated')\n"
        "        self.mechanism = 'cgroup_v2'\n"
    )
    assert result.returncode == 1
    assert "resource limits        : unavailable --max-processes" in result.stdout
    assert "verdict: DEGRADED" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_doctor_exits_one_when_only_cpu_quota_unavailable() -> None:
    # R-1 regression guard: same as above, for the --cpu-quota (cpu.max)
    # controller specifically.
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *, max_memory=None, max_processes=None,\n"
        "                 cpu_quota=None, **kwargs):\n"
        "        if cpu_quota is not None:\n"
        "            raise processkit.Unsupported('cpu controller not delegated')\n"
        "        self.mechanism = 'cgroup_v2'\n"
    )
    assert result.returncode == 1
    assert "resource limits        : unavailable --cpu-quota" in result.stdout
    assert "verdict: DEGRADED" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_doctor_reports_all_unavailable_limits_together() -> None:
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *, max_memory=None, max_processes=None,\n"
        "                 cpu_quota=None, **kwargs):\n"
        "        if max_processes is not None or cpu_quota is not None:\n"
        "            raise processkit.ResourceLimit('controller not delegated')\n"
        "        self.mechanism = 'cgroup_v2'\n"
    )
    assert result.returncode == 1
    limits_line = next(
        line
        for line in result.stdout.splitlines()
        if "resource limits" in line and "unavailable" in line
    )
    assert "--max-processes" in limits_line
    assert "--cpu-quota" in limits_line
    assert "--max-memory" not in limits_line
    assert "verdict: DEGRADED" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_doctor_exits_three_when_containment_itself_is_unavailable() -> None:
    # Exit 3, not 2 (R-2 regression guard): 2 is reserved for argparse usage
    # errors (see test_doctor_rejects_a_trailing_command below) and must
    # never double as a diagnostic verdict.
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *a, **k):\n"
        "        raise processkit.Unsupported('containment is unavailable')\n"
    )
    assert result.returncode == 3
    assert "containment mechanism : unavailable" in result.stdout
    assert "verdict: UNAVAILABLE" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_doctor_exits_four_when_mechanism_probe_hits_an_operational_error() -> None:
    # R-3 regression guard: an OSError/PermissionError (e.g. failing to read
    # cgroup state) is not a definitive "unavailable" answer and must not be
    # misreported as one — nor allowed to escape as a raw traceback.
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *a, **k):\n"
        "        raise PermissionError('cannot read /sys/fs/cgroup')\n"
    )
    assert result.returncode == 4
    assert "containment mechanism : error probing" in result.stdout
    assert "verdict: ERROR" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_doctor_exits_four_when_a_limit_probe_hits_an_operational_error() -> None:
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *, max_memory=None, max_processes=None,\n"
        "                 cpu_quota=None, **kwargs):\n"
        "        if max_processes is not None:\n"
        "            raise OSError('cannot read pids.max')\n"
        "        self.mechanism = 'cgroup_v2'\n"
    )
    assert result.returncode == 4
    assert "resource limits        : error probing --max-processes" in result.stdout
    assert "verdict: ERROR" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


# --- supervise ----------------------------------------------------------


def test_supervise_help_does_not_raise() -> None:
    result = _run_cli("supervise", "--help")
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
    assert "--restart" in result.stdout
    assert "--timeout" in result.stdout
    assert "--max-memory" in result.stdout
    assert "--max-processes" in result.stdout
    assert "--cpu-quota" in result.stdout
    assert "--create-no-window" in result.stdout
    assert "--health-port" in result.stdout
    assert "--health-http" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_parses_flags() -> None:
    result = _run_cli(
        "supervise",
        "--restart",
        "never",
        "--max-restarts",
        "2",
        "--backoff-initial",
        "0.01",
        "--backoff-factor",
        "1",
        "--max-backoff",
        "1",
        "--no-jitter",
        "--",
        PY,
        "-c",
        "pass",
    )
    assert result.returncode == 0
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_timeout_is_per_incarnation_and_uses_timeout_exit_code() -> None:
    result = _run_cli(
        "supervise",
        "--restart",
        "never",
        "--timeout",
        "0.2",
        "--",
        PY,
        "-c",
        "import time; time.sleep(30)",
    )
    assert result.returncode == 124
    assert "timed out after 0.2s" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_passes_containment_flags_to_command_and_supervisor() -> None:
    script = (
        "import json, sys\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.supervise as mod\n"
        "class _Command:\n"
        "    calls = []\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def inherit_stdin(self): return self\n"
        "    def stdout_tee(self, *a): return self\n"
        "    def stderr_tee(self, *a): return self\n"
        "    def timeout(self, value): self.calls.append(['timeout', value]); return self\n"
        "    def create_no_window(self): self.calls.append(['no-window']); return self\n"
        "class _Result:\n"
        "    code = 0\n"
        "    signal = None\n"
        "    timed_out = False\n"
        "class _Outcome:\n"
        "    stopped = 'policy_satisfied'\n"
        "    final_result = _Result()\n"
        "class _Supervisor:\n"
        "    kwargs = {}\n"
        "    def __init__(self, command, **kwargs): _Supervisor.kwargs = kwargs\n"
        "    def run(self): return _Outcome()\n"
        "mod.Command = _Command\n"
        "mod.Supervisor = _Supervisor\n"
        "code = cli.main(['supervise', '--timeout', '2', '--max-memory', '1000', "
        "'--max-processes', '3', '--cpu-quota', '0.5', '--create-no-window', "
        "'--', 'irrelevant'])\n"
        "print(json.dumps({'calls': _Command.calls, 'kwargs': _Supervisor.kwargs}))\n"
        "sys.exit(code)\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["calls"] == [["timeout", 2.0], ["no-window"]]
    assert payload["kwargs"] == {"max_memory": 1000, "max_processes": 3, "cpu_quota": 0.5}


def test_supervise_omits_tees_when_standard_streams_are_unavailable() -> None:
    script = (
        "import json, sys\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.supervise as mod\n"
        "class _Command:\n"
        "    calls = []\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def inherit_stdin(self): self.calls.append('stdin'); return self\n"
        "    def stdout_tee(self, *a): raise AssertionError('stdout tee called')\n"
        "    def stderr_tee(self, *a): raise AssertionError('stderr tee called')\n"
        "class _Result:\n"
        "    code = 0\n"
        "    signal = None\n"
        "    timed_out = False\n"
        "class _Outcome:\n"
        "    stopped = 'policy_satisfied'\n"
        "    final_result = _Result()\n"
        "class _Supervisor:\n"
        "    def __init__(self, command, **kwargs): pass\n"
        "    def run(self): return _Outcome()\n"
        "mod.Command = _Command\n"
        "mod.Supervisor = _Supervisor\n"
        "stdout, stderr = sys.stdout, sys.stderr\n"
        "sys.stdout = sys.stderr = None\n"
        "try:\n"
        "    code = cli.main(['supervise', '--', 'irrelevant'])\n"
        "finally:\n"
        "    sys.stdout, sys.stderr = stdout, stderr\n"
        "print(json.dumps({'code': code, 'calls': _Command.calls}))\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"code": 0, "calls": ["stdin"]}


def test_supervise_health_port_builds_a_working_probe() -> None:
    script = (
        "import json, sys\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.supervise as mod\n"
        "class _Connection:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *a): return False\n"
        "seen = []\n"
        "def connect(address, timeout):\n"
        "    seen.append([list(address), timeout])\n"
        "    return _Connection()\n"
        "mod.socket.create_connection = connect\n"
        "class _Command:\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def inherit_stdin(self): return self\n"
        "    def stdout_tee(self, *a): return self\n"
        "    def stderr_tee(self, *a): return self\n"
        "class _Result:\n"
        "    code = 0\n"
        "    signal = None\n"
        "    timed_out = False\n"
        "class _Outcome:\n"
        "    stopped = 'policy_satisfied'\n"
        "    final_result = _Result()\n"
        "class _Supervisor:\n"
        "    details = {}\n"
        "    def __init__(self, command, **kwargs):\n"
        "        _Supervisor.details = {'healthy': kwargs['health_check'](), "
        "'interval': kwargs['health_check_interval']}\n"
        "    def run(self): return _Outcome()\n"
        "mod.Command = _Command\n"
        "mod.Supervisor = _Supervisor\n"
        "code = cli.main(['supervise', '--health-port', '[::1]:8080', "
        "'--health-interval', '2', '--health-timeout', '0.25', '--', 'irrelevant'])\n"
        "print(json.dumps({'details': _Supervisor.details, 'seen': seen}))\n"
        "sys.exit(code)\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "details": {"healthy": True, "interval": 2.0},
        "seen": [[["::1", 8080], 0.25]],
    }


def test_supervise_health_http_accepts_only_a_2xx_response() -> None:
    script = (
        "import json, sys\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.supervise as mod\n"
        "class _Response:\n"
        "    status = 204\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *a): return False\n"
        "seen = []\n"
        "def open_url(url, timeout): seen.append([url, timeout]); return _Response()\n"
        "mod.urllib.request.urlopen = open_url\n"
        "class _Command:\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def inherit_stdin(self): return self\n"
        "    def stdout_tee(self, *a): return self\n"
        "    def stderr_tee(self, *a): return self\n"
        "class _Result:\n"
        "    code = 0\n"
        "    signal = None\n"
        "    timed_out = False\n"
        "class _Outcome:\n"
        "    stopped = 'policy_satisfied'\n"
        "    final_result = _Result()\n"
        "class _Supervisor:\n"
        "    healthy = False\n"
        "    def __init__(self, command, **kwargs): "
        "_Supervisor.healthy = kwargs['health_check']()\n"
        "    def run(self): return _Outcome()\n"
        "mod.Command = _Command\n"
        "mod.Supervisor = _Supervisor\n"
        "code = cli.main(['supervise', '--health-http', 'http://localhost/healthz', "
        "'--health-timeout', '0.4', '--', 'irrelevant'])\n"
        "print(json.dumps({'healthy': _Supervisor.healthy, 'seen': seen}))\n"
        "sys.exit(code)\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "healthy": True,
        "seen": [["http://localhost/healthz", 0.4]],
    }


def test_supervise_resource_limit_retries_contained_but_uncapped() -> None:
    script = (
        "import json, sys\n"
        "import processkit\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.supervise as mod\n"
        "class _Command:\n"
        "    def __init__(self, *a, **k): pass\n"
        "    def inherit_stdin(self): return self\n"
        "    def stdout_tee(self, *a): return self\n"
        "    def stderr_tee(self, *a): return self\n"
        "class _Result:\n"
        "    code = 0\n"
        "    signal = None\n"
        "    timed_out = False\n"
        "class _Outcome:\n"
        "    stopped = 'policy_satisfied'\n"
        "    final_result = _Result()\n"
        "class _Supervisor:\n"
        "    calls = []\n"
        "    def __init__(self, command, **kwargs): self.kwargs = kwargs\n"
        "    def run(self):\n"
        "        self.calls.append(self.kwargs)\n"
        "        if 'max_memory' in self.kwargs:\n"
        "            raise processkit.ResourceLimit('controller unavailable')\n"
        "        return _Outcome()\n"
        "mod.Command = _Command\n"
        "mod.Supervisor = _Supervisor\n"
        "code = cli.main(['supervise', '--max-memory', '1000', '--', 'irrelevant'])\n"
        "print(json.dumps(_Supervisor.calls))\n"
        "sys.exit(code)\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == [{"max_memory": 1000}, {}]
    assert "supervising contained, but uncapped" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_health_options_require_exactly_one_valid_probe() -> None:
    cases = [
        (["--health-interval", "1"], "requires a health probe"),
        (["--health-port", "localhost"], "must be HOST:PORT"),
        (["--health-http", "file:///tmp/healthy"], "absolute http:// or https:// URL"),
        (["--health-http", "http://localhost:bad/"], "valid absolute HTTP(S) URL"),
        (
            ["--health-port", "localhost:80", "--health-http", "http://localhost/"],
            "not allowed with argument",
        ),
    ]
    for flags, message in cases:
        result = _run_cli("supervise", *flags, "--", PY)
        assert result.returncode == 2
        assert message in result.stderr
        assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_unhealthy_process_is_force_stopped() -> None:
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        port = unavailable.getsockname()[1]
        result = _run_cli(
            "supervise",
            "--restart",
            "never",
            "--health-port",
            f"127.0.0.1:{port}",
            "--health-interval",
            "0.05",
            "--health-timeout",
            "0.05",
            "--",
            PY,
            "-c",
            "import time; time.sleep(30)",
        )
    assert result.returncode in {120, 128 + getattr(signal, "SIGKILL", 9)}
    assert "health check" in result.stderr or "killed by signal" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_parses_env_and_cwd_flags(tmp_path: pathlib.Path) -> None:
    result = _run_cli(
        "supervise",
        "--restart",
        "never",
        "--env",
        "PK_SUPERVISE_ENV=applied",
        "--cwd",
        str(tmp_path),
        "--",
        PY,
        "-c",
        "import os; print(os.environ['PK_SUPERVISE_ENV']); print(os.getcwd())",
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "applied"
    assert os.path.realpath(lines[1]) == os.path.realpath(str(tmp_path))
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_missing_command_after_supervise_is_a_usage_error() -> None:
    result = _run_cli("supervise", "--restart", "always")
    assert result.returncode == 2
    assert "missing command" in result.stderr
    assert "usage: python -m processkit supervise" in result.stderr
    assert "--restart" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_idle_timeout_is_a_loud_usage_error_not_a_silent_noop() -> None:
    # `--idle-timeout` is accepted by the supervise parser (parity with `run`)
    # but cannot be enforced through Supervisor's one-shot verbs in processkit
    # 2.3.x, so using it is a usage error (exit 2) with a clear message pointing
    # at `run` — never a silently-ignored flag. Runs a program that WOULD exit 0
    # to prove the rejection happens before any supervision, not after.
    result = _run_cli(
        "supervise",
        "--restart",
        "never",
        "--idle-timeout",
        "1",
        "--",
        PY,
        "-c",
        "print('should never run')",
    )
    assert result.returncode == 2
    assert "--idle-timeout is not yet supported under supervise" in result.stderr
    assert "run --idle-timeout" in result.stderr
    assert "should never run" not in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_successful_run_exits_with_final_result_code() -> None:
    result = _run_cli("supervise", "--restart", "never", "--", PY, "-c", "import sys; sys.exit(7)")
    assert result.returncode == 7
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_exits_restarts_exhausted_code_on_max_restarts() -> None:
    result = _run_cli(
        "supervise",
        "--restart",
        "on_crash",
        "--max-restarts",
        "2",
        "--backoff-initial",
        "0.01",
        "--backoff-factor",
        "1",
        "--no-jitter",
        "--",
        PY,
        "-c",
        "import sys; sys.exit(1)",
    )
    assert result.returncode == 121
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_exits_sigint_on_keyboard_interrupt() -> None:
    script = (
        "import sys\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.supervise as supervise_mod\n"
        "class _InterruptingSupervisor:\n"
        "    def __init__(self, *args, **kwargs): pass\n"
        "    def run(self): raise KeyboardInterrupt\n"
        "supervise_mod.Supervisor = _InterruptingSupervisor\n"
        "sys.exit(cli.main(['supervise', '--', 'irrelevant']))\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 130
    assert "interrupted" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_exits_gave_up_code_when_outcome_reports_gave_up() -> None:
    # `give_up_when` is API-only (not exposed as a CLI flag), so drive the
    # "gave_up" branch directly with a fake `Supervisor`/outcome, the same
    # technique `test_supervise_exits_sigint_on_keyboard_interrupt` uses above.
    script = (
        "import sys\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.supervise as supervise_mod\n"
        "class _FinalResult:\n"
        "    code = 1\n"
        "    signal = None\n"
        "class _Outcome:\n"
        "    stopped = 'gave_up'\n"
        "    final_result = _FinalResult()\n"
        "class _GivingUpSupervisor:\n"
        "    def __init__(self, *args, **kwargs): pass\n"
        "    def run(self): return _Outcome()\n"
        "supervise_mod.Supervisor = _GivingUpSupervisor\n"
        "sys.exit(cli.main(['supervise', '--', 'irrelevant']))\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 122
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_exits_signal_code_when_final_result_was_killed_by_signal() -> None:
    # A signal-killed last incarnation under a satisfied policy has no `.code`
    # — must map to `128 + signal` (mirroring `run`'s own convention), not the
    # generic internal-error code.
    script = (
        "import sys\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.supervise as supervise_mod\n"
        "class _FinalResult:\n"
        "    code = None\n"
        "    signal = 15\n"
        "    timed_out = False\n"
        "class _Outcome:\n"
        "    stopped = 'policy_satisfied'\n"
        "    final_result = _FinalResult()\n"
        "class _SignalledSupervisor:\n"
        "    def __init__(self, *args, **kwargs): pass\n"
        "    def run(self): return _Outcome()\n"
        "supervise_mod.Supervisor = _SignalledSupervisor\n"
        "sys.exit(cli.main(['supervise', '--', 'irrelevant']))\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 128 + 15
    assert "killed by signal 15" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_exits_internal_error_on_missing_program() -> None:
    result = _run_cli("supervise", "--restart", "never", "--", NO_SUCH_PROGRAM)
    assert result.returncode == 120
    assert "could not supervise" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_internal_error_is_reported_not_raised() -> None:
    script = (
        "import sys\n"
        "import processkit\n"
        "import processkit._cli as cli\n"
        "import processkit._cli.supervise as supervise_mod\n"
        "class _UnsupportedSupervisor:\n"
        "    def __init__(self, *args, **kwargs):\n"
        "        raise processkit.Unsupported('containment is unavailable')\n"
        "supervise_mod.Supervisor = _UnsupportedSupervisor\n"
        "sys.exit(cli.main(['supervise', '--', 'irrelevant']))\n"
    )
    result = subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert result.returncode == 120
    assert len(result.stderr.strip().splitlines()) == 1
    assert "containment is unavailable" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_env_clear_and_inherit_env_work_like_run() -> None:
    parent_env = _parent_env_with(PK_SUPERVISE_KEEP="kept", PK_SUPERVISE_DROP="dropped")
    args = ["supervise", "--restart", "never", "--inherit-env", "PK_SUPERVISE_KEEP"]
    if sys.platform == "win32":
        args += ["--inherit-env", "SYSTEMROOT"]
    code = (
        "import os; print(os.environ.get('PK_SUPERVISE_KEEP', '-'), "
        "os.environ.get('PK_SUPERVISE_DROP', '-'))"
    )
    args += ["--", PY, "-c", code]
    result = _run_cli(*args, env=parent_env)
    assert result.returncode == 0
    assert result.stdout.strip() == "kept -"
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_env_file_uses_the_same_merge_rules(tmp_path: pathlib.Path) -> None:
    env_file = tmp_path / "supervise.env"
    env_file.write_text("PK_SUPERVISE_FILE=from-file\nPK_OVERRIDE=file\n", encoding="utf-8")
    code = "import os; print(os.environ['PK_SUPERVISE_FILE'], os.environ['PK_OVERRIDE'])"
    result = _run_cli(
        "supervise",
        "--restart",
        "never",
        "--env-file",
        str(env_file),
        "--env",
        "PK_OVERRIDE=flag",
        "--",
        PY,
        "-c",
        code,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "from-file flag"
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_cwd_flag_works(tmp_path: pathlib.Path) -> None:
    result = _run_cli(
        "supervise",
        "--restart",
        "never",
        "--cwd",
        str(tmp_path),
        "--",
        PY,
        "-c",
        "import os; print(os.getcwd())",
    )
    assert result.returncode == 0
    assert os.path.realpath(result.stdout.strip()) == os.path.realpath(str(tmp_path))
    assert "Traceback (most recent call last)" not in result.stderr


def test_supervise_successful_program_exits_zero_and_streams_stdout() -> None:
    result = _run_cli(
        "supervise", "--restart", "never", "--", PY, "-c", "print('hello from supervisor')"
    )
    assert result.returncode == 0
    assert "hello from supervisor" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr
