"""Hardening: leak/stress, interpreter-exit teardown, and a perf sanity check.

These back the 1.0 no-orphan promise under repetition and process exit.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import time

from processkit import Command, ProcessGroup

from ._liveness import read_pid_when_ready, wait_dead
from ._programs import SPAWN_GRANDCHILD as _SPAWN_GRANDCHILD

PY = sys.executable


def test_many_groups_leave_no_orphans(tmp_path: pathlib.Path) -> None:
    # Create and tear down many trees in a row; every grandchild must be reaped.
    grandchildren: list[int] = []
    for i in range(15):
        pid_file = tmp_path / f"gc{i}.pid"
        with ProcessGroup() as group:
            group.start(Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]))
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
    # A loose sanity bound — catches catastrophic per-call overhead, not micro-perf.
    start = time.monotonic()
    for _ in range(10):
        assert Command(PY, ["-c", "pass"]).output().is_success
    assert time.monotonic() - start < 60.0
