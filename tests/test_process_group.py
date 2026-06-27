"""`ProcessGroup` context manager — the kill-on-drop tree guarantee.

The headline test spawns a child that itself spawns a *grandchild*, then proves
the grandchild is dead after the ``with`` block exits. This is the orphan-leak
exit criterion: containment reaches descendants, not just direct children.
"""

from __future__ import annotations

import gc
import pathlib
import sys

import pytest

from processkit import Command, ProcessError, ProcessGroup

from ._liveness import is_alive, read_pid_when_ready, wait_until
from ._programs import SPAWN_GRANDCHILD as _SPAWN_GRANDCHILD

PY = sys.executable


def test_group_reports_a_mechanism() -> None:
    with ProcessGroup() as group:
        assert group.mechanism in {"job_object", "cgroup_v2", "process_group"}


def test_group_teardown_kills_grandchild(tmp_path: pathlib.Path) -> None:
    pid_file = tmp_path / "grandchild.pid"

    with ProcessGroup() as group:
        group.start(Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]))
        grandchild_pid = read_pid_when_ready(pid_file, timeout=10.0)
        assert is_alive(grandchild_pid)

    # The `with` block has exited — the whole tree must be gone.
    assert wait_until(lambda: not is_alive(grandchild_pid), timeout=10.0), (
        f"grandchild {grandchild_pid} survived ProcessGroup teardown"
    )


def test_explicit_shutdown_is_idempotent() -> None:
    group = ProcessGroup()
    group.start(Command(PY, ["-c", "import time; time.sleep(30)"]))
    group.shutdown()
    group.shutdown()  # second call is a no-op, not an error


def test_use_after_close_raises() -> None:
    group = ProcessGroup()
    group.shutdown()
    with pytest.raises(ProcessError):
        group.start(Command(PY, ["-c", "pass"]))


def test_start_returns_handle_with_pid() -> None:
    with ProcessGroup() as group:
        running = group.start(Command(PY, ["-c", "import time; time.sleep(30)"]))
        assert running.pid is not None
        assert running.pid > 0


def test_teardown_runs_when_exception_escapes_block(tmp_path: pathlib.Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    grandchild_pid: int | None = None

    # try/except (not `pytest.raises`) so static analysis can see that the
    # post-block assertions are reachable after the exception is handled.
    try:
        with ProcessGroup() as group:
            group.start(Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]))
            grandchild_pid = read_pid_when_ready(pid_file, timeout=10.0)
            assert is_alive(grandchild_pid)
            raise KeyboardInterrupt  # the `__exit__` teardown must still fire
    except KeyboardInterrupt:
        # Expected — raised above to prove teardown fires when an exception
        # escapes the block.
        pass

    assert grandchild_pid is not None
    assert wait_until(lambda: not is_alive(grandchild_pid), timeout=10.0), (
        f"grandchild {grandchild_pid} survived teardown on KeyboardInterrupt"
    )


def test_teardown_on_garbage_collection(tmp_path: pathlib.Path) -> None:
    pid_file = tmp_path / "grandchild.pid"

    # No `with`: drop the only reference and force collection. The Rust `Drop`
    # of the dropped ProcessGroup must reap the tree.
    group = ProcessGroup()
    group.start(Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]))
    grandchild_pid = read_pid_when_ready(pid_file, timeout=10.0)
    assert is_alive(grandchild_pid)

    del group
    gc.collect()

    assert wait_until(lambda: not is_alive(grandchild_pid), timeout=10.0), (
        f"grandchild {grandchild_pid} survived garbage collection of the group"
    )
