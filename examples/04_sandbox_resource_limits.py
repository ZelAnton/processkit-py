"""Sandbox an agent's untrusted tool calls with kernel-enforced resource limits.

The differentiator versus a plain subprocess wrapper: a ``ProcessGroup`` can cap
a whole tree's memory, process count, and CPU — enforced by the Windows Job
Object or a Linux cgroup v2. This example plays out the full recipe from
docs/sandboxing.md for an agent making a couple of tool calls in one sandboxed
session: each call is locked down independently (empty environment, bounded
captured output, a per-call timeout, die-with-parent), and the whole session
shares one resource-limited group that is torn down as a unit at the end.

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

# Two short-lived stand-ins for the tool calls an agent might make in a row: a
# quick one and a slower one, both inside the same sandboxed group. The sleeps
# are just there to make each call take a visibly non-zero amount of time,
# comfortably inside the per-call timeout below — group.output() blocks until
# each call finishes, so by the time stats() is checked below every call has
# already completed (active_process_count is 0 at that point; peak_memory
# still reflects the tree's usage accumulated over the whole session).
_TOOL_CALLS = [
    ("quick tool call", "import time; time.sleep(0.2)"),
    ("slow tool call", "import time; time.sleep(2)"),
]


def _locked_down_tool(code: str) -> Command:
    """The per-call recipe from docs/sandboxing.md, in order: a locked-down
    environment (only PATH allow-listed), bounded captured output that *fails*
    on overflow rather than silently dropping, a per-call timeout so no single
    call can hang forever, and kill-on-parent-death so it cannot outlive us
    even without explicit teardown."""
    return (
        Command(sys.executable, ["-c", code])
        .env_clear()
        .inherit_env(["PATH"])
        .output_limit(max_bytes=8 * _MiB, on_overflow="error")
        .timeout(30.0)
        .kill_on_parent_death()
    )


def _run_agent_session(
    *,
    max_memory: int | None = None,
    max_processes: int | None = None,
    cpu_quota: float | None = None,
) -> None:
    # The group is the last ingredient of the recipe: whole-tree resource limits,
    # shared by every tool call the agent makes in this session, torn down as one
    # unit on exit (the fifth ingredient — teardown — is this `with` block's exit).
    with ProcessGroup(
        max_memory=max_memory,
        max_processes=max_processes,
        cpu_quota=cpu_quota,
    ) as group:
        print(f"  mechanism           : {group.mechanism}")
        for name, code in _TOOL_CALLS:
            result = group.output(_locked_down_tool(code))
            print(f"  {name:<15}: exit={result.code} timed_out={result.timed_out}")
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
    # The group's context manager exit reaps the whole tree here — every tool call's
    # process, and anything it forked, is gone regardless of how the block above ran.


def main() -> None:
    try:
        _run_agent_session(max_memory=512 * _MiB, max_processes=64, cpu_quota=1.0)
        print("ran the agent's tool calls under kernel-enforced memory / process / CPU limits.")
    except (ResourceLimit, Unsupported) as exc:
        print(f"kernel resource limits are not permitted here: {exc}")
        print("(typical in containers / non-root cgroups / macOS) - running uncapped.")
        _run_agent_session()
        print("ran the agent's tool calls contained, but without resource caps.")


if __name__ == "__main__":
    main()
