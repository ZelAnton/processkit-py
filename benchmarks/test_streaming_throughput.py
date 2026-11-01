"""Line-streaming throughput: `RunningProcess.stdout_lines()` (see
`docs/streaming.md`) draining a child that writes a known number of lines as
fast as it can, end to end (spawn through `afinish()`).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from processkit import Command

from ._shared import PY

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

#: This line count makes the loop cost greater than the fixed spawn cost.
#: The count also keeps each round short.
#: The weekly benchmark job uses pytest-benchmark to select the number of rounds.
_LINE_COUNT = 5_000

_PRODUCER = f"for i in range({_LINE_COUNT}): print(i)"


def test_stdout_lines_throughput(benchmark: BenchmarkFixture) -> None:
    async def scenario() -> int:
        proc = await Command(PY, ["-c", _PRODUCER]).astart()
        count = 0
        async for _line in proc.stdout_lines():
            count += 1
        finished = await proc.afinish()
        assert finished.exited_zero
        return count

    def run() -> int:
        return asyncio.run(scenario())

    lines = benchmark(run)
    assert lines == _LINE_COUNT
