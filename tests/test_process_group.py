"""`ProcessGroup` — the kill-on-drop tree guarantee plus the rest of the group
operation surface (resource limits, signals, suspend/resume/terminate, stats).

The headline test spawns a child that itself spawns a *grandchild*, then proves
the grandchild is dead after the ``with`` block exits. This is the orphan-leak
exit criterion: containment reaches descendants, not just direct children. The
later sections cover construction-time resource limits and the running-group
operations, skipping where the platform cannot enforce them.
"""

from __future__ import annotations

import gc
import os
import pathlib
import sys
import time

import pytest

from processkit import Command, ProcessError, ProcessGroup, ResourceLimit, Unsupported

from ._liveness import is_alive, read_pid_when_ready, wait_dead, wait_until
from .conftest import PY, spawn_grandchild_command


def test_group_reports_a_mechanism() -> None:
    with ProcessGroup() as group:
        assert group.mechanism in {"job_object", "cgroup_v2", "process_group"}


def test_group_teardown_kills_grandchild(pid_file: pathlib.Path) -> None:
    with ProcessGroup() as group:
        group.start(spawn_grandchild_command(pid_file))
        grandchild_pid = read_pid_when_ready(pid_file, timeout=10.0)
        assert is_alive(grandchild_pid)

    # The `with` block has exited — the whole tree must be gone.
    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived ProcessGroup teardown"
    )


def test_explicit_shutdown_is_idempotent(pid_file: pathlib.Path) -> None:
    group = ProcessGroup()
    group.start(spawn_grandchild_command(pid_file))
    grandchild_pid = read_pid_when_ready(pid_file, timeout=10.0)
    assert is_alive(grandchild_pid)
    group.shutdown()
    group.shutdown()  # second call is a no-op, not an error
    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived shutdown()"
    )


def test_use_after_close_raises() -> None:
    group = ProcessGroup()
    group.shutdown()
    with pytest.raises(ProcessError, match="already closed"):
        group.start(Command(PY, ["-c", "pass"]))


def test_start_returns_handle_with_pid() -> None:
    with ProcessGroup() as group:
        running = group.start(Command(PY, ["-c", "import time; time.sleep(30)"]))
        assert running.pid is not None
        assert running.pid > 0


def test_teardown_runs_when_exception_escapes_block(pid_file: pathlib.Path) -> None:
    grandchild_pid: int | None = None

    # try/except (not `pytest.raises`) so static analysis can see that the
    # post-block assertions are reachable after the exception is handled.
    try:
        with ProcessGroup() as group:
            group.start(spawn_grandchild_command(pid_file))
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


def test_teardown_on_garbage_collection(pid_file: pathlib.Path) -> None:
    # No `with`: drop the only reference and force collection. The Rust `Drop`
    # of the dropped ProcessGroup must reap the tree.
    group = ProcessGroup()
    group.start(spawn_grandchild_command(pid_file))
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
    assert str(excinfo.value)  # the reason is the exception message (no .message attr)
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


@pytest.mark.skipif(
    sys.platform != "win32", reason="Job Object active-process limit is Windows-specific"
)
def test_max_processes_enforcement_rejects_second_spawn() -> None:
    # `test_resource_limited_group_runs` only pins construction-time
    # acceptance of `max_processes` — this pins actual OS-level ENFORCEMENT:
    # the Windows Job Object's active-process ceiling really rejects a spawn
    # that would exceed it, rather than silently letting it through.
    with ProcessGroup(max_processes=1) as group:
        first = group.start(Command(PY, ["-c", "import time; time.sleep(5)"]))
        assert first.pid is not None
        with pytest.raises(ProcessError):
            group.start(Command(PY, ["-c", "import time; time.sleep(5)"]))


def test_group_shutdown_grace_kwarg_tears_down(pid_file: pathlib.Path) -> None:
    # The teardown-policy ceilings (`shutdown_grace`, `escalate_to_kill`) are not
    # resource limits, so construction needs no Job Object / cgroup root. This is
    # the only call site that passes `shutdown_grace=` — it pins the renamed kwarg
    # against both the stub (mypy here) and the Rust binding (a name mismatch would
    # raise at construction) — and proves the configured grace policy still reaps
    # the whole tree. Liveness is checked on the *grandchild* (reparented to init
    # and reaped on death); a direct child can linger as an unreaped POSIX zombie
    # that still answers `kill(pid, 0)`, so it is not a portable death signal.
    with ProcessGroup(shutdown_grace=0.5, escalate_to_kill=True) as group:
        group.start(spawn_grandchild_command(pid_file))
        grandchild_pid = read_pid_when_ready(pid_file, timeout=10.0)
        assert is_alive(grandchild_pid)
        group.shutdown()  # signal -> wait shutdown_grace -> escalate to hard kill

    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived shutdown_grace teardown"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="escalate_to_kill=False needs SIGTERM-trapping")
