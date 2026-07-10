"""POSIX `fork()` safety for the process-global tokio runtime.

`pyo3-async-runtimes` keeps processkit's tokio runtime in a process-global
`OnceLock`. Once processkit has run a sync/async verb the runtime is
initialized with background worker threads. A POSIX `fork()` copies the
runtime struct (and its "initialized" flag) into the child but **not** those
worker threads — only the forking thread survives — so any lock a vanished
worker held at fork time is frozen forever. Driving the copied runtime in the
child (another processkit verb) would hang or panic with no recovery.

The binding therefore refuses fast, with a clear ``ProcessError``, when a verb
is driven from a process that `fork()`ed after the runtime was initialized in
its parent. This test proves the contract end to end:

* the fork child fails fast (no hang, no orphaned subprocess), and
* the parent keeps working afterwards, for both sync and async verbs.

The whole scenario runs inside a subprocess under a hard external timeout, so a
regression that reintroduces the deadlock fails the test instead of wedging the
suite. It is POSIX-only: there is no `os.fork` on Windows (and no hazard there).
"""

from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

from ._liveness import is_alive
from .conftest import PY

pytestmark = pytest.mark.skipif(
    not hasattr(os, "fork"), reason="os.fork() is POSIX-only; no fork hazard elsewhere"
)

# Exit codes the driver's forked child uses to report its outcome back to the
# parent (and, via the parent, to this test). Distinct values so a failure names
# exactly what went wrong instead of a bare "child died".
_CHILD_REFUSED_CLEANLY = 44  # got the expected fast, fork-aware ProcessError
_CHILD_WRONG_ERROR = 45  # a ProcessError, but not the fork-aware one
_CHILD_NO_ERROR = 43  # the verb neither hung nor raised (unexpected here)
_CHILD_OTHER_EXC = 46  # some other exception
_PARENT_CHILD_HUNG = 10  # the child never returned: it deadlocked the runtime
_PARENT_BAD_CHILD_CODE = 11  # the child exited, but not with the clean-refusal code

# Runs as `python -c <DRIVER> <marker_pid_file>`.
#
# The child asks processkit to run a command that, *if it were ever spawned*,
# writes its own PID to the marker file and sleeps for a long time. With the
# fork guard working, the verb is refused before any OS process is spawned, so
# the marker file is never written — the test asserts its absence to prove no
# subprocess was orphaned. If the guard regressed, the command would be spawned
# and then hang on the dead runtime; the parent's bounded reap SIGKILLs the hung
# child, leaving that grandchild orphaned and alive — which the marker file then
# reveals.
_DRIVER = rf"""
import asyncio
import os
import sys
import time

import processkit

marker = sys.argv[1]

# 1) Use processkit in the parent so the tokio runtime is really initialized
#    (workers spawned) *before* the fork — this is the hazardous ordering.
assert processkit.Command(sys.executable, ["-c", "pass"]).output().is_success

# 2) fork.
pid = os.fork()
if pid == 0:
    # CHILD: another processkit verb here must NOT hang or panic. It must fail
    # fast with a clear, fork-aware ProcessError. Any spawned subprocess would
    # write `marker` first, so a clean refusal leaves `marker` absent.
    would_orphan = (
        "import os, sys, time\n"
        "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    code = {_CHILD_NO_ERROR}
    try:
        processkit.Command(sys.executable, ["-c", would_orphan, marker]).output()
    except processkit.ProcessError as exc:
        msg = str(exc).lower()
        if "fork" in msg and "spawn" in msg:
            code = {_CHILD_REFUSED_CLEANLY}
        else:
            code = {_CHILD_WRONG_ERROR}
    except BaseException:
        code = {_CHILD_OTHER_EXC}
    os._exit(code)

# PARENT: reap the child within a bounded window. Exceeding it means the child
# deadlocked driving the copied runtime — the exact regression we guard against.
deadline = time.monotonic() + 15.0
status = None
while time.monotonic() < deadline:
    waited, st = os.waitpid(pid, os.WNOHANG)
    if waited == pid:
        status = st
        break
    time.sleep(0.05)

if status is None:
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    sys.stderr.write("child hung driving the runtime after fork\n")
    os._exit({_PARENT_CHILD_HUNG})

child_code = os.waitstatus_to_exitcode(status)
if child_code != {_CHILD_REFUSED_CLEANLY}:
    sys.stderr.write("child exit code " + str(child_code) + "\n")
    os._exit({_PARENT_BAD_CHILD_CODE})

# PARENT keeps working after the child: sync AND async verbs both still run on
# the parent's (untouched) runtime.
assert processkit.Command(sys.executable, ["-c", "pass"]).output().is_success


async def _use_async():
    result = await processkit.Command(sys.executable, ["-c", "pass"]).aoutput()
    assert result.is_success


asyncio.run(_use_async())

# `os._exit()` (used throughout this driver to avoid post-fork interpreter
# cleanup) skips the atexit stdout flush, and under `capture_output=True`
# this stdout is a pipe — block-buffered, not line-buffered — so the success
# marker must be flushed explicitly or it is silently dropped while the exit
# code still reads 0. Flush before exiting so the parent test observes "OK".
print("OK", flush=True)
os._exit(0)
"""


def test_use_fork_use_refuses_without_hanging_or_orphaning(tmp_path: pathlib.Path) -> None:
    marker = tmp_path / "forked-grandchild.pid"

    try:
        result = subprocess.run(
            [PY, "-c", _DRIVER, str(marker)],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired as exc:
        # The whole scenario wedged past the external safety net: a real deadlock
        # regression (the bounded in-driver reap should have failed it far sooner).
        pytest.fail(f"fork-safety driver hung: stdout={exc.stdout!r} stderr={exc.stderr!r}")

    # No subprocess should ever have been spawned by the refused child, so nothing
    # can be orphaned. If the marker exists the guard regressed: clean up the leak
    # and surface it.
    if marker.exists():
        leaked = int(marker.read_text().strip())
        alive = is_alive(leaked)
        if alive:
            os.kill(leaked, 9)
        pytest.fail(
            f"fork child spawned an orphaned subprocess (pid {leaked}, "
            f"alive={alive}) instead of refusing before spawn"
        )

    assert result.returncode == 0, (
        f"fork-safety driver failed (code {result.returncode}); "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # Use a slice (`[-1:]`) rather than an index (`[-1]`) so an unexpectedly
    # empty stdout fails as a clear, informative assertion — not a bare
    # IndexError that hides what the driver actually did.
    tail = result.stdout.strip().splitlines()[-1:]
    assert tail == ["OK"], (
        f"fork-safety driver did not confirm success with a trailing 'OK'; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
