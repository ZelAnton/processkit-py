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


def _run_doctor_with_mocked_process_group(mock_class_body: str) -> subprocess.CompletedProcess[str]:
    """Run `main(["doctor"])` in-process with `processkit._cli.doctor.ProcessGroup`
    monkeypatched to `mock_class_body` (a `class _MockGroup: ...` definition,
    verbatim) — the same technique
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
        "sys.exit(cli.main(['doctor']))\n"
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
