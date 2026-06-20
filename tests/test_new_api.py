"""Tests for the extended surface: full environment control, output caps,
bytes output, and the stdlib-aliased exceptions."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from processkit import (
    BytesResult,
    Command,
    OutputTooLarge,
    ProcessError,
    ProcessGroup,
    ProcessNotFound,
    Runner,
    Timeout,
    wait_for,
)

from ._liveness import read_pid_when_ready, wait_dead

PY = sys.executable

_SPAWN_GRANDCHILD = (
    "import subprocess, sys, time;"
    "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
    "open(sys.argv[1], 'w').write(str(gc.pid));"
    "time.sleep(60)"
)


# --- Environment control ----------------------------------------------------


def test_envs_sets_multiple() -> None:
    out = (
        Command(PY, ["-c", "import os; print(os.environ['A'], os.environ['B'])"])
        .envs({"A": "1", "B": "2"})
        .run()
    )
    assert out == "1 2"


def test_env_remove_drops_inherited() -> None:
    os.environ["PK_REMOVE_ME"] = "parent"
    try:
        out = (
            Command(PY, ["-c", "import os; print(os.environ.get('PK_REMOVE_ME', 'GONE'))"])
            .env_remove("PK_REMOVE_ME")
            .run()
        )
        assert out == "GONE"
    finally:
        del os.environ["PK_REMOVE_ME"]


def test_env_clear_starts_from_empty() -> None:
    os.environ["PK_CLEAR_MARKER"] = "parent"
    try:
        cmd = Command(
            PY, ["-c", "import os; print(os.environ.get('PK_CLEAR_MARKER', 'GONE'))"]
        ).env_clear()
        # The interpreter needs SystemRoot to spawn on Windows; re-add just that
        # (env var names are case-insensitive on Windows).
        if sys.platform == "win32":
            cmd = cmd.env("SYSTEMROOT", os.environ.get("SYSTEMROOT", r"C:\Windows"))
        assert cmd.run() == "GONE"
    finally:
        del os.environ["PK_CLEAR_MARKER"]


# --- Bytes output -----------------------------------------------------------


def test_output_bytes_returns_raw_bytes() -> None:
    code = "import sys; sys.stdout.buffer.write(bytes([0, 1, 2, 255]))"
    result = Command(PY, ["-c", code]).output_bytes()
    assert isinstance(result, BytesResult)
    assert result.stdout == bytes([0, 1, 2, 255])
    assert isinstance(result.stderr, str)
    assert result.code == 0
    assert result.is_success
    assert not result.truncated


def test_aoutput_bytes_returns_raw_bytes() -> None:
    async def scenario() -> BytesResult:
        code = "import sys; sys.stdout.buffer.write(b'\\x00\\xff')"
        return await Command(PY, ["-c", code]).aoutput_bytes()

    result = asyncio.run(scenario())
    assert result.stdout == b"\x00\xff"


def test_pipeline_output_bytes_captures_binary_tail() -> None:
    # A pipeline ending in a binary producer can capture raw (non-UTF-8) bytes.
    produce = Command(PY, ["-c", "import sys; sys.stdout.buffer.write(bytes([0, 1, 2, 255]))"])
    echo = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"
    passthrough = Command(PY, ["-c", echo])
    result = (produce | passthrough).output_bytes()
    assert isinstance(result, BytesResult)
    assert result.stdout == bytes([0, 1, 2, 255])
    assert result.is_success


def test_pipeline_aoutput_bytes_captures_binary_tail() -> None:
    echo = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"

    async def scenario() -> BytesResult:
        produce = Command(PY, ["-c", "import sys; sys.stdout.buffer.write(bytes([3, 4, 255]))"])
        return await (produce | Command(PY, ["-c", echo])).aoutput_bytes()

    result = asyncio.run(scenario())
    assert result.stdout == bytes([3, 4, 255])


# --- Output caps ------------------------------------------------------------


def test_output_limit_error_raises_output_too_large() -> None:
    code = "import sys\nfor i in range(1000):\n    print(i)"
    with pytest.raises(OutputTooLarge) as excinfo:
        Command(PY, ["-c", code]).output_limit(max_lines=10, on_overflow="error").run()
    assert excinfo.value.line_limit == 10
    assert excinfo.value.total_lines >= 1000


def test_output_limit_truncate_marks_truncated() -> None:
    code = "import sys\nfor i in range(1000):\n    print('x' * 80)"
    result = Command(PY, ["-c", code]).output_limit(max_lines=10).output()
    assert result.is_success
    assert result.truncated


def test_output_limit_requires_a_cap() -> None:
    with pytest.raises(ValueError):
        Command(PY, ["-c", "pass"]).output_limit()


def test_output_limit_rejects_unknown_overflow() -> None:
    with pytest.raises(ValueError):
        # An invalid literal is the point of the test; mypy would flag it.
        Command(PY, ["-c", "pass"]).output_limit(max_bytes=10, on_overflow="nope")  # type: ignore[arg-type]


# --- Stdlib-aliased exceptions ----------------------------------------------


def test_timeout_is_a_timeout_error() -> None:
    assert issubclass(Timeout, TimeoutError)
    assert issubclass(Timeout, ProcessError)
    with pytest.raises(TimeoutError):
        Command(PY, ["-c", "import time; time.sleep(30)"]).timeout(0.2).run()


def test_process_not_found_is_a_file_not_found_error() -> None:
    assert issubclass(ProcessNotFound, FileNotFoundError)
    assert issubclass(ProcessNotFound, ProcessError)
    with pytest.raises(FileNotFoundError):
        Command("processkit-definitely-no-such-program-xyz").run()


# --- RunningProcess as a context manager ------------------------------------


def test_running_process_sync_with_reaps_tree(tmp_path: object) -> None:
    import pathlib

    pid_file = pathlib.Path(str(tmp_path)) / "gc.pid"
    # A standalone start() owns a private tree; the `with` exit must kill it.
    with Runner().start(Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)])):
        grandchild = read_pid_when_ready(pid_file, timeout=10.0)
    assert wait_dead(grandchild, timeout=10.0), "grandchild survived the with-block exit"


def test_running_process_async_with_reaps_tree(tmp_path: object) -> None:
    import pathlib

    pid_file = pathlib.Path(str(tmp_path)) / "gc.pid"

    async def scenario() -> int:
        async with await Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]).astart():
            return read_pid_when_ready(pid_file, timeout=10.0)

    grandchild = asyncio.run(scenario())
    assert wait_dead(grandchild, timeout=10.0), "grandchild survived the async-with exit"


def test_context_manager_is_noop_after_consuming() -> None:
    async def scenario() -> None:
        async with await Command(PY, ["-c", "print('hi')"]).astart() as proc:
            result = await proc.output()  # consumes the handle
            assert result.is_success
        # __aexit__ sees a consumed handle and must not raise.

    asyncio.run(scenario())


# --- wait_for ---------------------------------------------------------------


def test_wait_for_sync_predicate() -> None:
    async def scenario() -> None:
        calls = 0

        def ready() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        await wait_for(ready, timeout=2.0, interval=0.01)
        assert calls >= 3

    asyncio.run(scenario())


def test_wait_for_async_predicate() -> None:
    async def scenario() -> None:
        async def ready() -> bool:
            return True

        await wait_for(ready, timeout=1.0)

    asyncio.run(scenario())


def test_wait_for_times_out() -> None:
    async def scenario() -> None:
        with pytest.raises(TimeoutError):
            await wait_for(lambda: False, timeout=0.2, interval=0.01)

    asyncio.run(scenario())


def test_wait_for_returns_immediately_when_already_true() -> None:
    # An already-true predicate must return before the deadline check, even at
    # timeout=0 (predicate is evaluated first).
    async def scenario() -> None:
        await wait_for(lambda: True, timeout=0.0)

    asyncio.run(scenario())


def test_wait_for_async_predicate_polls_until_true() -> None:
    # A missing `await` would treat the coroutine as truthy and return after one
    # call; requiring three proves the value is actually awaited.
    async def scenario() -> None:
        calls = 0

        async def ready() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        await wait_for(ready, timeout=2.0, interval=0.01)
        assert calls >= 3

    asyncio.run(scenario())


def test_wait_for_async_predicate_times_out() -> None:
    async def scenario() -> None:
        async def never() -> bool:
            return False

        with pytest.raises(TimeoutError):
            await wait_for(never, timeout=0.2, interval=0.01)

    asyncio.run(scenario())


def test_wait_for_rejects_nonpositive_interval() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError):
            await wait_for(lambda: True, timeout=1.0, interval=0)

    asyncio.run(scenario())


# --- Context-manager teardown under exceptions / inside a group -------------


def test_with_reaps_tree_even_when_block_raises(tmp_path: object) -> None:
    import pathlib

    pid_file = pathlib.Path(str(tmp_path)) / "gc.pid"
    grandchild = -1
    with (
        pytest.raises(RuntimeError, match="boom"),
        Runner().start(Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)])),
    ):
        grandchild = read_pid_when_ready(pid_file, timeout=10.0)
        raise RuntimeError("boom")
    assert grandchild > 0
    assert wait_dead(grandchild, timeout=10.0), "grandchild survived a raising with-block"


def test_async_with_reaps_tree_even_when_block_raises(tmp_path: object) -> None:
    import pathlib

    pid_file = pathlib.Path(str(tmp_path)) / "gc.pid"
    captured: dict[str, int] = {}

    async def scenario() -> None:
        async with await Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]).astart():
            captured["pid"] = read_pid_when_ready(pid_file, timeout=10.0)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(scenario())
    assert wait_dead(captured["pid"], timeout=10.0), "grandchild survived a raising async-with"


def test_group_started_handle_works_as_context_manager() -> None:
    # A handle from group.start() is a shared-group handle: the context-manager
    # exit kills just that child, and the surrounding group stays usable.
    with ProcessGroup() as group:
        with group.start(Command(PY, ["-c", "import time; time.sleep(60)"])) as proc:
            child = proc.pid
            assert child is not None
        assert wait_dead(child, timeout=10.0), "group-started child survived its inner with-block"
        assert isinstance(group.members(), list)
