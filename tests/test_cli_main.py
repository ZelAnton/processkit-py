"""`python -m processkit run -- ...` — the CLI wrapper (`src/processkit/__main__.py`).

Every test here spawns a **real** `sys.executable -m processkit ...` subprocess
rather than importing `processkit.__main__` and calling `main()` directly: the
whole point under test is argv parsing and process exit-code plumbing, neither
of which a direct import would actually exercise (an in-process call can't
observe `sys.exit()`/the real process exit code the way a subprocess round
trip does).
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

from .conftest import NO_SUCH_PROGRAM, PY

#: Generous but bounded — these are short-lived child interpreters; a hang
#: here means the CLI itself is stuck, which should fail loud, not time out
#: the whole test session.
_SUBPROCESS_TIMEOUT = 30


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PY, "-m", "processkit", *args],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
        env=env,
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
        "import processkit.__main__ as m\n"
        "class _AlwaysUnsupported:\n"
        "    def __init__(self, *a, **k):\n"
        "        raise processkit.Unsupported('containment is unavailable')\n"
        "m.ProcessGroup = _AlwaysUnsupported\n"
        "sys.exit(m.main(['run', '--max-memory', '1', '--', 'irrelevant']))\n"
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


# --- doctor -------------------------------------------------------------


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
    # report and the exit-code range are not environment-dependent.
    result = _run_cli("doctor")
    assert result.returncode in (0, 1, 2)
    assert "containment mechanism" in result.stdout
    assert "verdict:" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def _run_doctor_with_mocked_process_group(mock_class_body: str) -> subprocess.CompletedProcess[str]:
    """Run `main(["doctor"])` in-process with `processkit.__main__.ProcessGroup`
    monkeypatched to `mock_class_body` (a `class _MockGroup: ...` definition,
    verbatim) — the same technique
    `test_fallback_process_group_failure_is_reported_not_raised` already uses
    for `run`, needed here because the live probe's outcome depends on
    whatever container primitives (or lack thereof) this CI runner's kernel
    actually grants."""
    script = (
        "import sys\n"
        "import processkit\n"
        "import processkit.__main__ as m\n"
        f"{mock_class_body}\n"
        "m.ProcessGroup = _MockGroup\n"
        "sys.exit(m.main(['doctor']))\n"
    )
    return subprocess.run(
        [PY, "-c", script],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
        check=False,
    )


def test_doctor_exits_zero_when_resource_limits_are_available() -> None:
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *, max_memory=None, **kwargs):\n"
        "        self.mechanism = 'cgroup_v2'\n"
    )
    assert result.returncode == 0
    assert "cgroup_v2" in result.stdout
    assert "resource limits        : available" in result.stdout
    assert "verdict: OK" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_doctor_exits_one_when_containment_available_but_limits_are_not() -> None:
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *, max_memory=None, **kwargs):\n"
        "        if max_memory is not None:\n"
        "            raise processkit.ResourceLimit('cgroup-v2 root required')\n"
        "        self.mechanism = 'process_group'\n"
    )
    assert result.returncode == 1
    assert "process_group" in result.stdout
    assert "resource limits        : unavailable" in result.stdout
    assert "verdict: DEGRADED" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr


def test_doctor_exits_two_when_containment_itself_is_unavailable() -> None:
    result = _run_doctor_with_mocked_process_group(
        "class _MockGroup:\n"
        "    def __init__(self, *a, **k):\n"
        "        raise processkit.Unsupported('containment is unavailable')\n"
    )
    assert result.returncode == 2
    assert "containment mechanism : unavailable" in result.stdout
    assert "verdict: UNAVAILABLE" in result.stdout
    assert "Traceback (most recent call last)" not in result.stderr
