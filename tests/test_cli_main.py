"""`python -m processkit run -- ...` — the CLI wrapper (`src/processkit/__main__.py`).

Every test here spawns a **real** `sys.executable -m processkit ...` subprocess
rather than importing `processkit.__main__` and calling `main()` directly: the
whole point under test is argv parsing and process exit-code plumbing, neither
of which a direct import would actually exercise (an in-process call can't
observe `sys.exit()`/the real process exit code the way a subprocess round
trip does).
"""

from __future__ import annotations

import subprocess

from .conftest import NO_SUCH_PROGRAM, PY

#: Generous but bounded — these are short-lived child interpreters; a hang
#: here means the CLI itself is stuck, which should fail loud, not time out
#: the whole test session.
_SUBPROCESS_TIMEOUT = 30


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PY, "-m", "processkit", *args],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )


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
    assert "Traceback (most recent call last)" not in result.stderr


def test_successful_run_exits_zero_and_streams_stdout() -> None:
    result = _run_cli("run", "--", PY, "-c", "print('hello from child')")
    assert result.returncode == 0
    assert "hello from child" in result.stdout
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


def test_timeout_grace_without_timeout_is_a_usage_error() -> None:
    result = _run_cli("run", "--timeout-grace", "1", "--", PY, "-c", "print(1)")
    assert result.returncode == 2
    assert "--timeout-grace requires --timeout" in result.stderr
    assert "Traceback (most recent call last)" not in result.stderr


def test_missing_command_after_run_is_a_usage_error() -> None:
    result = _run_cli("run", "--timeout", "1")
    assert result.returncode == 2
    assert "missing command" in result.stderr


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
