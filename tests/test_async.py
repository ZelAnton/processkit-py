"""Async surface (provisional) — the tokio ↔ asyncio bridge and its single most
important property: cancelling an awaited run tears down the process tree.

Tests drive asyncio with ``asyncio.run`` so no pytest-asyncio plugin is needed.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

from processkit import Command, NonZeroExit, ProcessGroup

from ._liveness import is_alive, read_pid_when_ready, wait_dead
from ._programs import SPAWN_GRANDCHILD as _SPAWN_GRANDCHILD

PY = sys.executable


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
    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived task cancellation"
    )


def test_async_parity() -> None:
    async def scenario() -> tuple[int, bool, bool]:
        code = await Command(PY, ["-c", "import sys; sys.exit(7)"]).aexit_code()
        ok = await Command(PY, ["-c", "import sys; sys.exit(0)"]).aprobe()
        not_ok = await Command(PY, ["-c", "import sys; sys.exit(1)"]).aprobe()
        return code, ok, not_ok

    code, ok, not_ok = asyncio.run(scenario())
    assert code == 7
    assert ok is True
    assert not_ok is False


def test_async_group_teardown_kills_grandchild(tmp_path: pathlib.Path) -> None:
    pid_file = tmp_path / "grandchild.pid"

    async def scenario() -> int:
        async with ProcessGroup() as group:
            assert group.mechanism in {"job_object", "cgroup_v2", "process_group"}
            await group.astart(Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]))
            grandchild_pid = await asyncio.to_thread(read_pid_when_ready, pid_file, 10.0)
            assert is_alive(grandchild_pid)
            return grandchild_pid

    grandchild_pid = asyncio.run(scenario())
    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived async ProcessGroup teardown"
    )


def test_explicit_ashutdown_reaps_tree(tmp_path: pathlib.Path) -> None:
    # The explicit `await group.ashutdown()` path (not the async-with sugar) must
    # reap the whole tree, grandchild included.
    pid_file = tmp_path / "grandchild.pid"

    async def scenario() -> int:
        group = ProcessGroup()
        await group.astart(Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]))
        grandchild_pid = await asyncio.to_thread(read_pid_when_ready, pid_file, 10.0)
        assert is_alive(grandchild_pid)
        await group.ashutdown()
        return grandchild_pid

    grandchild_pid = asyncio.run(scenario())
    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived explicit ashutdown()"
    )


def test_wait_for_timeout_kills_tree(tmp_path: pathlib.Path) -> None:
    # asyncio.wait_for cancellation must tear the tree down, like a direct cancel.
    pid_file = tmp_path / "grandchild.pid"

    async def scenario() -> int:
        task = asyncio.ensure_future(
            Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]).aoutput()
        )
        grandchild_pid = await asyncio.to_thread(read_pid_when_ready, pid_file, 10.0)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=0.5)
        return grandchild_pid

    grandchild_pid = asyncio.run(scenario())
    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived asyncio.wait_for timeout"
    )
