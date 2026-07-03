"""Sandbox an untrusted child tree with kernel-enforced resource limits.

The differentiator versus a plain subprocess wrapper: a ``ProcessGroup`` can cap
a whole tree's memory, process count, and CPU — enforced by the Windows Job
Object or a Linux cgroup v2. We also lock the command itself down (empty
environment, bounded captured output, die-with-parent) so a misbehaving tool
cannot run away with the machine.

Kernel resource limits need privileges the environment may not grant: inside a
container, a systemd user session, or a non-root cgroup the kernel forbids them,
and macOS (a POSIX process group) has no equivalent. processkit is honest about
this — it raises rather than silently ignoring the cap — so this example catches
that and degrades to "contained, but uncapped", staying runnable anywhere.

Run it:  python examples/04_sandbox_resource_limits.py
"""

from __future__ import annotations

import sys

from processkit import Command, ProcessGroup, ResourceLimit, Unsupported

_MiB = 1024 * 1024

# A short-lived stand-in for an untrusted tool doing a little work. The sleep keeps
# it alive long enough for the stats() snapshot below to actually catch it running.
_TOOL = "import time; time.sleep(2)"


def _locked_down_tool() -> Command:
    """An untrusted command tied down independently of the group's limits: an empty
    environment (only PATH allow-listed), a bounded captured output that *fails* on
    overflow rather than silently dropping, and kill-on-parent-death so it cannot
    outlive us even without explicit teardown."""
    return (
        Command(sys.executable, ["-c", _TOOL])
        .env_clear()
        .inherit_env(["PATH"])
        .kill_on_parent_death()
        .output_limit(max_bytes=8 * _MiB, on_overflow="error")
    )


def _run(
    *,
    max_memory: int | None = None,
    max_processes: int | None = None,
    cpu_quota: float | None = None,
) -> None:
    with ProcessGroup(
        max_memory=max_memory,
        max_processes=max_processes,
        cpu_quota=cpu_quota,
    ) as group:
        group.start(_locked_down_tool())
        print(f"  mechanism           : {group.mechanism}")
        # A stats() snapshot: active_process_count is always available; peak memory /
        # CPU are populated only where the kernel accounts for the whole tree (Windows,
        # Linux cgroup) and are None on the POSIX process-group backend. Guard the call
        # anyway — a locked-down environment can refuse even the snapshot.
        try:
            stats = group.stats()
            print(f"  active processes    : {stats.active_process_count}")
            print(f"  peak memory (bytes) : {stats.peak_memory_bytes}")  # None on process-group
        except Unsupported:
            print("  usage stats         : unavailable in this environment")


def main() -> None:
    try:
        _run(max_memory=512 * _MiB, max_processes=64, cpu_quota=1.0)
        print("ran the tool under kernel-enforced memory / process / CPU limits.")
    except (ResourceLimit, Unsupported) as exc:
        print(f"kernel resource limits are not permitted here: {exc}")
        print("(typical in containers / non-root cgroups / macOS) - running uncapped.")
        _run()
        print("ran the tool contained, but without resource caps.")


if __name__ == "__main__":
    main()
