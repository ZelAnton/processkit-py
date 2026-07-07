"""`output_all` / `aoutput_all` at different concurrency levels — bounded
parallel batches of short-lived commands (see `docs/cookbook.md`'s
"many commands, bounded concurrency" recipe).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from processkit import Command, aoutput_all, output_all

from ._shared import NOOP_CODE, PY

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

#: Concurrency == batch size in every case below: N commands, all allowed to
#: run at once, at each of the sizes the task calls out (1/10/50) — that
#: isolates how the batch dispatch machinery itself scales, rather than
#: mixing in a fixed backlog queued behind a narrower `concurrency=`.
_CONCURRENCIES = (1, 10, 50)


@pytest.mark.parametrize("concurrency", _CONCURRENCIES)
def test_output_all_concurrency(benchmark: BenchmarkFixture, concurrency: int) -> None:
    commands = [Command(PY, ["-c", NOOP_CODE]) for _ in range(concurrency)]
    benchmark.group = f"output_all(concurrency={concurrency})"

    def run() -> None:
        results = output_all(commands, concurrency=concurrency)
        assert len(results) == concurrency

    benchmark(run)


@pytest.mark.parametrize("concurrency", _CONCURRENCIES)
def test_aoutput_all_concurrency(benchmark: BenchmarkFixture, concurrency: int) -> None:
    commands = [Command(PY, ["-c", NOOP_CODE]) for _ in range(concurrency)]
    benchmark.group = f"aoutput_all(concurrency={concurrency})"

    async def scenario() -> int:
        results = await aoutput_all(commands, concurrency=concurrency)
        return len(results)

    def run() -> None:
        count = asyncio.run(scenario())
        assert count == concurrency

    benchmark(run)
