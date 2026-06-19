"""Async surface (provisional) — the tokio ↔ asyncio bridge and its single most
important property: cancelling an awaited run tears down the process tree.

Tests drive asyncio with ``asyncio.run`` so no pytest-asyncio plugin is needed.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

from processkit import Command, NonZeroExit

from ._liveness import is_alive, read_pid_when_ready, wait_until

PY = sys.executable

_SPAWN_GRANDCHILD = (
    "import subprocess, sys, time;"
    "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
    "open(sys.argv[1], 'w').write(str(gc.pid));"
    "time.sleep(60)"
)


def test_aoutput_awaits_to_a_result() -> None:
    async def scenario() -> None:
        result = await Command(PY, ["-c", "print('async-hello')"]).aoutput()
        assert result.stdout.strip() == "async-hello"
        assert result.is_success

    asyncio.run(scenario())


def test_arun_awaits_to_stdout() -> None:
    async def scenario() -> str:
        return await Command(PY, ["-c", "print('via-arun')"]).arun()

    assert asyncio.run(scenario()) == "via-arun"


def test_arun_raises_with_structured_fields() -> None:
    # Exercises the async error path: the rich exception is built on a tokio
    # worker (via Python::attach) and propagated through the asyncio bridge.
    async def scenario() -> str:
        return await Command(PY, ["-c", "import sys; sys.exit(4)"]).arun()

    with pytest.raises(NonZeroExit) as excinfo:
        asyncio.run(scenario())
    assert excinfo.value.code == 4


def test_cancelling_awaited_run_kills_tree(tmp_path: pathlib.Path) -> None:
    pid_file = tmp_path / "grandchild.pid"

    async def scenario() -> int:
        task = asyncio.ensure_future(
            Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]).aoutput()
        )
        # Let the child start and record the grandchild PID without blocking the
        # event loop (so the bridged task keeps making progress).
        grandchild_pid = await asyncio.to_thread(read_pid_when_ready, pid_file, 10.0)
        assert is_alive(grandchild_pid)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            _ = await task  # bind the (never-produced) result; cancel always wins
        return grandchild_pid

    grandchild_pid = asyncio.run(scenario())
    assert wait_until(lambda: not is_alive(grandchild_pid), timeout=10.0), (
        f"grandchild {grandchild_pid} survived task cancellation"
    )
