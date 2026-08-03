"""Completion-order streaming for a bounded batch of output-producing commands."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from processkit import Command, ProcessResult, aoutput_as_completed

from ._shared import PY

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


_BATCH_SIZE = 16
_CONCURRENCY = 4
_PAYLOAD_SIZE = 2_048
_BATCH_CODE = (
    "import sys\n"
    "index = int(sys.argv[1])\n"
    f"print(str(index).zfill(2) + ':' + ('x' * {_PAYLOAD_SIZE}))\n"
)


def test_aoutput_as_completed_throughput(benchmark: BenchmarkFixture) -> None:
    commands = [Command(PY, ["-c", _BATCH_CODE, str(index)]) for index in range(_BATCH_SIZE)]
    benchmark.group = f"aoutput_as_completed(concurrency={_CONCURRENCY})"

    async def scenario() -> int:
        completed: set[int] = set()
        async for index, result in aoutput_as_completed(commands, concurrency=_CONCURRENCY):
            assert isinstance(result, ProcessResult)
            assert result.is_success
            assert result.stdout.startswith(f"{index:02d}:")
            completed.add(index)
        return len(completed)

    def run() -> int:
        return asyncio.run(scenario())

    completed = benchmark(run)
    assert completed == _BATCH_SIZE
