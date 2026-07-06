"""Async streaming, interactive stdin, and the `RunningProcess` handle.

Tests drive asyncio with ``asyncio.run`` so no pytest-asyncio plugin is needed.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from processkit import (
    BytesResult,
    Command,
    Finished,
    Outcome,
    ProcessError,
    ProcessGroup,
    ProcessResult,
    Runner,
    RunProfile,
    Supervisor,
)

from ._liveness import is_alive, read_pid_when_ready, wait_dead
from .conftest import PY, spawn_grandchild_command

# Prints N lines (flushed so they stream) then exits.
_PRINT_LINES = "[print(f'line{i}', flush=True) for i in range(5)]"

# A `\r`-redrawn progress bar: three frames with no `\n` until the very end —
# `curl`/`pip`/`apt`-style. Under the default "newline" framing this is ONE
# line; under "carriage_return" framing it is three.
_PRINT_CR_PROGRESS = "import sys; sys.stdout.write('a\\rb\\rc\\n'); sys.stdout.flush()"

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
    async def scenario() -> tuple[list[str], Finished]:
        proc = await Command(PY, ["-c", _PRINT_LINES]).astart()
        lines = [line.rstrip() async for line in proc.stdout_lines()]
        finished = await proc.afinish()
        return lines, finished

    lines, finished = asyncio.run(scenario())
    assert lines == [f"line{i}" for i in range(5)]
    assert finished.exited_zero
    # Finished adds captured stderr over a bare Outcome; pin its accessors.
    assert isinstance(finished.stderr, str)
    assert finished.code == 0
    assert finished.outcome.exited_zero


def test_stdout_line_terminator_carriage_return_splits_progress_frames() -> None:
    # `stdout_line_terminator("carriage_return")` treats a bare `\r` as a frame
    # terminator too, so a redrawn-in-place progress bar streams live, one frame
    # at a time, instead of piling up into a single line at EOF.
    async def scenario() -> list[str]:
        cmd = Command(PY, ["-c", _PRINT_CR_PROGRESS]).stdout_line_terminator("carriage_return")
        proc = await cmd.astart()
        lines = [line async for line in proc.stdout_lines()]
        await proc.aoutcome()
        return lines

    assert asyncio.run(scenario()) == ["a", "b", "c"]


def test_stdout_line_terminator_default_leaves_carriage_returns_as_content() -> None:
    # Backward compatibility: without `line_terminator`/`stdout_line_terminator`,
    # a bare `\r` is ordinary line content (not a terminator) — the same
    # `\r`-progress output accumulates into a single line, as it did before this
    # knob existed.
    async def scenario() -> list[str]:
        proc = await Command(PY, ["-c", _PRINT_CR_PROGRESS]).astart()
        lines = [line async for line in proc.stdout_lines()]
        await proc.aoutcome()
        return lines

    assert asyncio.run(scenario()) == ["a\rb\rc"]


def test_line_terminator_sets_both_streams() -> None:
    # `line_terminator` (unlike `stdout_line_terminator`/`stderr_line_terminator`)
    # sets both streams at once; exercise it on stderr since the other test above
    # already covers stdout.
    code = "import sys; sys.stderr.write('a\\rb\\rc\\n'); sys.stderr.flush()"

    async def scenario() -> list[tuple[str, str]]:
        proc = await Command(PY, ["-c", code]).line_terminator("carriage_return").astart()
        events = [(str(e.stream), e.text) async for e in proc.output_events()]
        await proc.aoutcome()
        return events

    events = asyncio.run(scenario())
    stderr_lines = [text for stream, text in events if stream == "stderr"]
    assert stderr_lines == ["a", "b", "c"]


def test_output_events_cover_both_streams() -> None:
    async def scenario() -> list[tuple[str, str, bool]]:
        proc = await Command(PY, ["-c", _BOTH_STREAMS]).astart()
        events = [(str(e.stream), e.text.rstrip(), e.is_stderr) async for e in proc.output_events()]
        await proc.aoutcome()
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
        await proc.aoutcome()
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


def test_stdin_bytes_accepts_bytearray_and_memoryview() -> None:
    # ReadableBuffer (C7 batch A / C6): stdin_bytes() isn't bytes-only — any
    # buffer-protocol object PyO3 extracts a Vec<u8> from works.
    async def scenario(data: bytes | bytearray | memoryview) -> str:
        return await Command(PY, ["-c", _ECHO_UPPER]).stdin_bytes(data).arun()

    assert asyncio.run(scenario(bytearray(b"abc\n"))) == "ABC"
    assert asyncio.run(scenario(memoryview(b"xyz\n"))) == "XYZ"


def test_interactive_stdin_write_bytes_and_flush() -> None:
    # `write(bytes)` + an explicit `flush()` were previously never exercised
    # (only `write_line`/`close` had coverage). `write` takes raw bytes (no
    # newline added), so terminate the lines ourselves for the echo-by-line
    # child to see each one before EOF.
    async def scenario() -> list[str]:
        proc = await Command(PY, ["-c", _ECHO_UPPER]).keep_stdin_open().astart()
        stdin = proc.take_stdin()
        await stdin.write(b"raw-hello\n")
        await stdin.flush()
        await stdin.write(b"raw-world\n")
        await stdin.flush()
        await stdin.close()
        lines = [line.rstrip() async for line in proc.stdout_lines()]
        await proc.aoutcome()
        return lines

    assert asyncio.run(scenario()) == ["RAW-HELLO", "RAW-WORLD"]


def test_interactive_stdin_write_accepts_bytearray_and_memoryview() -> None:
    async def scenario() -> list[str]:
        proc = await Command(PY, ["-c", _ECHO_UPPER]).keep_stdin_open().astart()
        stdin = proc.take_stdin()
        await stdin.write(bytearray(b"from-bytearray\n"))
        await stdin.flush()
        await stdin.write(memoryview(b"from-memoryview\n"))
        await stdin.flush()
        await stdin.close()
        lines = [line.rstrip() async for line in proc.stdout_lines()]
        await proc.aoutcome()
        return lines

    assert asyncio.run(scenario()) == ["FROM-BYTEARRAY", "FROM-MEMORYVIEW"]


def test_take_stdin_is_once() -> None:
    # The first take hands over the handle; a second take raises (consumed).
    async def scenario() -> None:
        proc = await Command(PY, ["-c", _ECHO_UPPER]).keep_stdin_open().astart()
        first = proc.take_stdin()
        with pytest.raises(ProcessError):
            proc.take_stdin()
        await first.close()
        await proc.aoutcome()

    asyncio.run(scenario())


def test_take_stdin_without_keep_open_raises() -> None:
    # Forgetting keep_stdin_open() fails clearly at take_stdin(), not later with
    # an AttributeError on a None.
    async def scenario() -> None:
        proc = await Command(PY, ["-c", "pass"]).astart()
        with pytest.raises(ProcessError):
            proc.take_stdin()
        await proc.aoutcome()

    asyncio.run(scenario())


def test_running_process_output_captures() -> None:
    async def scenario() -> ProcessResult:
        proc = await Command(PY, ["-c", "print('captured')"]).astart()
        return await proc.aoutput()

    result = asyncio.run(scenario())
    assert result.stdout.strip() == "captured"
    assert result.is_success


def test_kill_then_wait_returns_promptly() -> None:
    # kill() must actually terminate the child — a no-op would leave aoutcome()
    # blocking on the 60s sleeper until the bounded wait_for trips. Pins the
    # effect, not just the renamed name.
    async def scenario() -> Outcome:
        proc = await Command(PY, ["-c", "import time; time.sleep(60)"]).astart()
        proc.kill()
        return await asyncio.wait_for(proc.aoutcome(), timeout=15.0)

    outcome = asyncio.run(scenario())
    assert not outcome.exited_zero  # killed, not a clean exit


def test_shutdown_grace_terminates_and_returns_outcome() -> None:
    # shutdown()/ashutdown() = graceful signal -> wait grace -> hard kill,
    # consuming the handle. A no-op would hang on the 60s sleeper past the
    # bounded wait_for.
    async def scenario() -> Outcome:
        proc = await Command(PY, ["-c", "import time; time.sleep(60)"]).astart()
        return await asyncio.wait_for(proc.ashutdown(grace_seconds=0.5), timeout=15.0)

    outcome = asyncio.run(scenario())
    assert not outcome.exited_zero  # terminated, not clean


def test_running_process_wait_reports_exit_code() -> None:
    async def scenario() -> Outcome:
        proc = await Command(PY, ["-c", "import sys; sys.exit(3)"]).astart()
        return await proc.aoutcome()

    outcome = asyncio.run(scenario())
    assert outcome.code == 3
    assert not outcome.exited_zero
    assert outcome.signal is None  # clean exit, not a signal
    assert not outcome.timed_out


def test_consumed_handle_raises() -> None:
    async def scenario() -> None:
        proc = await Command(PY, ["-c", "pass"]).astart()
        await proc.aoutcome()
        # The handle is spent; a second consuming call must raise.
        await proc.aoutcome()

    with pytest.raises(ProcessError):
        asyncio.run(scenario())


def test_async_verb_without_running_loop_leaves_handle_usable() -> None:
    # Calling an `a`-prefixed consuming verb (e.g. `aoutcome()`) from sync code,
    # with no asyncio event loop running, must not destroy the still-live
    # process as a side effect of the error path — it must raise cleanly and
    # leave the handle intact and reusable, not spend it. (The sync twin,
    # `outcome()`, is the correct call from sync code — this test pins the
    # failure mode of reaching for the wrong one, not a missing capability.)
    proc = Command(PY, ["-c", "import time; time.sleep(30)"]).start()
    pid = proc.pid
    assert pid is not None
    with pytest.raises(ProcessError):
        # No running event loop: raises synchronously, before any await is
        # even reachable -- that's the point of this test, not a missing await.
        proc.aoutcome()  # type: ignore[unused-coroutine]
    assert proc.pid == pid, "the handle must not be consumed by the failed call"
    assert is_alive(pid), "the process must still be alive after the failed call"

    async def reap() -> None:
        await proc.aoutcome()

    asyncio.run(reap())
    assert wait_dead(pid, timeout=10.0)


def test_running_process_sync_twins_of_every_consuming_verb() -> None:
    # `start()` (sync) is genuinely usable end-to-end: every consuming verb has
    # a sync twin (Stage 3 / C3), not just `outcome()`. Exercise each one on its
    # own handle, entirely from sync code, no event loop anywhere.
    assert Command(PY, ["-c", "import sys; sys.exit(3)"]).start().outcome().code == 3

    proc = Command(PY, ["-c", "print('hi')"]).start()
    finished = proc.finish()
    assert finished.exited_zero
    assert finished.stderr == ""

    result = Command(PY, ["-c", "print('captured')"]).start().output()
    assert isinstance(result, ProcessResult)
    assert result.stdout.strip() == "captured"

    code = "import sys; sys.stdout.buffer.write(bytes([1, 2, 255]))"
    raw = Command(PY, ["-c", code]).start().output_bytes()
    assert isinstance(raw, BytesResult)
    assert raw.stdout == bytes([1, 2, 255])

    proc = Command(PY, ["-c", "import time; time.sleep(0.1)"]).start()
    prof = proc.profile(0.02)
    assert isinstance(prof, RunProfile)
    assert prof.code == 0

    proc = Command(PY, ["-c", "import time; time.sleep(60)"]).start()
    outcome = proc.shutdown(grace_seconds=0.3)
    assert isinstance(outcome, Outcome)
    assert not outcome.exited_zero  # terminated, not a clean exit


def test_running_process_sync_verb_reentrant_call_leaves_handle_usable() -> None:
    # A sync consuming verb (e.g. `outcome()`) called reentrantly — here, from
    # inside a Supervisor's `stop_when` predicate running on the tokio runtime —
    # must have its reentrant-runtime check run BEFORE the handle is taken out
    # of `self`; otherwise the failed call would still spend (and thus leak)
    # the process. Mirrors
    # `test_reentrant_run_call_leaves_the_target_supervisor_usable` for
    # `Supervisor.run()`.
    proc = Command(PY, ["-c", "import time; time.sleep(30)"]).start()
    pid = proc.pid
    assert pid is not None

    def reentrant_stop(_result: object) -> bool:
        with pytest.raises(ProcessError):
            proc.outcome()  # re-enters the runtime: must raise, not spend `proc`
        return True

    driver = Supervisor(
        Command(PY, ["-c", "print('y')"]), restart="always", stop_when=reentrant_stop
    )
    driver.run()
    assert proc.pid == pid, "the handle must not be consumed by the failed reentrant call"
    assert is_alive(pid), "the process must still be alive after the failed reentrant call"

    proc.kill()
    proc.outcome()  # now off the runtime: consumes and reaps it for real
    assert wait_dead(pid, timeout=10.0)


def test_cancel_mid_stream_kills_tree(pid_file: pathlib.Path) -> None:
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
        return await proc.aprofile(0.02)

    rp = asyncio.run(scenario())
    assert isinstance(rp, RunProfile)
    assert rp.code == 0
    assert rp.duration_seconds >= 0.0
    assert rp.samples >= 1
    assert rp.cpu_time_seconds is None or rp.cpu_time_seconds >= 0.0
    assert rp.peak_memory_bytes is None or rp.peak_memory_bytes >= 0
    assert rp.avg_cpu_cores is None or rp.avg_cpu_cores >= 0.0
    # profile()/aprofile() is a superset of outcome()/aoutcome(): it also
    # carries how the run ended.
    assert rp.timed_out is False
    assert rp.signal is None
    assert rp.outcome.code == 0
    assert rp.outcome.exited_zero is True
    assert rp.outcome.timed_out is False


@pytest.mark.parametrize("bad_interval", [0.0, -1.0])
def test_profile_rejects_non_positive_interval(bad_interval: float) -> None:
    async def scenario() -> None:
        proc = await Command(PY, ["-c", "pass"]).astart()
        await proc.aprofile(bad_interval)

    with pytest.raises(ValueError):
        asyncio.run(scenario())


def test_profile_tiny_interval_is_clamped_not_a_hang() -> None:
    # The crate clamps a sub-millisecond sampling period to 1ms internally
    # (tokio panics on a zero interval; a tiny-but-positive one would otherwise
    # spin the sampler as fast as the scheduler allows) — this must complete
    # promptly with a well-formed profile, not hang or flood.
    async def scenario() -> RunProfile:
        proc = await Command(PY, ["-c", "import time; time.sleep(0.1)"]).astart()
        return await asyncio.wait_for(proc.aprofile(1e-9), timeout=10.0)

    rp = asyncio.run(scenario())
    assert isinstance(rp, RunProfile)
    assert rp.code == 0
    assert rp.samples >= 1


def test_profile_of_a_timed_out_run() -> None:
    # profile()/aprofile() is a superset of outcome()/aoutcome(): it must
    # still report a well-formed
    # profile when the run ends via Command.timeout() rather than a clean
    # exit, with `timed_out`/`outcome.timed_out` reflecting that.
    async def scenario() -> RunProfile:
        proc = await Command(PY, ["-c", "import time; time.sleep(30)"]).timeout(0.3).astart()
        return await proc.aprofile(0.05)

    rp = asyncio.run(scenario())
    assert isinstance(rp, RunProfile)
    assert rp.timed_out is True
    assert rp.outcome.timed_out is True
    assert rp.code is None
    assert rp.duration_seconds >= 0.0


def test_running_process_output_bytes() -> None:
    async def scenario() -> BytesResult:
        code = "import sys; sys.stdout.buffer.write(bytes([1, 2, 255]))"
        proc = await Command(PY, ["-c", code]).astart()
        return await proc.aoutput_bytes()

    result = asyncio.run(scenario())
    assert result.stdout == bytes([1, 2, 255])


# --- stdout_tee / stderr_tee — file sink, async paths (T-004) ----------------


def test_stdout_tee_with_aoutput_keeps_capture(tmp_path: pathlib.Path) -> None:
    # The async whole-run capture verb (aoutput) tees each line to the file while
    # keeping the captured result whole — the async twin of the sync `output()`
    # tee coverage.
    sink = tmp_path / "out.log"

    async def scenario() -> ProcessResult:
        code = "print('alpha', flush=True); print('beta', flush=True)"
        return await Command(PY, ["-c", code]).stdout_tee(sink).aoutput()

    result = asyncio.run(scenario())
    assert result.is_success
    assert result.stdout.splitlines() == ["alpha", "beta"]
    assert sink.read_bytes() == b"alpha\nbeta\n"


def test_stdout_tee_streams_with_start_and_stdout_lines(tmp_path: pathlib.Path) -> None:
    # The tee also works with the streaming line verbs (start + stdout_lines), not
    # only the whole-run capture verbs: the file receives the same lines the
    # iterator yields, flushed by the pump at stream end.
    sink = tmp_path / "out.log"

    async def scenario() -> list[str]:
        proc = await Command(PY, ["-c", _PRINT_LINES]).stdout_tee(sink).astart()
        lines = [line.rstrip() async for line in proc.stdout_lines()]
        await proc.afinish()
        return lines

    lines = asyncio.run(scenario())
    assert lines == [f"line{i}" for i in range(5)]
    assert sink.read_bytes() == b"".join(f"line{i}\n".encode() for i in range(5))


# --- context-manager teardown (standalone start() owns a private tree) -------


def test_running_process_sync_with_reaps_tree(pid_file: pathlib.Path) -> None:
    # A standalone start() owns a private tree; the `with` exit must kill it.
    with Runner().start(spawn_grandchild_command(pid_file)):
        grandchild = read_pid_when_ready(pid_file, timeout=10.0)
    assert wait_dead(grandchild, timeout=10.0), "grandchild survived the with-block exit"


def test_command_start_is_sync_twin_of_astart(pid_file: pathlib.Path) -> None:
    # Command.start() is the synchronous counterpart of astart(): sync setup
    # returning a RunningProcess that owns a private tree and reaps it on exit —
    # no detour through Runner() needed.
    with spawn_grandchild_command(pid_file).start():
        grandchild = read_pid_when_ready(pid_file, timeout=10.0)
    assert wait_dead(grandchild, timeout=10.0), "Command().start() handle didn't reap on exit"


def test_running_process_async_with_reaps_tree(pid_file: pathlib.Path) -> None:
    async def scenario() -> int:
        async with await spawn_grandchild_command(pid_file).astart():
            return read_pid_when_ready(pid_file, timeout=10.0)

    grandchild = asyncio.run(scenario())
    assert wait_dead(grandchild, timeout=10.0), "grandchild survived the async-with exit"


def test_context_manager_is_noop_after_consuming() -> None:
    async def scenario() -> None:
        async with await Command(PY, ["-c", "print('hi')"]).astart() as proc:
            result = await proc.aoutput()  # consumes the handle
            assert result.is_success
        # __aexit__ sees a consumed handle and must not raise.

    asyncio.run(scenario())


def test_with_reaps_tree_even_when_block_raises(pid_file: pathlib.Path) -> None:
    grandchild = -1
    with (
        pytest.raises(RuntimeError, match="boom"),
        Runner().start(spawn_grandchild_command(pid_file)),
    ):
        grandchild = read_pid_when_ready(pid_file, timeout=10.0)
        raise RuntimeError("boom")
    assert grandchild > 0
    assert wait_dead(grandchild, timeout=10.0), "grandchild survived a raising with-block"


def test_async_with_reaps_tree_even_when_block_raises(pid_file: pathlib.Path) -> None:
    captured: dict[str, int] = {}

    async def scenario() -> None:
        async with await spawn_grandchild_command(pid_file).astart():
            captured["pid"] = read_pid_when_ready(pid_file, timeout=10.0)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(scenario())
    assert wait_dead(captured["pid"], timeout=10.0), "grandchild survived a raising async-with"


def test_shared_group_streaming_enforces_command_timeout() -> None:
    # A command's own .timeout() is enforced while streaming a *shared-group* handle
    # (group.astart -> stdout_lines): a quiet, never-exiting child is killed at the
    # deadline and reported as timed-out, instead of leaving the stream pending
    # forever. This path's deadline watchdog was fixed in the processkit 1.2.0 bump
    # (it previously armed only for own-group `Command().astart()` handles).
    async def scenario() -> bool:
        cmd = Command(PY, ["-c", "import time; time.sleep(60)"]).timeout(1.0)
        async with ProcessGroup() as group:
            proc = await group.astart(cmd)
            async for _line in proc.stdout_lines():  # arms the deadline watchdog
                pass
            finished = await proc.afinish()
            return finished.outcome.timed_out

    # Outer bound: if the deadline were not enforced (the pre-1.2.0 behavior) the
    # stream would hang; fail loudly at 30s instead of hanging the suite.
    assert asyncio.run(asyncio.wait_for(scenario(), timeout=30.0))
