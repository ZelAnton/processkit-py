"""Event-loop compatibility matrix: `docs/event-loops.md` claims uvloop and
anyio-on-asyncio are "fully supported" / "works today" alongside plain
asyncio. Nothing enforced that before this file — every other async test in
the suite drives `asyncio.run` directly. This module reruns a representative
slice of the async surface (`aoutput`, `astart` + streaming, task
cancellation, `aoutput_all`, and the readiness helpers) under all three real
runtimes via a single parametrized `run_scenario` fixture, so a regression in
any of them (e.g. the `pyo3-async-runtimes` bridge growing an asyncio-loop-
internals dependency) fails a test instead of silently invalidating the docs.

uvloop ships no Windows wheels, so the uvloop backend is skipped (with an
explicit reason, not silently) on Windows. Both uvloop and anyio live in the
optional `event-loops` dependency group (`uv sync --group event-loops`), not
in `dev` — when either package is absent (the ordinary dev/CI `test` job),
its backend parameter is skipped, and the plain-asyncio backend still runs.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from processkit import Command, ProcessGroup, ProcessResult, aoutput_all, wait_for_port, wait_until

from ._liveness import is_alive, read_pid_when_ready, wait_dead
from ._programs import free_port
from .conftest import PY, spawn_grandchild_command

try:
    import uvloop  # type: ignore[import-not-found]
except ImportError:
    uvloop = None

try:
    import anyio  # type: ignore[import-not-found]
except ImportError:
    anyio = None

# Prints N lines (flushed so they stream) then exits -- shared with test_streaming.py.
_PRINT_LINES = "[print(f'line{i}', flush=True) for i in range(5)]"

# stdout + stderr on both streams -- shared with test_streaming.py.
_BOTH_STREAMS = (
    "import sys; "
    "print('out1', flush=True); "
    "sys.stderr.write('err1\\n'); sys.stderr.flush(); "
    "print('out2', flush=True)"
)

#: A `Scenario` is a zero-argument async callable (`async def scenario() -> T`),
#: the same shape every test below defines locally, mirroring the rest of the
#: suite's `asyncio.run(scenario())` convention.
Scenario = Callable[[], Coroutine[Any, Any, Any]]
RunScenario = Callable[[Scenario], Any]


def _run_under_asyncio(scenario: Scenario) -> Any:
    return asyncio.run(scenario())


def _run_under_uvloop(scenario: Scenario) -> Any:
    # Deliberately not `asyncio.set_event_loop_policy` + `asyncio.run`: the
    # policy functions were deprecated in Python 3.14 (and this suite's
    # `filterwarnings = ["error", ...]` turns any DeprecationWarning into a
    # hard failure). A private loop built directly via `uvloop.new_event_loop()`
    # and driven with `run_until_complete` needs no global/deprecated API.
    assert uvloop is not None
    loop = uvloop.new_event_loop()
    try:
        return loop.run_until_complete(scenario())
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            loop.close()


def _run_under_anyio_asyncio(scenario: Scenario) -> Any:
    assert anyio is not None
    # anyio's asyncio backend runs a real asyncio loop underneath (see
    # docs/event-loops.md) -- `anyio.run` calls `scenario()` and awaits it.
    return anyio.run(scenario, backend="asyncio")


_BACKENDS = [
    pytest.param(_run_under_asyncio, id="asyncio"),
    pytest.param(
        _run_under_uvloop,
        id="uvloop",
        marks=[
            pytest.mark.skipif(
                sys.platform == "win32",
                reason="uvloop ships no Windows wheels",
            ),
            pytest.mark.skipif(
                uvloop is None,
                reason="uvloop not installed -- run `uv sync --group event-loops`",
            ),
        ],
    ),
    pytest.param(
        _run_under_anyio_asyncio,
        id="anyio-asyncio",
        marks=pytest.mark.skipif(
            anyio is None,
            reason="anyio not installed -- run `uv sync --group event-loops`",
        ),
    ),
]


@pytest.fixture(params=_BACKENDS)
def run_scenario(request: pytest.FixtureRequest) -> RunScenario:
    """Run a zero-arg async `scenario()` to completion under the parametrized
    event-loop backend (asyncio, uvloop, or anyio-on-asyncio) and return its
    result. Every test in this module takes this fixture instead of calling
    `asyncio.run` directly, so it automatically runs under all three."""
    runner: RunScenario = request.param
    return runner


# --- aoutput ------------------------------------------------------------------


def test_aoutput_awaits_to_a_result(run_scenario: RunScenario) -> None:
    async def scenario() -> None:
        result = await Command(PY, ["-c", "print('event-loop-hello')"]).aoutput()
        assert result.stdout.strip() == "event-loop-hello"
        assert result.is_success

    run_scenario(scenario)


# --- astart + streaming -------------------------------------------------------


def test_astart_streams_stdout_lines_in_order(run_scenario: RunScenario) -> None:
    async def scenario() -> list[str]:
        proc = await Command(PY, ["-c", _PRINT_LINES]).astart()
        lines = [line.rstrip() async for line in proc.stdout_lines()]
        await proc.aoutcome()
        return lines

    assert run_scenario(scenario) == [f"line{i}" for i in range(5)]


def test_astart_output_events_cover_both_streams(run_scenario: RunScenario) -> None:
    async def scenario() -> list[tuple[str, str]]:
        proc = await Command(PY, ["-c", _BOTH_STREAMS]).astart()
        events = [(str(e.stream), e.text.rstrip()) async for e in proc.output_events()]
        await proc.aoutcome()
        return events

    events = run_scenario(scenario)
    streams = {stream for stream, _ in events}
    texts = {text for _, text in events}
    assert streams == {"stdout", "stderr"}
    assert {"out1", "out2", "err1"} <= texts


# --- cancellation --------------------------------------------------------------


def test_cancelling_awaited_run_kills_tree(
    run_scenario: RunScenario, pid_file: pathlib.Path
) -> None:
    async def scenario() -> int:
        task = asyncio.ensure_future(spawn_grandchild_command(pid_file).aoutput())
        # Poll off-loop so the bridged task keeps making progress on whichever
        # loop backend is under test.
        grandchild_pid = await asyncio.to_thread(read_pid_when_ready, pid_file, 10.0)
        assert is_alive(grandchild_pid)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            _ = await task  # cancel always wins over any (never-produced) result
        return grandchild_pid

    grandchild_pid = run_scenario(scenario)
    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived task cancellation"
    )


# --- aoutput_all ---------------------------------------------------------------


def test_aoutput_all_returns_results_in_order(run_scenario: RunScenario) -> None:
    async def scenario() -> list[str]:
        results = await aoutput_all(
            [Command(PY, ["-c", "print(1)"]), Command(PY, ["-c", "print(2)"])],
            concurrency=2,
        )
        return [r.stdout.strip() for r in results if isinstance(r, ProcessResult)]

    assert run_scenario(scenario) == ["1", "2"]


# --- readiness helpers -----------------------------------------------------


def test_wait_for_port_ready(run_scenario: RunScenario) -> None:
    port = free_port()
    server = (
        f"import socket, time; "
        f"s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
        f"s.bind(('127.0.0.1', {port})); s.listen(); time.sleep(10)"
    )

    async def scenario() -> None:
        async with ProcessGroup() as group:
            await group.astart(Command(PY, ["-c", server]))
            await wait_for_port("127.0.0.1", port, timeout=10.0)

    run_scenario(scenario)


def test_wait_until_polls_until_true(run_scenario: RunScenario) -> None:
    async def scenario() -> None:
        calls = 0

        def ready() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        await wait_until(ready, timeout=2.0, interval=0.01)
        assert calls >= 3

    run_scenario(scenario)
