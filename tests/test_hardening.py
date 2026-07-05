"""Hardening: leak/stress, interpreter-exit teardown, and a perf sanity check.

These back the 1.0 no-orphan promise under repetition and process exit.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import time

from processkit import Command, ProcessGroup

from ._liveness import read_pid_when_ready, wait_dead
from .conftest import PY, spawn_grandchild_command


def _stress_scale() -> int:
    """Multiplier for stress-test intensity (iterations/spawns), read from
    `PROCESSKIT_STRESS_SCALE`.

    Defaults to 1, which reproduces exactly the fast, PR-gate-sized values
    already hardcoded below. The scheduled nightly/weekly workflow
    (`.github/workflows/nightly-stress.yml`) sets this higher to exercise many
    more iterations per run, to catch rare teardown races that a single small
    PR-gate run is unlikely to surface. An invalid/non-integer value falls
    back to 1 rather than failing the test.
    """
    try:
        scale = int(os.environ.get("PROCESSKIT_STRESS_SCALE", "1"))
    except ValueError:
        scale = 1
    return max(1, scale)


_SCALE = _stress_scale()


def test_many_groups_leave_no_orphans(tmp_path: pathlib.Path) -> None:
    # Create and tear down many trees in a row; every grandchild must be reaped.
    # 5 iterations by default (was 15): the same signal is proven well before
    # 15 — this is a repetition/leak check, not a load test, and the suite
    # pays this cost on every run. PROCESSKIT_STRESS_SCALE raises this back up
    # (and beyond) for the scheduled hardening run.
    grandchildren: list[int] = []
    for i in range(5 * _SCALE):
        pid_file = tmp_path / f"gc{i}.pid"
        with ProcessGroup() as group:
            group.start(spawn_grandchild_command(pid_file))
            grandchildren.append(read_pid_when_ready(pid_file, timeout=10.0))

    for pid in grandchildren:
        assert wait_dead(pid, timeout=10.0), f"grandchild {pid} survived its group's teardown"


def test_interpreter_exit_reaps_tree(tmp_path: pathlib.Path) -> None:
    # A subprocess creates a group, starts a child, and exits *normally* without
    # calling shutdown. The group's drop (at interpreter shutdown) — or, on
    # Windows, the Job Object closing — must reap the child.
    pid_file = tmp_path / "child.pid"
    program = (
        "import processkit, sys\n"
        "group = processkit.ProcessGroup()\n"
        "running = group.start(processkit.Command(sys.executable, "
        "['-c', 'import time; time.sleep(60)']))\n"
        "open(sys.argv[1], 'w').write(str(running.pid))\n"
        "# exit normally; no explicit shutdown\n"
    )
    subprocess.run([PY, "-c", program, str(pid_file)], timeout=30, check=True)
    child_pid = int(pid_file.read_text())
    assert wait_dead(child_pid, timeout=10.0), f"child {child_pid} survived the interpreter exiting"


def test_no_silly_per_call_overhead() -> None:
    # A loose sanity bound — catches catastrophic per-call overhead, not
    # micro-perf. 3 spawns by default (was 10) with a tighter bound: still
    # generous against real interpreter-startup cost, but no longer loose
    # enough to hide a real regression. The bound scales with the spawn count
    # (PROCESSKIT_STRESS_SCALE) so a scaled-up scheduled run stays a real
    # per-call-overhead check rather than a wall-clock race.
    start = time.monotonic()
    for _ in range(3 * _SCALE):
        assert Command(PY, ["-c", "pass"]).output().is_success
    assert time.monotonic() - start < 20.0 * _SCALE
