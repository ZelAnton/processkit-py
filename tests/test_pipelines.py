"""Command pipelines (`a | b` / `a.pipe(b)`): ordered run/exit_code, the
binary-tail bytes capture, and pipefail — a non-last stage's failure is not
masked by a clean final stage (unlike a shell `|`).
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import time

import pytest

from processkit import (
    BytesResult,
    CancellationToken,
    Cancelled,
    Command,
    NonZeroExit,
    Pipeline,
    ProcessResult,
)

from ._liveness import read_pid_when_ready, wait_dead
from .conftest import spawn_grandchild_command

PY = sys.executable

_UPPER = "import sys; [print(line.strip().upper()) for line in sys.stdin]"


def test_pipeline_run_sync() -> None:
    pipe = Command(PY, ["-c", "print('a'); print('b'); print('c')"]) | Command(PY, ["-c", _UPPER])
    assert pipe.run() == "A\nB\nC"


def test_pipeline_run_async_and_pipe_method() -> None:
    async def scenario() -> str:
        pipe = Command(PY, ["-c", "print('x'); print('y')"]).pipe(Command(PY, ["-c", _UPPER]))
        return await pipe.arun()

    assert asyncio.run(scenario()) == "X\nY"


def test_pipeline_exit_code() -> None:
    # The downstream stage drains stdin before exiting: a consumer that exits
    # WITHOUT reading can race the producer into writing to a closed pipe
    # (BrokenPipe -> the producer's interpreter exits 120, which pipefail then
    # surfaces as the pipeline code). Reading stdin keeps both stages clean, so
    # the pipeline exit code is a deterministic 0.
    upstream = Command(PY, ["-c", "print('hi')"])
    downstream = Command(PY, ["-c", "import sys; sys.stdin.read(); sys.exit(0)"])
    assert (upstream | downstream).exit_code() == 0


def test_pipeline_output_bytes_captures_binary_tail() -> None:
    # A pipeline ending in a binary producer can capture raw (non-UTF-8) bytes.
    produce = Command(PY, ["-c", "import sys; sys.stdout.buffer.write(bytes([0, 1, 2, 255]))"])
    echo = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"
    passthrough = Command(PY, ["-c", echo])
    result = (produce | passthrough).output_bytes()
    assert isinstance(result, BytesResult)
    assert result.stdout == bytes([0, 1, 2, 255])
    assert result.is_success


def test_pipeline_aoutput_bytes_captures_binary_tail() -> None:
    echo = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"

    async def scenario() -> BytesResult:
        produce = Command(PY, ["-c", "import sys; sys.stdout.buffer.write(bytes([3, 4, 255]))"])
        return await (produce | Command(PY, ["-c", echo])).aoutput_bytes()

    result = asyncio.run(scenario())
    assert result.stdout == bytes([3, 4, 255])


def test_pipeline_pipefail_propagates_non_last_stage_failure() -> None:
    # The whole point over a shell `|`: a failure in a NON-last stage is not
    # masked by a clean final stage. The pipeline's code is the first unclean
    # stage's, and `run()` raises for it.
    bad = Command(PY, ["-c", "import sys; sys.exit(3)"])  # first stage fails
    tail = Command(PY, ["-c", "import sys; sys.stdin.read(); print('tail-ran')"])

    result = (bad | tail).output()
    assert result.code == 3, "a non-last stage's failure must propagate to the pipeline exit code"
    assert not result.is_success

    with pytest.raises(NonZeroExit) as excinfo:
        (bad | tail).run()
    assert excinfo.value.code == 3


def test_pipeline_probe_sync() -> None:
    # `probe` routes to the pipeline's exit code: 0 -> True, non-zero -> False.
    ok = Command(PY, ["-c", "print('hi')"]) | Command(PY, ["-c", _UPPER])
    assert ok.probe() is True
    bad = Command(PY, ["-c", "import sys; sys.exit(1)"]) | Command(
        PY, ["-c", "import sys; sys.stdin.read()"]
    )
    assert bad.probe() is False


def test_pipeline_async_verbs_each_route_correctly() -> None:
    # Drive the async pipeline verbs with no other coverage — aoutput / aexit_code
    # / aprobe. Each returns an awaitable, so a forwarder wired to the wrong helper
    # would still compile and pass stubtest; only calling each one proves it routes
    # correctly.
    def _pipe() -> Pipeline:
        return Command(PY, ["-c", "print('hi')"]) | Command(PY, ["-c", _UPPER])

    async def scenario() -> None:
        result = await _pipe().aoutput()
        assert result.stdout.strip() == "HI"
        assert result.is_success
        assert await _pipe().aexit_code() == 0
        assert await _pipe().aprobe() is True

    asyncio.run(scenario())


def test_pipeline_timeout_is_captured() -> None:
    # A pipeline-level timeout bounds the whole pipeline; a slow final stage trips
    # it and the result reflects the timeout rather than hanging.
    pipe = Command(PY, ["-c", "print('go')"]) | Command(PY, ["-c", "import time; time.sleep(5)"])
    result = pipe.timeout(0.3).output()
    assert result.timed_out
    assert not result.is_success


def test_pipeline_stage_timeout_kills_its_whole_subtree(pid_file: pathlib.Path) -> None:
    # processkit 2.1.0: each pipeline stage now spawns into its OWN kill-on-drop
    # sub-group, instead of the whole chain sharing one group. A per-stage
    # `Command.timeout()` (set BEFORE `|`/`.pipe()`) therefore tears down that
    # stage's whole subtree, including a grandchild it forks off -- previously
    # the stage's own kill reached only its direct child, so a forking stage's
    # grandchild survived, kept the pipe open, and stalled the downstream stage.
    # Keep this comfortably above Windows process-start latency under xdist:
    # the timeout must fire after the grandchild PID is observable, otherwise
    # the probe races the very timeout whose teardown behavior it is testing.
    spawner = spawn_grandchild_command(pid_file).timeout(2.0)
    downstream = Command(PY, ["-c", "import sys; sys.stdin.read()"])
    pipe = spawner | downstream

    async def stream_pipe() -> ProcessResult:
        return await pipe.aoutput()

    async def driver() -> tuple[ProcessResult, int]:
        task = asyncio.ensure_future(stream_pipe())
        grandchild = await asyncio.to_thread(read_pid_when_ready, pid_file, 10.0)
        result = await task
        return result, grandchild

    result, grandchild = asyncio.run(asyncio.wait_for(driver(), timeout=20.0))
    assert result.timed_out, "the first stage's own timeout must be reported by the pipeline"
    assert not result.is_success
    assert wait_dead(grandchild, timeout=10.0), (
        "the grandchild of a timed-out stage must not outlive that stage's own kill"
    )


def test_pipeline_stage_failure_proactively_tears_down_a_quiet_upstream(
    tmp_path: pathlib.Path,
) -> None:
    # processkit 2.1.0: a checked stage failure now tears the rest of the chain
    # down PROACTIVELY instead of only passively through pipe EOF. Here the
    # upstream stage never writes anything downstream reads and sleeps far
    # longer than the test timeout; only a proactive teardown (triggered by the
    # downstream stage's own checked failure, exit(7)) lets the whole pipeline
    # finish quickly -- the old, passive behavior would keep the quiet upstream
    # running until its own 30s sleep elapsed (or an outer bound fired), holding
    # the pipeline open.
    upstream_pid_file = tmp_path / "upstream.pid"
    quiet_upstream = Command(
        PY,
        [
            "-c",
            "import os, sys, time;"
            "f = open(sys.argv[1], 'w');"
            "f.write(str(os.getpid()));"
            "f.flush();"
            "f.close();"
            "time.sleep(30)",
            str(upstream_pid_file),
        ],
    )
    # A small head start lets the upstream's pid-file write above land before
    # this exits and triggers proactive teardown -- deterministic, not a race:
    # 0.3s dwarfs interpreter-startup + a single write() but stays far below
    # the 10s bound asserted below.
    failing_downstream = Command(PY, ["-c", "import sys, time; time.sleep(0.3); sys.exit(7)"])
    pipe = quiet_upstream | failing_downstream

    async def scenario() -> ProcessResult:
        return await pipe.aoutput()

    started = time.monotonic()
    result = asyncio.run(asyncio.wait_for(scenario(), timeout=20.0))
    elapsed = time.monotonic() - started
    assert result.code == 7, "the actually-failed (last) stage keeps the blame"
    assert not result.is_success
    # Structural check: the real invariant under test is that the quiet
    # upstream is actually torn down, not merely that the call *returned*
    # quickly -- a bug could abandon the wait without truly killing it, and a
    # fast host could mask that on timing alone. The wall-clock bound below
    # stays as a secondary, coarser signal.
    upstream_pid = read_pid_when_ready(upstream_pid_file, timeout=10.0)
    assert wait_dead(upstream_pid, timeout=5.0), (
        "the quiet upstream must be dead/reaped once the pipeline returns, not merely abandoned"
    )
    assert elapsed < 10.0, (
        "a checked stage failure must tear the chain down proactively, "
        f"not wait on the quiet upstream's own 30s sleep (took {elapsed:.1f}s)"
    )


def test_pipeline_cancel_on_tears_down_the_whole_chain() -> None:
    async def scenario() -> None:
        token = CancellationToken()
        pipe = (
            Command(PY, ["-c", "print('go')"]) | Command(PY, ["-c", "import time; time.sleep(30)"])
        ).cancel_on(token)
        task = asyncio.ensure_future(pipe.arun())
        await asyncio.sleep(0.2)
        token.cancel()
        with pytest.raises(Cancelled):
            await task

    asyncio.run(scenario())
