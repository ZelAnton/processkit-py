"""Async streaming, interactive stdin, and the `RunningProcess` handle.

Tests drive asyncio with ``asyncio.run`` so no pytest-asyncio plugin is needed.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

from processkit import Command

from ._liveness import is_alive, read_pid_when_ready, wait_until

PY = sys.executable

# Prints N lines (flushed so they stream) then exits.
_PRINT_LINES = "[print(f'line{i}', flush=True) for i in range(5)]"

# Echoes each stdin line uppercased until EOF.
_ECHO_UPPER = (
    "import sys; [(sys.stdout.write(line.upper()), sys.stdout.flush()) for line in sys.stdin]"
)

# stdout + stderr on both streams.
_BOTH_STREAMS = (
    "import sys; "
    "print('out1', flush=True); "
    "sys.stderr.write('err1\\n'); sys.stderr.flush(); "
    "print('out2', flush=True)"
)

# Spawns a grandchild (sleeps), records its PID to argv[1], then streams forever.
_STREAM_AND_SPAWN = """
import subprocess, sys, time
gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
with open(sys.argv[1], "w") as f:
    f.write(str(gc.pid))
i = 0
while True:
    print(f"tick {i}", flush=True)
    i += 1
    time.sleep(0.05)
"""


def test_stdout_lines_streams_in_order() -> None:
    async def scenario() -> tuple[list[str], object]:
        proc = await Command(PY, ["-c", _PRINT_LINES]).astart()
        lines = [line.rstrip() async for line in proc.stdout_lines()]
        finished = await proc.finish()
        return lines, finished

    lines, finished = asyncio.run(scenario())
    assert lines == [f"line{i}" for i in range(5)]
    assert finished.is_success  # type: ignore[attr-defined]


def test_output_events_cover_both_streams() -> None:
    async def scenario() -> list[tuple[str, str]]:
        proc = await Command(PY, ["-c", _BOTH_STREAMS]).astart()
        events = [(str(e.stream), e.text.rstrip()) async for e in proc.output_events()]
        await proc.wait()
        return events

    events = asyncio.run(scenario())
    streams = {s for s, _ in events}
    texts = {t for _, t in events}
    assert {"out1", "out2", "err1"} <= texts
    assert streams == {"stdout", "stderr"}


def test_interactive_stdin_echo() -> None:
    async def scenario() -> list[str]:
        proc = await Command(PY, ["-c", _ECHO_UPPER]).keep_stdin_open().astart()
        stdin = proc.take_stdin()
        assert stdin is not None
        await stdin.write_line("hello")
        await stdin.write_line("world")
        await stdin.close()  # EOF — the child finishes and exits
        lines = [line.rstrip() async for line in proc.stdout_lines()]
        await proc.wait()
        return lines

    assert asyncio.run(scenario()) == ["HELLO", "WORLD"]


def test_stdin_text_feeds_input() -> None:
    async def scenario() -> str:
        # Upfront input (no interactive handle needed).
        return await Command(PY, ["-c", _ECHO_UPPER]).stdin_text("abc\n").arun()

    assert asyncio.run(scenario()) == "ABC"


def test_take_stdin_is_once() -> None:
    async def scenario() -> bool:
        proc = await Command(PY, ["-c", _ECHO_UPPER]).keep_stdin_open().astart()
        first = proc.take_stdin()
        second = proc.take_stdin()
        if first is not None:
            await first.close()
        await proc.wait()
        return first is not None and second is None

    assert asyncio.run(scenario())


def test_running_process_output_captures() -> None:
    async def scenario() -> object:
        proc = await Command(PY, ["-c", "print('captured')"]).astart()
        return await proc.output()

    result = asyncio.run(scenario())
    assert result.stdout.strip() == "captured"  # type: ignore[attr-defined]
    assert result.is_success  # type: ignore[attr-defined]


def test_running_process_wait_reports_exit_code() -> None:
    async def scenario() -> object:
        proc = await Command(PY, ["-c", "import sys; sys.exit(3)"]).astart()
        return await proc.wait()

    outcome = asyncio.run(scenario())
    assert outcome.code == 3  # type: ignore[attr-defined]
    assert not outcome.is_success  # type: ignore[attr-defined]


def test_consumed_handle_raises() -> None:
    from processkit import ProcessError

    async def scenario() -> None:
        proc = await Command(PY, ["-c", "pass"]).astart()
        await proc.wait()
        # The handle is spent; a second consuming call must raise.
        await proc.wait()

    with pytest.raises(ProcessError):
        asyncio.run(scenario())


def test_cancel_mid_stream_kills_tree(tmp_path: pathlib.Path) -> None:
    pid_file = tmp_path / "grandchild.pid"

    async def stream_forever() -> None:
        proc = await Command(PY, ["-c", _STREAM_AND_SPAWN, str(pid_file)]).astart()
        async for _line in proc.stdout_lines():
            pass  # consume until cancelled

    async def driver() -> int:
        task = asyncio.ensure_future(stream_forever())
        grandchild_pid = await asyncio.to_thread(read_pid_when_ready, pid_file, 10.0)
        assert is_alive(grandchild_pid)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return grandchild_pid

    grandchild_pid = asyncio.run(driver())
    assert wait_until(lambda: not is_alive(grandchild_pid), timeout=10.0), (
        f"grandchild {grandchild_pid} survived cancellation of the streaming task"
    )
