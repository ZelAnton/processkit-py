"""`ProcessGroup` start/exit — the cost of creating the group's kernel
container (Job Object / cgroup-v2 / process group, see `docs/platforms.md`),
entering the context manager, starting one short-lived child into it, and
tearing the whole tree down on exit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from processkit import Command, ProcessGroup

from ._shared import NOOP_CODE, PY

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


def test_process_group_start_exit(benchmark: BenchmarkFixture) -> None:
    def run() -> None:
        with ProcessGroup() as group:
            proc = group.start(Command(PY, ["-c", NOOP_CODE]))
            outcome = proc.outcome()
            assert outcome.exited_zero

    benchmark(run)