def test_escalate_to_kill_false_spares_a_surviving_child(tmp_path: pathlib.Path) -> None:
    # `escalate_to_kill=False`: graceful shutdown sends the signal, waits
    # `shutdown_grace`, and — unlike the default (True) — does NOT follow up
    # with a hard kill. A child that traps and ignores the signal must
    # therefore still be alive once `shutdown()` returns (previously zero
    # coverage: every other teardown test uses the `escalate_to_kill=True`
    # default, which always ends in a hard kill either way).
    marker = tmp_path / "got_term"
    ready = tmp_path / "ready"
    code = (
        "import signal, time\n"
        f"signal.signal(signal.SIGTERM, lambda *a: open({str(marker)!r}, 'w').write('x'))\n"
        f"open({str(ready)!r}, 'w').write('x')\n"
        "time.sleep(30)\n"
    )
    group = ProcessGroup(shutdown_grace=0.3, escalate_to_kill=False)
    running = group.start(Command(PY, ["-c", code]))
    survivor_pid = running.pid
    assert survivor_pid is not None

    # Wait for the child to actually install its SIGTERM handler before
    # signalling it — otherwise shutdown() can race the child's own startup
    # (interpreter boot + `signal.signal()`) and the SIGTERM arrives while the
    # default disposition (terminate, no marker) is still in effect.
    assert wait_until(ready.exists, timeout=5.0), "the child never became ready"

    group.shutdown()  # signal -> wait shutdown_grace -> NO escalation (spared)

    assert wait_until(marker.exists, timeout=5.0), "the child never ran its SIGTERM handler"
    assert is_alive(survivor_pid), "escalate_to_kill=False must spare a surviving child"

    # The Python wrapper is now closed (mirrors the crate's shutdown_ref call),
    # dropping its Arc<ProcessGroup> reference. Force collection and re-check:
    # the crate's Drop backstop must NOT retroactively kill the survivor it
    # just chose to spare (a group "left untouched" after a graceful shutdown
    # keeps its survivors, per the crate's own `shutdown_ref` docs).
    del group, running
    gc.collect()
    assert is_alive(survivor_pid), (
        "the spared survivor must not be killed by dropping the ProcessGroup afterwards"
    )

    # A literal same-object "shutdown, then spawn a new child into the SAME
    # group" reuse (the crate-level scenario 1.2.0's re-arm fix addresses) is
    # NOT exercisable through this binding: `ProcessGroup.shutdown()` always
    # closes the Python wrapper (`self.inner.take()`), so no further `.start()`
    # is possible on the same object — `test_use_after_close_raises` already
    # pins that. What IS verified here, and reachable: a brand-new
    # `ProcessGroup` still behaves normally afterwards (no cross-instance
    # state corruption from the prior group's spared survivor).
    with ProcessGroup() as fresh_group:
        fresh = fresh_group.start(Command(PY, ["-c", "import time; time.sleep(30)"]))
        fresh_pid = fresh.pid
        assert fresh_pid is not None
    assert wait_dead(fresh_pid, timeout=10.0), (
        "a fresh ProcessGroup's teardown must still hard-kill"
    )

    # Clean up the spared survivor so it doesn't leak past the test (this test
    # only runs on POSIX, per the skipif above).
    os.kill(survivor_pid, 9)
    assert wait_dead(survivor_pid, timeout=10.0)


def test_group_cpu_quota_kwarg_accepted() -> None:
    # The last unpinned `ProcessGroup` limit kwarg. Pin `cpu_quota=`'s name against
    # the stub (mypy) and the Rust binding (a rename would raise `TypeError` here,
    # before any enforcement). Enforcement needs a Job Object / cgroup-v2 root, so
    # skip where unenforceable — the name binding has already been exercised.
    try:
        with ProcessGroup(cpu_quota=1.0) as group:
            assert group.mechanism in {"job_object", "cgroup_v2", "process_group"}
    except (Unsupported, ResourceLimit):
        pytest.skip("cpu_quota not enforceable in this environment")


# --- signals / suspend / resume / terminate / stats -------------------------


def test_group_suspend_resume_terminate(tmp_path: pathlib.Path, pid_file: pathlib.Path) -> None:
    # A ticking child gives suspend/resume an observable effect (the tick file
    # must stall while suspended and advance again after resume); a separate
    # grandchild-spawning child proves kill_all reaches the whole tree, not just
    # the direct child (reparented to init and reaped, so its death is portable
    # — the killed direct child can persist as an unreaped zombie for the
    # lifetime of the still-open group handle).
    tick_file = tmp_path / "ticks"
    tick_code = (
        "import sys, time\n"
        "n = 0\n"
        "while True:\n"
        "    n += 1\n"
        "    open(sys.argv[1], 'w').write(str(n))\n"
        "    time.sleep(0.05)\n"
    )
    with ProcessGroup() as group:
        group.start(Command(PY, ["-c", tick_code, str(tick_file)]))
        group.start(spawn_grandchild_command(pid_file))
        grandchild_pid = read_pid_when_ready(pid_file, timeout=10.0)
        assert wait_until(tick_file.exists, timeout=5.0), "tick file was never written"

        try:
            group.suspend()
        except Unsupported:
            pytest.skip("suspend/resume not supported on this platform")
        ticks_at_suspend = tick_file.read_text()
        time.sleep(0.3)
        assert tick_file.read_text() == ticks_at_suspend, "ticks advanced while suspended"
        group.resume()
        assert wait_until(lambda: tick_file.read_text() != ticks_at_suspend, timeout=5.0), (
            "ticks did not resume after resume()"
        )

        group.kill_all()
        assert wait_dead(grandchild_pid, timeout=10.0), (
            f"grandchild {grandchild_pid} survived kill_all"
        )


def test_group_signal(pid_file: pathlib.Path) -> None:
    # Assert on the grandchild (reparented to init and reaped) rather than the
    # direct child, which can persist as an unreaped zombie that still answers
    # `kill(pid, 0)` for the lifetime of the still-open group handle.
    with ProcessGroup() as group:
        group.start(spawn_grandchild_command(pid_file))
        grandchild_pid = read_pid_when_ready(pid_file, timeout=10.0)
        try:
            group.signal("term")
        except Unsupported:
            pytest.skip("signal delivery not supported on this platform")
        assert wait_dead(grandchild_pid, timeout=10.0), (
            f"grandchild {grandchild_pid} survived group.signal('term')"
        )


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
