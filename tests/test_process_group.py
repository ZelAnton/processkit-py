"""`ProcessGroup` — the kill-on-drop tree guarantee plus the rest of the group
operation surface (resource limits, signals, suspend/resume/terminate, stats).

The headline test spawns a child that itself spawns a *grandchild*, then proves
the grandchild is dead after the ``with`` block exits. This is the orphan-leak
exit criterion: containment reaches descendants, not just direct children. The
later sections cover construction-time resource limits and the running-group
operations, skipping where the platform cannot enforce them.
"""

from __future__ import annotations

import contextlib
import gc
import pathlib
import sys

import pytest

from processkit import Command, ProcessError, ProcessGroup, ResourceLimit, Unsupported

from ._liveness import is_alive, read_pid_when_ready, wait_dead
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
    assert wait_dead(grandchild_pid, timeout=10.0), (
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
    assert wait_dead(grandchild_pid, timeout=10.0), (
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

    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived garbage collection of the group"
    )


def test_group_started_handle_works_as_context_manager() -> None:
    # A handle from group.start() is a shared-group handle: the context-manager
    # exit kills just that child, and the surrounding group stays usable.
    with ProcessGroup() as group:
        with group.start(Command(PY, ["-c", "import time; time.sleep(60)"])) as proc:
            child = proc.pid
            assert child is not None
        assert wait_dead(child, timeout=10.0), "group-started child survived its inner with-block"
        assert isinstance(group.members(), list)


# --- resource limits --------------------------------------------------------


def test_invalid_resource_limit_raises() -> None:
    with pytest.raises(ResourceLimit) as excinfo:
        ProcessGroup(max_processes=0)
    assert excinfo.value.message  # the structured field carries the reason
    with pytest.raises(ResourceLimit):
        ProcessGroup(max_memory=0)


def test_resource_limited_group_runs() -> None:
    # Limits are enforceable via the Windows Job Object or a Linux cgroup v2
    # *root*; under a container / systemd session / non-root cgroup the kernel's
    # "no internal processes" rule blocks them (raising ResourceLimit), and some
    # platforms don't support them at all (Unsupported). Skip where unenforceable.
    try:
        with ProcessGroup(max_processes=64, max_memory=512 * 1024 * 1024) as group:
            running = group.start(Command(PY, ["-c", "pass"]))
            assert running.pid is not None
    except (Unsupported, ResourceLimit):
        pytest.skip("resource limits not enforceable in this environment")


def test_group_shutdown_grace_kwarg_tears_down() -> None:
    # The teardown-policy ceilings (`shutdown_grace`, `escalate_to_kill`) are not
    # resource limits, so construction needs no Job Object / cgroup root. This is
    # the only call site that passes `shutdown_grace=` — it pins the renamed kwarg
    # against both the stub (mypy here) and the Rust binding (a name mismatch would
    # raise at construction).
    with ProcessGroup(shutdown_grace=0.5, escalate_to_kill=True) as group:
        running = group.start(Command(PY, ["-c", "import time; time.sleep(30)"]))
        pid = running.pid
        group.shutdown()  # signal -> wait shutdown_grace -> escalate to hard kill

    assert pid is not None
    assert wait_dead(pid, timeout=10.0), "shutdown_grace teardown did not reap the child"


# --- signals / suspend / resume / terminate / stats -------------------------


def test_group_suspend_resume_terminate() -> None:
    with ProcessGroup() as group:
        running = group.start(Command(PY, ["-c", "import time; time.sleep(30)"]))
        pid = running.pid
        try:
            group.suspend()
            group.resume()
        except Unsupported:
            pass
        group.kill_all()
        assert pid is not None
        assert wait_dead(pid, timeout=10.0), "kill_all did not reap the group member"


def test_group_signal() -> None:
    with ProcessGroup() as group:
        group.start(Command(PY, ["-c", "import time; time.sleep(30)"]))
        with contextlib.suppress(Unsupported):
            group.signal("term")


def test_group_signal_unknown_name_rejected() -> None:
    with ProcessGroup() as group, pytest.raises(ValueError):
        group.signal("not-a-signal")  # type: ignore[arg-type]  # invalid on purpose


def test_group_stats() -> None:
    with ProcessGroup() as group:
        group.start(Command(PY, ["-c", "import time; time.sleep(2)"]))
        try:
            stats = group.stats()
        except Unsupported:
            pytest.skip("stats unsupported on this platform")
        assert stats.active_process_count >= 1
        assert stats.peak_memory_bytes is None or stats.peak_memory_bytes >= 0
        assert stats.total_cpu_time_seconds is None or stats.total_cpu_time_seconds >= 0.0
