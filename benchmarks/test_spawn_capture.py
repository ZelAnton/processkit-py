"""Spawn + capture a single short-lived command: `processkit` vs the two
"naive" ways of doing the same thing from stdlib — `subprocess.run` and
`asyncio.create_subprocess_exec` + `communicate()`. Same payload on all
three (`_shared.CAPTURE_CODE`) so the comparison isolates the bridge's
per-call overhead rather than a differing workload.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING

from processkit import Command

from ._shared import CAPTURE_CODE, PY

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

_EXPECTED = "x" * 4096


def test_spawn_capture_processkit(benchmark: BenchmarkFixture) -> None:
    def run() -> str:
        result = Command(PY, ["-c", CAPTURE_CODE]).output()
        assert result.is_success
        return result.stdout

    stdout = benchmark(run)
    assert stdout == _EXPECTED


def test_spawn_capture_subprocess(benchmark: BenchmarkFixture) -> None:
    def run() -> str:
        result = subprocess.run(
            [PY, "-c", CAPTURE_CODE], capture_output=True, text=True, check=True
        )
        return result.stdout

    stdout = benchmark(run)
    assert stdout == _EXPECTED


def test_spawn_capture_asyncio_subprocess(benchmark: BenchmarkFixture) -> None:
    # `asyncio.run` opens/closes a fresh event loop per call — the same
    # "naive per-call" shape a caller reaching for asyncio.subprocess without
    # already running inside a long-lived loop would write.
    async def scenario() -> str:
        proc = await asyncio.create_subprocess_exec(
            PY, "-c", CAPTURE_CODE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _stderr = await proc.communicate()
        assert proc.returncode == 0
        return stdout.decode()

    def run() -> str:
        return asyncio.run(scenario())

    stdout = benchmark(run)
    assert stdout == _EXPECTED
