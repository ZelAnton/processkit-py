"""PTY output relay throughput on POSIX and Windows ConPTY.

The child emits a bounded, fixed-width stream so the benchmark measures the
terminal relay and capture path rather than terminal line wrapping. POSIX
systems use their native pseudo-terminal implementation. Windows runs only
when the host advertises the ConPTY API introduced in Windows 10 1809.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING

import pytest

from processkit import Command

from ._shared import PY

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


_WINDOWS_CONPTY_MIN_BUILD = 17_763
_LINE_COUNT = 512
_LINE_WIDTH = 64
_PAYLOAD = "x" * _LINE_WIDTH
_PTY_CODE = (
    "import sys\n"
    f"payload = 'x' * {_LINE_WIDTH}\n"
    f"for i in range({_LINE_COUNT}): print(str(i).zfill(4) + ':' + payload)\n"
)


def _pty_supported() -> bool:
    """Return whether the current launcher can provide the requested PTY."""
    if os.name == "posix":
        return True
    if os.name == "nt":
        return sys.getwindowsversion().build >= _WINDOWS_CONPTY_MIN_BUILD
    return False


pytestmark = pytest.mark.skipif(
    not _pty_supported(),
    reason="PTY benchmark requires a POSIX pty or Windows ConPTY (10 1809+)",
)


def test_pty_output_relay(benchmark: BenchmarkFixture) -> None:
    async def scenario() -> int:
        result = await Command(PY, ["-c", _PTY_CODE]).pty(cols=120, rows=40).aoutput()
        assert result.is_success
        lines = result.stdout.splitlines()
        payload_lines = [line for line in lines if line.endswith(_PAYLOAD)]
        assert len(payload_lines) == _LINE_COUNT
        assert payload_lines[0].endswith(f"0000:{_PAYLOAD}")
        assert payload_lines[-1].endswith(f"{_LINE_COUNT - 1:04d}:{_PAYLOAD}")
        return len(payload_lines)

    def run() -> int:
        return asyncio.run(scenario())

    line_count = benchmark(run)
    assert line_count == _LINE_COUNT
