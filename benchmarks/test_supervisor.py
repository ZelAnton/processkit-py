"""Live Supervisor session with bounded crash/restart churn."""

from __future__ import annotations

from typing import TYPE_CHECKING

from processkit import Command, Supervisor

from ._shared import PY

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


_RESTART_COUNT = 6
_SUPERVISED_CODE = "import sys; print('attempt', flush=True); sys.exit(7)"


def test_live_supervisor_session_restarts(benchmark: BenchmarkFixture) -> None:
    def run() -> int:
        session = Supervisor(
            Command(PY, ["-c", _SUPERVISED_CODE]),
            restart="on_crash",
            max_restarts=_RESTART_COUNT,
            backoff_initial=0.001,
            backoff_factor=1.0,
            max_backoff=0.001,
            jitter=False,
        ).start()
        outcome = session.wait()
        assert outcome.restarts == _RESTART_COUNT
        assert outcome.stopped == "restarts_exhausted"
        assert not outcome.final_result.is_success
        return outcome.restarts

    restarts = benchmark(run)
    assert restarts == _RESTART_COUNT
