"""Command pipelines (`a | b` / `a.pipe(b)`): ordered run/exit_code, the
binary-tail bytes capture, and pipefail — a non-last stage's failure is not
masked by a clean final stage (unlike a shell `|`).
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from processkit import BytesResult, Command, NonZeroExit, Pipeline

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
