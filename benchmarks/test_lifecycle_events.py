"""Full lifecycle-event stream throughput for a mixed stdout/stderr workload."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from processkit import Command

from ._shared import PY

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


_LINE_COUNT = 256
_LIFECYCLE_CODE = (
    "import sys\n"
    f"for i in range({_LINE_COUNT}):\n"
    "    print('out:' + str(i), flush=True)\n"
    "    print('err:' + str(i), file=sys.stderr, flush=True)\n"
)


def test_lifecycle_events_throughput(benchmark: BenchmarkFixture) -> None:
    async def scenario() -> int:
        proc = await Command(PY, ["-c", _LIFECYCLE_CODE]).astart()
        events = [event async for event in proc.lifecycle_events()]
        finished = await proc.afinish()

        assert events[0].kind == "started"
        assert events[-1].kind == "exited"
        assert events[-1].outcome is not None
        assert events[-1].outcome.exited_zero
        assert finished.outcome.exited_zero
        return sum(event.kind in {"stdout", "stderr"} for event in events)

    def run() -> int:
        return asyncio.run(scenario())

    output_events = benchmark(run)
    assert output_events == _LINE_COUNT * 2
