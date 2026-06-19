"""Post-build smoke test for a packaged wheel.

Run by cibuildwheel's `test-command` against the freshly built wheel on each
platform: it must import, spawn a child via the compiled extension, and contain
a process tree in a group. Deliberately light — the full suite runs in CI; this
only confirms the *wheel artifact* loads and works on the target OS.
"""

from __future__ import annotations

import sys

from processkit import Command, ProcessGroup

result = Command(sys.executable, ["-c", "print('ok')"]).output()
assert result.stdout.strip() == "ok", result
assert result.is_success, result

with ProcessGroup() as group:
    group.start(Command(sys.executable, ["-c", "import time; time.sleep(0.1)"]))
    assert group.mechanism in {"job_object", "cgroup_v2", "process_group"}

print("smoke OK on", sys.platform)
