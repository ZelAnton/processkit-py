"""No-orphan guarantee: a ProcessGroup reaps a whole tree, grandchildren included.

This is the core reason processkit exists. We start two children that each spawn
a *grandchild*; a naive ``subprocess`` call tracks only the direct child, so the
grandchildren would outlive a timeout, an exception, or a cancelled task. Inside
a ``ProcessGroup``, leaving the ``with`` block tears the tree down: kernel-enforced
on Windows (Job Object) and Linux (cgroup v2), and best-effort on the POSIX
process-group fallback (macOS/BSD) — there a grandchild that calls ``setsid()`` can
escape, which is why ``ProcessGroup.mechanism`` reports the active backend rather
than pretending. The children below don't ``setsid``, so they are reaped everywhere.

Run it:  python examples/01_no_orphan_guarantee.py
"""

from __future__ import annotations

import sys
import time

from processkit import Command, ProcessGroup

# A child that spawns an untracked grandchild (a 60-second sleeper) and then sleeps
# itself. Neither does any real work — they stand in for a build tool's compiler
# children, a server's workers, or an agent tool's helper processes.
_CHILD = (
    "import subprocess, sys, time; "
    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
    "time.sleep(60)"
)


def main() -> None:
    with ProcessGroup() as group:
        group.start(Command(sys.executable, ["-c", _CHILD]))
        group.start(Command(sys.executable, ["-c", _CHILD]))

        # Give the children a moment to spawn their grandchildren, then look at
        # what the kernel container is tracking.
        time.sleep(0.5)
        members = group.members()
        print(f"containment mechanism : {group.mechanism}")
        print(f"processes in the tree : {len(members)} (PIDs {members})")
        print("leaving the block - the whole tree is about to be reaped...")

    # Past this line the group is gone: both children AND their grandchildren
    # have been killed as a unit — including the grandchildren we never held a
    # handle to.
    print("done - every child and grandchild has been torn down.")


if __name__ == "__main__":
    main()
