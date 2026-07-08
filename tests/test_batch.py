"""Concurrent batch execution: `output_all` / `aoutput_all` and their `_bytes`
twins run many commands with bounded concurrency, returning each result — or a
`ProcessError` for a failed slot — in input order.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import threading
import time
from collections.abc import Callable

import pytest

from processkit import (
    BytesResult,
    Command,
    ProcessError,
    ProcessNotFound,
    ProcessResult,
    aoutput_all,
    aoutput_all_bytes,
    output_all,
    output_all_bytes,
)
from processkit.testing import Reply, ScriptedRunner

from ._liveness import is_alive, read_pid_when_ready, wait_dead
from .conftest import NO_SUCH_PROGRAM, spawn_grandchild_command

PY = sys.executable


def test_output_all_returns_results_in_order() -> None:
    # The first command sleeps far longer than the second, so it *finishes*
    # last -- an implementation that (bug) returned results in completion
    # order rather than input order would put "2" first here. The previous
    # version of this test raced two instantaneous commands, which a
    # completion-order implementation would also have passed by coincidence
    # (nothing forced their completion order to differ from input order).
    slow = Command(PY, ["-c", "import time; time.sleep(0.5); print(1)"])
    fast = Command(PY, ["-c", "print(2)"])
    results = output_all([slow, fast], concurrency=2)
    assert all(isinstance(r, ProcessResult) for r in results)
    assert [r.stdout.strip() for r in results if isinstance(r, ProcessResult)] == ["1", "2"]


def test_aoutput_all_returns_results_in_order() -> None:
    # Async twin of test_output_all_returns_results_in_order: same inverted
    # completion order (first command sleeps longest, finishes last), same
    # input-order guarantee on the returned list.
    async def scenario() -> list[ProcessResult | ProcessError]:
        slow = Command(PY, ["-c", "import time; time.sleep(0.5); print(1)"])
        fast = Command(PY, ["-c", "print(2)"])
        return await aoutput_all([slow, fast], concurrency=2)

    results = asyncio.run(scenario())
    assert all(isinstance(r, ProcessResult) for r in results)
    assert [r.stdout.strip() for r in results if isinstance(r, ProcessResult)] == ["1", "2"]


def test_output_all_bytes_returns_results_in_order() -> None:
    # Bytes twin, on the separate bytes result-conversion path
    # (`bytes_results_to_pylist`) -- same inverted-completion-order guarantee.
    # `aoutput_all_bytes` is not given its own copy: the async bridge is
    # already exercised by `test_aoutput_all_returns_results_in_order` and the
    # bytes conversion path by this test, and the ordering logic itself is
    # shared by all four entry points, not reimplemented per variant.
    slow_code = "import sys, time; time.sleep(0.5); sys.stdout.buffer.write(b'\\x01')"
    slow = Command(PY, ["-c", slow_code])
    fast = Command(PY, ["-c", "import sys; sys.stdout.buffer.write(b'\\x02')"])
    results = output_all_bytes([slow, fast], concurrency=2)
    assert all(isinstance(r, BytesResult) for r in results)
    assert [r.stdout for r in results if isinstance(r, BytesResult)] == [b"\x01", b"\x02"]


def test_output_all_rejects_zero_concurrency() -> None:
    # concurrency=0 used to be silently clamped to 1 ("I asked for none and
    # got some anyway") — now a clear ValueError, across all four entry points.
    cmds = [Command(PY, ["-c", "print(1)"])]
    with pytest.raises(ValueError, match="concurrency"):
        output_all(cmds, concurrency=0)
    with pytest.raises(ValueError, match="concurrency"):
        output_all_bytes(cmds, concurrency=0)

    async def scenario() -> None:
        with pytest.raises(ValueError, match="concurrency"):
            await aoutput_all(cmds, concurrency=0)
        with pytest.raises(ValueError, match="concurrency"):
            await aoutput_all_bytes(cmds, concurrency=0)

    asyncio.run(scenario())


def test_output_all_puts_spawn_failure_in_its_slot() -> None:
    results = output_all([Command(PY, ["-c", "print(1)"]), Command(NO_SUCH_PROGRAM)])
    ok, failed = results[0], results[1]
    assert isinstance(ok, ProcessResult)
    assert ok.stdout.strip() == "1"
    assert isinstance(failed, ProcessNotFound)
    assert isinstance(failed, ProcessError)


def test_output_all_bytes() -> None:
    code = "import sys; sys.stdout.buffer.write(b'\\x00\\x01')"
    results = output_all_bytes([Command(PY, ["-c", code])])
    first = results[0]
    assert isinstance(first, BytesResult)
    assert first.stdout == b"\x00\x01"


def test_aoutput_all() -> None:
    async def scenario() -> list[ProcessResult | ProcessError]:
        return await aoutput_all([Command(PY, ["-c", "print(9)"])])

    results = asyncio.run(scenario())
    first = results[0]
    assert isinstance(first, ProcessResult)
    assert first.stdout.strip() == "9"


def test_aoutput_all_bytes() -> None:
    async def scenario() -> list[BytesResult | ProcessError]:
        code = "import sys; sys.stdout.buffer.write(b'\\x02\\x03')"
        return await aoutput_all_bytes([Command(PY, ["-c", code])])

    results = asyncio.run(scenario())
    first = results[0]
    assert isinstance(first, BytesResult)
    assert first.stdout == b"\x02\x03"


def test_aoutput_all_puts_spawn_failure_in_its_slot() -> None:
    # The async twin of test_output_all_puts_spawn_failure_in_its_slot — a real
    # (not ScriptedRunner-injected) spawn failure alongside a real success,
    # each landing correctly in its own result slot. Previously only the sync
    # `output_all` had this exact real-spawn-failure coverage.
    async def scenario() -> list[ProcessResult | ProcessError]:
        return await aoutput_all([Command(PY, ["-c", "print(1)"]), Command(NO_SUCH_PROGRAM)])

    results = asyncio.run(scenario())
    ok, failed = results[0], results[1]
    assert isinstance(ok, ProcessResult)
    assert ok.stdout.strip() == "1"
    assert isinstance(failed, ProcessNotFound)
    assert isinstance(failed, ProcessError)


# --- runner injection (C1) ---------------------------------------------------


def test_output_all_accepts_injected_runner() -> None:
    # A NO_SUCH_PROGRAM program would fail to spawn for real; with a ScriptedRunner
    # fallback wired in, no real process runs at all and the scripted reply
    # surfaces — proving the batch actually drove every command through the
    # injected runner, not the real one.
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("scripted"))
    results = output_all([Command(NO_SUCH_PROGRAM), Command(NO_SUCH_PROGRAM)], runner=runner)
    assert all(isinstance(r, ProcessResult) for r in results)
    assert [r.stdout for r in results if isinstance(r, ProcessResult)] == ["scripted", "scripted"]


def test_output_all_bytes_accepts_injected_runner() -> None:
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("bytes-scripted"))
    results = output_all_bytes([Command(NO_SUCH_PROGRAM)], runner=runner)
    first = results[0]
    assert isinstance(first, BytesResult)
    assert first.stdout == b"bytes-scripted"


def test_aoutput_all_accepts_injected_runner() -> None:
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("async-scripted"))

    async def scenario() -> list[ProcessResult | ProcessError]:
        return await aoutput_all([Command(NO_SUCH_PROGRAM)], runner=runner)

    results = asyncio.run(scenario())
    first = results[0]
    assert isinstance(first, ProcessResult)
    assert first.stdout == "async-scripted"


def test_aoutput_all_bytes_accepts_injected_runner() -> None:
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("async-bytes-scripted"))

    async def scenario() -> list[BytesResult | ProcessError]:
        return await aoutput_all_bytes([Command(NO_SUCH_PROGRAM)], runner=runner)

    results = asyncio.run(scenario())
    first = results[0]
    assert isinstance(first, BytesResult)
    assert first.stdout == b"async-bytes-scripted"


def test_output_all_rejects_unsupported_runner_object() -> None:
    with pytest.raises(TypeError):
        output_all([Command(PY, ["-c", "pass"])], runner=object())  # type: ignore[arg-type]


# --- no-orphan teardown + in-flight cancellation -----------------------------


def test_aoutput_all_cancel_mid_flight_kills_the_tree(pid_file: pathlib.Path) -> None:
    # No-orphan teardown, for the batch surface: cancelling the *awaiting task*
    # while `aoutput_all` is mid-flight must tear down the whole tree spawned by
    # its (single, still-running) slot -- not just leave a grandchild orphaned.
    # Mirrors `test_cancel_mid_stream_kills_tree` (test_streaming.py), which
    # pins the same guarantee for a standalone `astart()`. Every other
    # spawn-surface (astart, ProcessGroup, pipelines, cancel_on) already has
    # this exact "cancel -> grandchild `wait_dead`" coverage; the batch entry
    # points spawn N trees with none.
    async def driver() -> int:
        task = asyncio.ensure_future(
            aoutput_all([spawn_grandchild_command(pid_file)], concurrency=1)
        )
        grandchild_pid = await asyncio.to_thread(read_pid_when_ready, pid_file, 10.0)
        assert is_alive(grandchild_pid)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return grandchild_pid

    grandchild_pid = asyncio.run(driver())
    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived cancellation of an in-flight aoutput_all"
    )


def test_output_all_slot_timeout_lands_in_its_own_slot_without_stalling_the_batch() -> None:
    # A `Command.timeout()` firing inside ONE slot of a batch must land as a
    # timed-out `ProcessResult` -- not a `ProcessError`, not a raised exception
    # -- in that slot alone, and (the actual point of this test) must not
    # subject the rest of the batch to it: the fast sibling slot finishes on
    # its own schedule instead of waiting behind the slow one.
    slow = Command(PY, ["-c", "import time; time.sleep(30)"]).timeout(0.3)
    fast = Command(PY, ["-c", "print('fast')"])

    start = time.monotonic()
    results = output_all([slow, fast], concurrency=2)
    elapsed = time.monotonic() - start

    timed_out, ok = results[0], results[1]
    assert isinstance(timed_out, ProcessResult)
    assert timed_out.timed_out
    assert not timed_out.is_success
    assert isinstance(ok, ProcessResult)
    assert ok.stdout.strip() == "fast"
    assert elapsed < 10.0, (
        f"batch took {elapsed:.1f}s -- the timed-out slot must not stall its siblings "
        "or the whole batch behind the slow command's own 30s sleep"
    )


# --- concurrency actually bounds live children (T-058) -----------------------


def _mark_lifecycle_command(marks_dir: pathlib.Path, duration: float) -> Command:
    """A `Command` that drops a marker file named after its own PID into
    `marks_dir` on start, sleeps `duration` seconds, then removes the marker
    before exiting -- the probe `_measure_peak_concurrency` polls to compute
    how many of these children were alive (between marker-create and
    marker-remove) at the same time. Naming the marker after the PID needs no
    extra coordination between children: a PID is unique among the processes
    currently alive on the system, and both the create and the remove happen
    while this process (and thus its PID) is still alive.
    """
    code = (
        "import pathlib, sys, time, os\n"
        "marker = pathlib.Path(sys.argv[1]) / str(os.getpid())\n"
        "marker.write_text('1')\n"
        "time.sleep(float(sys.argv[2]))\n"
        "marker.unlink()\n"
    )
    return Command(PY, ["-c", code, str(marks_dir), str(duration)])


def _measure_peak_concurrency(marks_dir: pathlib.Path, run: Callable[[], object]) -> int:
    """Run `run()` -- expected to drive one or more `_mark_lifecycle_command`
    children through `marks_dir` to completion -- while a background thread
    polls `marks_dir`'s contents every 10ms, returning the largest marker
    count ever observed: the empirically measured peak parallelism, computed
    from file-presence facts rather than guessed from timing.
    """
    peak = 0
    stop = threading.Event()

    def poll() -> None:
        nonlocal peak
        while not stop.is_set():
            peak = max(peak, sum(1 for _ in marks_dir.iterdir()))
            time.sleep(0.01)

    poller = threading.Thread(target=poll)
    poller.start()
    try:
        run()
    finally:
        stop.set()
        poller.join()
    return peak


_CONCURRENCY_CASES = [
    # N > 1 with more than N commands queued behind it: peak must never
    # exceed N.
    pytest.param(2, 5, id="concurrency=2-of-5"),
    # N == 1: full serialization -- peak must never exceed 1.
    pytest.param(1, 3, id="concurrency=1-fully-serialized"),
]


@pytest.mark.parametrize(("concurrency", "child_count"), _CONCURRENCY_CASES)
def test_output_all_bounds_live_children_to_concurrency(
    tmp_path: pathlib.Path, concurrency: int, child_count: int
) -> None:
    marks_dir = tmp_path / "marks"
    marks_dir.mkdir()
    commands = [_mark_lifecycle_command(marks_dir, 0.35) for _ in range(child_count)]

    peak = _measure_peak_concurrency(
        marks_dir, lambda: output_all(commands, concurrency=concurrency)
    )

    # Not a strict `==`: on a CPU-starved runner, child-process startup can be
    # staggered enough that the poller never catches all N slots occupied at
    # once, which would be a false failure unrelated to whether `output_all`
    # itself enforces the limit. `peak >= 1` alone rules out a silently broken
    # probe (e.g. an empty/never-created marks_dir); `peak <= concurrency` is
    # the actual property under test -- and needs no timing margin to be
    # trustworthy, since the poller can only ever *undercount* a fleeting
    # overlap, never observe more live children than were truly alive at once.
    assert 1 <= peak <= concurrency, (
        f"observed peak of {peak} live children, expected 1..{concurrency} "
        f"({child_count} commands queued behind a concurrency={concurrency} limit)"
    )


@pytest.mark.parametrize(("concurrency", "child_count"), _CONCURRENCY_CASES)
def test_aoutput_all_bounds_live_children_to_concurrency(
    tmp_path: pathlib.Path, concurrency: int, child_count: int
) -> None:
    marks_dir = tmp_path / "marks"
    marks_dir.mkdir()
    commands = [_mark_lifecycle_command(marks_dir, 0.35) for _ in range(child_count)]

    async def scenario() -> None:
        await aoutput_all(commands, concurrency=concurrency)

    peak = _measure_peak_concurrency(marks_dir, lambda: asyncio.run(scenario()))

    # See the sibling sync test for why this is `1 <= peak <= concurrency`
    # rather than a strict `==`.
    assert 1 <= peak <= concurrency, (
        f"observed peak of {peak} live children, expected 1..{concurrency} "
        f"({child_count} commands queued behind a concurrency={concurrency} limit)"
    )
