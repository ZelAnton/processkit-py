"""Async streaming, interactive stdin, and the `RunningProcess` handle.

Tests drive asyncio with ``asyncio.run`` so no pytest-asyncio plugin is needed.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

from processkit import BytesResult, Command, ProcessError, Runner, RunProfile

from ._liveness import is_alive, read_pid_when_ready, wait_dead
from ._programs import SPAWN_GRANDCHILD as _SPAWN_GRANDCHILD

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
    assert finished.exited_zero  # type: ignore[attr-defined]
    # Finished adds captured stderr over a bare Outcome; pin its accessors.
    assert isinstance(finished.stderr, str)  # type: ignore[attr-defined]
    assert finished.code == 0  # type: ignore[attr-defined]
    assert finished.outcome.exited_zero  # type: ignore[attr-defined]


def test_output_events_cover_both_streams() -> None:
    async def scenario() -> list[tuple[str, str, bool]]:
        proc = await Command(PY, ["-c", _BOTH_STREAMS]).astart()
        events = [(str(e.stream), e.text.rstrip(), e.is_stderr) async for e in proc.output_events()]
        await proc.wait()
        return events

    events = asyncio.run(scenario())
    streams = {s for s, _, _ in events}
    texts = {t for _, t, _ in events}
    assert {"out1", "out2", "err1"} <= texts
    assert streams == {"stdout", "stderr"}
    # is_stderr is the boolean twin of the stream label.
    assert all(is_err == (stream == "stderr") for stream, _, is_err in events)


def test_interactive_stdin_echo() -> None:
    async def scenario() -> list[str]:
        proc = await Command(PY, ["-c", _ECHO_UPPER]).keep_stdin_open().astart()
        stdin = proc.take_stdin()
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


def test_stdin_bytes_feeds_input() -> None:
    async def scenario() -> str:
        # Raw-bytes upfront input (the bytes twin of stdin_text).
        return await Command(PY, ["-c", _ECHO_UPPER]).stdin_bytes(b"xyz\n").arun()

    assert asyncio.run(scenario()) == "XYZ"


def test_take_stdin_is_once() -> None:
    # The first take hands over the handle; a second take raises (consumed).
    async def scenario() -> None:
        proc = await Command(PY, ["-c", _ECHO_UPPER]).keep_stdin_open().astart()
        first = proc.take_stdin()
        with pytest.raises(ProcessError):
            proc.take_stdin()
        await first.close()
        await proc.wait()

    asyncio.run(scenario())


def test_take_stdin_without_keep_open_raises() -> None:
    # Forgetting keep_stdin_open() fails clearly at take_stdin(), not later with
    # an AttributeError on a None.
    async def scenario() -> None:
        proc = await Command(PY, ["-c", "pass"]).astart()
        with pytest.raises(ProcessError):
            proc.take_stdin()
        await proc.wait()

    asyncio.run(scenario())


def test_running_process_output_captures() -> None:
    async def scenario() -> object:
        proc = await Command(PY, ["-c", "print('captured')"]).astart()
        return await proc.output()

    result = asyncio.run(scenario())
    assert result.stdout.strip() == "captured"  # type: ignore[attr-defined]
    assert result.is_success  # type: ignore[attr-defined]


def test_kill_then_wait_returns_promptly() -> None:
    # kill() must actually terminate the child — a no-op would leave wait() blocking
    # on the 60s sleeper until the bounded wait_for trips. Pins the effect, not just
    # the renamed name.
    async def scenario() -> object:
        proc = await Command(PY, ["-c", "import time; time.sleep(60)"]).astart()
        proc.kill()
        return await asyncio.wait_for(proc.wait(), timeout=15.0)

    outcome = asyncio.run(scenario())
    assert not outcome.exited_zero  # type: ignore[attr-defined]  # killed, not a clean exit


def test_shutdown_grace_terminates_and_returns_outcome() -> None:
    # shutdown() = graceful signal -> wait grace -> hard kill, consuming the handle.
    # A no-op would hang on the 60s sleeper past the bounded wait_for.
    async def scenario() -> object:
        proc = await Command(PY, ["-c", "import time; time.sleep(60)"]).astart()
        return await asyncio.wait_for(proc.shutdown(grace_seconds=0.5), timeout=15.0)

    outcome = asyncio.run(scenario())
    assert not outcome.exited_zero  # type: ignore[attr-defined]  # terminated, not clean


def test_running_process_wait_reports_exit_code() -> None:
    async def scenario() -> object:
        proc = await Command(PY, ["-c", "import sys; sys.exit(3)"]).astart()
        return await proc.wait()

    outcome = asyncio.run(scenario())
    assert outcome.code == 3  # type: ignore[attr-defined]
    assert not outcome.exited_zero  # type: ignore[attr-defined]
    assert outcome.signal is None  # type: ignore[attr-defined]  # clean exit, not a signal
    assert not outcome.timed_out  # type: ignore[attr-defined]


def test_consumed_handle_raises() -> None:
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
    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived cancellation of the streaming task"
    )


# --- live introspection + profile -------------------------------------------


def test_running_process_live_getters() -> None:
    async def scenario() -> None:
        async with await Command(PY, ["-c", "import time; time.sleep(5)"]).astart() as proc:
            assert proc.pid is not None
            assert proc.owns_group is True  # standalone astart owns a private tree
            assert (proc.elapsed_seconds or 0.0) >= 0.0
            # No output captured yet — 0, or None if the counter isn't initialized.
            assert proc.stdout_line_count in (0, None)
            assert proc.stderr_line_count in (0, None)
            assert proc.cpu_time_seconds is None or proc.cpu_time_seconds >= 0.0
            assert proc.peak_memory_bytes is None or proc.peak_memory_bytes >= 0

    asyncio.run(scenario())


def test_profile_returns_runprofile() -> None:
    async def scenario() -> RunProfile:
        proc = await Command(PY, ["-c", "import time; time.sleep(0.1)"]).astart()
        return await proc.profile(0.02)

    rp = asyncio.run(scenario())
    assert isinstance(rp, RunProfile)
    assert rp.code == 0
    assert rp.duration_seconds >= 0.0
    assert rp.samples >= 1
    assert rp.cpu_time_seconds is None or rp.cpu_time_seconds >= 0.0
    assert rp.peak_memory_bytes is None or rp.peak_memory_bytes >= 0
    assert rp.avg_cpu_cores is None or rp.avg_cpu_cores >= 0.0
    # profile() is a superset of wait(): it also carries how the run ended.
    assert rp.timed_out is False
    assert rp.signal is None
    assert rp.outcome.code == 0
    assert rp.outcome.exited_zero is True
    assert rp.outcome.timed_out is False


def test_running_process_output_bytes() -> None:
    async def scenario() -> BytesResult:
        code = "import sys; sys.stdout.buffer.write(bytes([1, 2, 255]))"
        proc = await Command(PY, ["-c", code]).astart()
        return await proc.output_bytes()

    result = asyncio.run(scenario())
    assert result.stdout == bytes([1, 2, 255])


# --- context-manager teardown (standalone start() owns a private tree) -------


def test_running_process_sync_with_reaps_tree(tmp_path: pathlib.Path) -> None:
    pid_file = tmp_path / "gc.pid"
    # A standalone start() owns a private tree; the `with` exit must kill it.
    with Runner().start(Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)])):
        grandchild = read_pid_when_ready(pid_file, timeout=10.0)
    assert wait_dead(grandchild, timeout=10.0), "grandchild survived the with-block exit"


def test_command_start_is_sync_twin_of_astart(tmp_path: pathlib.Path) -> None:
    # Command.start() is the synchronous counterpart of astart(): sync setup
    # returning a RunningProcess that owns a private tree and reaps it on exit —
    # no detour through Runner() needed.
    pid_file = tmp_path / "gc.pid"
    with Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]).start():
        grandchild = read_pid_when_ready(pid_file, timeout=10.0)
    assert wait_dead(grandchild, timeout=10.0), "Command().start() handle didn't reap on exit"


def test_running_process_async_with_reaps_tree(tmp_path: pathlib.Path) -> None:
    pid_file = tmp_path / "gc.pid"

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


def test_with_reaps_tree_even_when_block_raises(tmp_path: pathlib.Path) -> None:
    pid_file = tmp_path / "gc.pid"
    grandchild = -1
    with (
        pytest.raises(RuntimeError, match="boom"),
        Runner().start(Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)])),
    ):
        grandchild = read_pid_when_ready(pid_file, timeout=10.0)
        raise RuntimeError("boom")
    assert grandchild > 0
    assert wait_dead(grandchild, timeout=10.0), "grandchild survived a raising with-block"


def test_async_with_reaps_tree_even_when_block_raises(tmp_path: pathlib.Path) -> None:
    pid_file = tmp_path / "gc.pid"
    captured: dict[str, int] = {}

    async def scenario() -> None:
        async with await Command(PY, ["-c", _SPAWN_GRANDCHILD, str(pid_file)]).astart():
            captured["pid"] = read_pid_when_ready(pid_file, timeout=10.0)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(scenario())
    assert wait_dead(captured["pid"], timeout=10.0), "grandchild survived a raising async-with"
