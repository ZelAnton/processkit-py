"""Async streaming, interactive stdin, and the `RunningProcess` handle.

Tests drive asyncio with ``asyncio.run`` so no pytest-asyncio plugin is needed.
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import io
import pathlib
import sys
import time

import pytest

from processkit import (
    BytesResult,
    Command,
    Finished,
    LifecycleEvent,
    Outcome,
    ProcessError,
    ProcessGroup,
    ProcessResult,
    Runner,
    RunProfile,
    Supervisor,
    Unsupported,
)

from ._liveness import is_alive, read_pid_when_ready, wait_dead, wait_until
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

# Echoes the first raw stdin byte to stdout.
_ECHO_ONE_STDIN_BYTE = (
    "import sys; "
    "data = sys.stdin.buffer.read(1); "
    "sys.stdout.buffer.write(data); "
    "sys.stdout.buffer.flush()"
)

# stdout + stderr on both streams.
_BOTH_STREAMS = (
    "import sys; "
    "print('out1', flush=True); "
    "sys.stderr.write('err1\\n'); sys.stderr.flush(); "
    "print('out2', flush=True)"
)

# Prints one line and exits at once, but leaves behind a grandchild that holds
# the inherited stdout pipe open and speaks up over a second later. So the merged
# event stream keeps running well past the child's exit — the one shape in which
# "the stream has observed the exit" and "the consumer is still mid-iteration"
# are true at the same time, deterministically (see the early-`break` tests).
# The grandchild's delay is the margin the child gets to actually exit in, and
# the trailing sleep keeps the pipe open past the `break` (the handle's teardown
# kills the tree; the sleep only bounds a leak if it ever failed to).
_EXIT_LEAVING_A_TALKING_GRANDCHILD = (
    "import subprocess, sys\n"
    "subprocess.Popen([sys.executable, '-c', "
    "\"import time; time.sleep(1.5); print('late', flush=True); time.sleep(5)\"])\n"
    "print('parent-done', flush=True)\n"
)

# The same shape, with two changes that make it a *teardown* probe rather than an
# iteration one: the grandchild's PID goes to argv[1] (so `wait_dead` can watch it
# die) and it lingers far longer than any assertion window, so "the tree came
# down" cannot be confused with "the grandchild happened to finish".
_EXIT_LEAVING_A_TALKING_GRANDCHILD_PID_FILE = (
    "import subprocess, sys\n"
    "child = subprocess.Popen([sys.executable, '-c', "
    "\"import time; time.sleep(1.5); print('late', flush=True); time.sleep(60)\"])\n"
    "with open(sys.argv[1], 'w') as f:\n"
    "    f.write(str(child.pid))\n"
    "    f.flush()\n"
    "print('parent-done', flush=True)\n"
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
    # Finished.timed_out/signal mirror .outcome for a normal exit.
    assert finished.timed_out is finished.outcome.timed_out
    assert finished.timed_out is False
    assert finished.signal == finished.outcome.signal
    assert finished.signal is None


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


def test_lifecycle_events_cover_start_output_and_exit_in_order() -> None:
    async def scenario() -> tuple[int | None, list[LifecycleEvent], Finished]:
        proc = await Command(PY, ["-c", _BOTH_STREAMS]).astart()
        pid = proc.pid
        events = [event async for event in proc.lifecycle_events()]
        finished = await proc.afinish()
        return pid, events, finished

    pid, events, finished = asyncio.run(
        asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS)
    )
    assert events[0].kind == "started"
    assert events[0].pid == pid
    assert events[0].stream is None
    assert events[0].text is None
    assert events[0].outcome is None

    assert events[-1].kind == "exited"
    assert events[-1].pid is None
    assert events[-1].stream is None
    assert events[-1].text is None
    assert events[-1].outcome is not None
    assert events[-1].outcome.exited_zero
    assert events[-1].outcome == finished.outcome

    output: set[tuple[str, str]] = set()
    for event in events[1:-1]:
        assert event.kind in {"stdout", "stderr"}
        assert event.stream is not None
        assert event.text is not None
        output.add((event.stream, event.text.rstrip()))
    assert {("stdout", "out1"), ("stdout", "out2"), ("stderr", "err1")} <= output


def test_lifecycle_and_output_event_iterators_share_one_shot_stream() -> None:
    async def scenario() -> None:
        proc = await Command(PY, ["-c", "print('x')"]).astart()
        proc.lifecycle_events()
        with pytest.raises(ProcessError):
            proc.output_events()
        await proc.afinish()

    asyncio.run(scenario())


# --- the documented drain-then-finish order (processkit 3.0.0) ---------------
#
# In the Rust core, the merged event stream became the process's whole lifecycle
# in 3.0.0, and its terminal event is delivered at the moment the run is *reaped*.
# The crate therefore tells a Rust caller to drive the stream and its finisher
# together, and warns that draining the stream first and only then calling
# `finish()`/`wait()` parks forever waiting for a reap nobody started.
#
# This library's documented Python order is exactly that "forbidden" shape
# (`docs/streaming.md`, `docs/cookbook.md`, the `RunningProcess` docstrings, and
# `processkit run --idle-timeout`'s own implementation in `_cli/run.py`), and it
# stays that way: the binding drives the finisher itself, so the deadlock is
# closed inside the extension rather than pushed onto the Python caller.
#
# Every test below is bounded by an explicit deadline (`asyncio.wait_for`, the
# 3.10-compatible form this suite already uses — `asyncio.timeout` is 3.11+), so a
# regression FAILS the run instead of hanging it: a hung worker would stall the
# whole suite and report nothing useful about the cause.

_EVENTS_DEADLINE_SECONDS = 30.0


def test_output_events_drain_then_afinish_terminates() -> None:
    # The headline order: `async for` to exhaustion, THEN `await proc.afinish()`.
    # Both halves must complete — the iterator must end on its own (no external
    # cancellation) and the following finisher must report the real run.
    async def scenario() -> tuple[list[str], Finished]:
        proc = await Command(PY, ["-c", _BOTH_STREAMS]).astart()
        texts = [ev.text.rstrip() async for ev in proc.output_events()]
        finished = await proc.afinish()
        return texts, finished

    texts, finished = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    assert {"out1", "out2", "err1"} <= set(texts)
    assert finished.exited_zero
    assert finished.code == 0


def test_output_events_drain_then_aoutcome_terminates() -> None:
    # The same order with the other finisher: `aoutcome()` must report the run
    # too, not raise "handle consumed" because the binding drove the reap.
    async def scenario() -> Outcome:
        proc = await Command(PY, ["-c", _PRINT_LINES]).astart()
        async for _ev in proc.output_events():
            pass
        return await proc.aoutcome()

    outcome = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    assert outcome.exited_zero
    assert outcome.timed_out is False


def test_lifecycle_drive_racing_aoutcome_never_reports_consumed() -> None:
    async def one_run() -> tuple[Outcome, list[LifecycleEvent]]:
        proc = await Command(PY, ["-c", "pass"]).astart()
        stream = proc.lifecycle_events()

        async def drain() -> list[LifecycleEvent]:
            return [event async for event in stream]

        draining = asyncio.create_task(drain())
        await asyncio.sleep(0)
        outcome = await proc.aoutcome()
        return outcome, await draining

    async def scenario() -> list[tuple[Outcome, list[LifecycleEvent]]]:
        # Several short runs widen the take_claim/start_joint_finish publication
        # race without relying on a test-only synchronization hook.
        return await asyncio.gather(*(one_run() for _ in range(32)))

    results = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    for outcome, events in results:
        assert outcome.exited_zero
        assert outcome.timed_out is False
        assert events[0].kind == "started"
        assert events[-1].kind == "exited"


def test_output_events_drain_then_finish_reports_a_nonzero_exit() -> None:
    # The finisher after a drained stream must carry the real exit status, not a
    # fabricated success — the run's outcome travels through the binding's own
    # finisher unchanged.
    code = "import sys; print('bye', flush=True); sys.exit(3)"

    async def scenario() -> Finished:
        proc = await Command(PY, ["-c", code]).astart()
        async for _ev in proc.output_events():
            pass
        return await proc.afinish()

    finished = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    assert finished.code == 3
    assert not finished.exited_zero


def test_output_events_drain_then_afinish_terminates_for_a_slow_child() -> None:
    # A child that keeps the stream open across several seconds: the binding must
    # not decide the run is over early (truncating output) just because the stream
    # went quiet between lines, and must still terminate once the child exits.
    code = "import time\nfor i in range(4):\n print(i, flush=True); time.sleep(0.3)\n"

    async def scenario() -> tuple[list[str], Finished]:
        proc = await Command(PY, ["-c", code]).astart()
        texts = [ev.text.rstrip() async for ev in proc.output_events()]
        finished = await proc.afinish()
        return texts, finished

    texts, finished = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    assert texts == ["0", "1", "2", "3"]
    assert finished.exited_zero


def test_output_events_yields_only_line_events_never_empty_lifecycle_items() -> None:
    # What the Python iterator sees for the crate's NON-LINE lifecycle events
    # (`Started { pid }` leads the 3.0.0 stream, `Exited(outcome)` ends it, and the
    # enum is non-exhaustive so more may follow): nothing at all. They are filtered
    # out in `PyOutputEvent::from_event`, never surfaced as an `OutputEvent` with
    # an empty `text` — which would be indistinguishable from a real blank output
    # line and would corrupt any consumer that counts or joins lines.
    #
    # The child prints three non-empty lines and one deliberately EMPTY one, so the
    # assertions below separate the two failure modes: a leaked lifecycle event
    # would add empty-text items (count > 4), while over-eager filtering would drop
    # the child's own blank line (count < 4).
    code = (
        "import sys; "
        "print('a', flush=True); "
        "print('', flush=True); "
        "sys.stderr.write('b\\n'); sys.stderr.flush(); "
        "print('c', flush=True)"
    )

    async def scenario() -> list[tuple[str, str]]:
        proc = await Command(PY, ["-c", code]).astart()
        events = [(str(ev.stream), ev.text.rstrip("\r\n")) async for ev in proc.output_events()]
        await proc.afinish()
        return events

    events = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    # Interleaving between the two streams is best-effort, so compare as a
    # multiset; the per-stream order is pinned by the other tests here.
    assert sorted(events) == sorted(
        [("stdout", "a"), ("stdout", ""), ("stderr", "b"), ("stdout", "c")]
    ), events
    # Exactly one empty-text item: the child's own blank line. Anything more is a
    # lifecycle event leaking through as a phantom blank line.
    assert sum(1 for _stream, text in events if text == "") == 1
    # And no item is a stand-in for the terminal event: every item names a real
    # stream, and the count matches the four lines the child actually wrote.
    assert len(events) == 4
    assert all(stream in {"stdout", "stderr"} for stream, _text in events)


def test_running_process_stays_live_while_events_stream() -> None:
    # The binding starts the run's finisher itself so the stream can end, but only
    # once the child has been observed to exit — so while output is still flowing
    # the handle is untouched: `pid` reads and the live line counters tick. Pins
    # that the joint drive did not quietly spend the handle for the whole streamed
    # run (which would make every getter read `None` and `kill()` raise).
    code = "import time\nfor i in range(3):\n print(i, flush=True); time.sleep(0.2)\n"

    async def scenario() -> tuple[list[int | None], list[int | None]]:
        proc = await Command(PY, ["-c", code]).astart()
        pids: list[int | None] = []
        counts: list[int | None] = []
        async for _ev in proc.output_events():
            pids.append(proc.pid)
            counts.append(proc.stdout_line_count)
        await proc.afinish()
        return pids, counts

    pids, counts = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    assert len(pids) == 3
    # The pid is readable for every observed line (never `None`, which is what a
    # prematurely-consumed handle would report), and is the same process each time.
    assert all(isinstance(p, int) for p in pids), pids
    assert len({p for p in pids if p is not None}) == 1
    # The live counter is readable too, and never goes backwards.
    assert all(isinstance(c, int) for c in counts), counts
    assert counts == sorted(c for c in counts if c is not None)


def test_handle_serves_another_task_while_the_events_stream_is_parked() -> None:
    # The harder half of the test above: not "while output flows" (where the
    # iterator is between `__anext__` calls anyway) but *while `__anext__` itself
    # is parked* on a child that has gone quiet — the state a `tail -f`-shaped
    # child spends nearly all its time in. A second asyncio task must still see a
    # live handle there: `pid` and the live counters read real values and
    # `kill()` reaches the child, instead of raising "the process handle has been
    # consumed" for a process that is very much running.
    #
    # (The drive's exit probe answers in one synchronous poll under the handle's
    # own lock, leaving the process in its slot; a probe that borrowed the process
    # out of the slot across the park would fail every assertion below.)
    code = "import time; print('ready', flush=True); time.sleep(60)"

    async def scenario() -> tuple[int | None, int | None, list[str]]:
        proc = await Command(PY, ["-c", code]).astart()
        texts: list[str] = []
        first_line = asyncio.Event()

        async def drain() -> None:
            async for ev in proc.output_events():
                texts.append(ev.text.rstrip())
                first_line.set()

        streaming = asyncio.create_task(drain())
        # From here the child is silent for a minute: `__anext__` is parked.
        await asyncio.wait_for(first_line.wait(), timeout=10.0)
        await asyncio.sleep(0.3)
        pid, lines = proc.pid, proc.stdout_line_count
        # Reaches the live child (a consumed handle would raise here) and ends
        # the stream, so the drain task can finish.
        proc.kill()
        await asyncio.wait_for(streaming, timeout=10.0)
        await proc.afinish()
        return pid, lines, texts

    pid, lines, texts = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    assert isinstance(pid, int) and pid > 0
    assert lines == 1
    assert texts == ["ready"]
    assert wait_dead(pid, timeout=10.0), "the concurrent kill() did not reach the child"


def test_async_with_reaps_tree_when_a_streamed_events_loop_is_cancelled(
    pid_file: pathlib.Path,
) -> None:
    # Cancelling a parked `async for … output_events()` must not cost the
    # deterministic teardown the context manager promises (docs/streaming.md,
    # "Deterministic teardown" and the `asyncio.timeout` pattern): leaving the
    # block still hard-kills the whole private tree, grandchild included.
    #
    # The child here is silent (it spawns a grandchild and sleeps), so the
    # cancellation lands while `__anext__` is parked, and the block is left with
    # the cancellation still *in flight* — `task.cancel()` only schedules it, and
    # nothing is awaited in between, which is exactly what `asyncio.wait_for`'s
    # own timeout does to the stream. An events drive that had borrowed the
    # process out of the handle's slot for the duration of that park would leave
    # `__aexit__` with nothing to kill (a silent no-op), and the tree would live
    # on until the interpreter got around to collecting the objects.
    #
    # Deliberately keeps the handle referenced past the block: dropping it would
    # kill the tree on its own (kill-on-drop), which would let a `__aexit__` that
    # quietly did nothing still pass this test. Holding it means only the
    # context-manager exit can be what kills the tree.
    keep_alive: list[object] = []

    async def scenario() -> int:
        proc = await spawn_grandchild_command(pid_file).astart()
        keep_alive.append(proc)

        async def drain() -> None:
            async for _ev in proc.output_events():
                pass

        streaming = asyncio.create_task(drain())
        async with proc:
            grandchild = read_pid_when_ready(pid_file, timeout=10.0)
            # Let the iterator reach its parked state on the silent child.
            await asyncio.sleep(0.3)
            assert is_alive(grandchild)
            streaming.cancel()
            # No await here: the block is left while the cancellation is still
            # in flight.
        with contextlib.suppress(asyncio.CancelledError):
            await streaming
        return grandchild

    grandchild = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    assert wait_dead(grandchild, timeout=10.0), (
        "grandchild survived the async-with exit after a cancelled event stream"
    )


def test_async_with_reaps_the_tree_after_an_early_break_from_an_exited_child(
    pid_file: pathlib.Path,
) -> None:
    # The other half of the teardown promise, on the branch the crate-3.0 joint
    # finisher opened: once the events stream has observed the child exit it moves
    # the run into a background `finish()`, so the handle's own slot is empty from
    # then on. A `__aexit__` that only looked at that slot would find nothing and
    # return silently, leaving the surviving tree to whenever that background
    # finisher gave up on the pipe (see the assertion below) or the objects were
    # collected — the orphaned-tree failure mode this context manager exists to
    # prevent.
    #
    # Deterministic by construction, like the capture-verb boundary tests below:
    # the child exits right after its first line while its grandchild holds the
    # inherited stdout pipe and speaks a second later, so the `__anext__` that
    # fetches that late line parks with the child already gone — the drive's probe
    # arms the finisher — and the `break` afterwards is a genuine mid-stream exit
    # with the pipe still open. `proc.pid` reading `None` inside the block pins
    # that the joint finisher really was armed, so this cannot silently degrade
    # into "an ordinary handle was torn down".
    #
    # The handle is deliberately kept referenced past the block (`keep_alive`):
    # dropping it kills the tree on its own, which would let a `__aexit__` that
    # quietly did nothing still pass.
    keep_alive: list[object] = []

    async def scenario() -> tuple[int, list[str], int | None]:
        command = Command(PY, ["-c", _EXIT_LEAVING_A_TALKING_GRANDCHILD_PID_FILE, str(pid_file)])
        proc = await command.astart()
        keep_alive.append(proc)
        texts: list[str] = []
        async with proc:
            grandchild = read_pid_when_ready(pid_file, timeout=10.0)
            async for ev in proc.output_events():
                texts.append(ev.text.rstrip())
                if texts[-1] == "late":
                    break
            pid_after_break = proc.pid
            assert is_alive(grandchild), "the grandchild died before the block was left"
        return grandchild, texts, pid_after_break

    grandchild, texts, pid_after_break = asyncio.run(
        asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS)
    )
    # Premises: the loop was left early (mid-stream, pipe still held), and the
    # events stream had taken the run over by then — an un-taken run would still
    # report a live `pid` here.
    assert texts == ["parent-done", "late"], texts
    assert pid_after_break is None, "the events stream never took the run over"
    # A deliberately SHORT window, and the reason is the whole point of the test:
    # a teardown that no-ops here does not leak the tree forever — the background
    # finisher gives up joining the pipe after the crate's 5 s `PUMP_TEARDOWN` and
    # drops the process then — so an orphan is only visible as a *delay*. Anything
    # at or past that grace would pass with the regression in place; this window
    # must stay well under it. It is not tight: the exit kills synchronously, so
    # all this absorbs is the OS reaping the tree (measured at 0.00-0.02 s here),
    # against 5 s for the regression it has to catch.
    assert wait_dead(grandchild, timeout=2.0), (
        "grandchild outlived the async-with exit after an early break from an exited "
        "child — the tree was left to the background finisher, not torn down by the block"
    )


@pytest.mark.parametrize("stream_verb", ["output_events", "stdout_lines"])
def test_dropping_the_handle_kills_the_tree_while_a_stream_is_live(
    pid_file: pathlib.Path, stream_verb: str
) -> None:
    # Kill-on-drop must not be delegated to whoever else is holding the handle's
    # shared process slot. Both live streams here hold an `Arc` on that slot — the
    # events drive always, `stdout_lines()` whenever the command set an
    # `idle_timeout` (its watchdog kills through the same lock) — so a handle that
    # let the last `Arc` holder decide when the child dies would keep the whole
    # tree alive for as long as the stream object happened to live, silently
    # turning "dropping the handle tears the tree down" into "…once everything
    # referencing it is collected too".
    #
    # The stream deliberately outlives the handle, and is then drained: it must
    # simply END (its pipes died with the tree), promptly and without a hang.
    async def scenario() -> int:
        command = spawn_grandchild_command(pid_file)
        if stream_verb == "stdout_lines":
            # What makes *this* stream hold the shared slot; far longer than the
            # drain below, so an idle lapse can never be what ends the stream.
            command = command.idle_timeout(30.0)
        proc = await command.astart()
        stream = getattr(proc, stream_verb)()
        grandchild = read_pid_when_ready(pid_file, timeout=10.0)
        assert is_alive(grandchild)

        del proc
        gc.collect()

        async def drain() -> None:
            async for _item in stream:
                pass

        await asyncio.wait_for(drain(), timeout=10.0)
        return grandchild

    grandchild = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    assert wait_dead(grandchild, timeout=10.0), (
        f"grandchild survived the handle drop while a live {stream_verb}() stream held the slot"
    )


def test_output_events_break_early_then_afinish_still_reports_the_run() -> None:
    # Leaving the loop early (the common "stream until I see X" shape) must still
    # let the following finisher report the run rather than hang or raise.
    async def scenario() -> Finished:
        proc = await Command(PY, ["-c", _PRINT_LINES]).astart()
        async for ev in proc.output_events():
            if "line0" in ev.text:
                break
        return await proc.afinish()

    finished = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    assert isinstance(finished, Finished)


@pytest.mark.parametrize("verb", ["aoutput", "aoutput_bytes", "aprofile"])
def test_capture_verbs_after_a_drained_events_stream_are_diagnosed(verb: str) -> None:
    # `output()`/`output_bytes()`/`profile()` cannot report a run whose output was
    # streamed away and whose completion the events stream already drove: stdout
    # was consumed by the stream and stderr was delivered as events, so they never
    # had anything to capture (they returned empty ones). They now say so instead
    # of raising the generic "handle has been consumed", and the message names the
    # verbs that DO report such a run.
    #
    # Draining is the COMMON way to get here, not the condition — the two tests
    # below pin the actual boundary on both of its sides.
    async def scenario() -> None:
        proc = await Command(PY, ["-c", _PRINT_LINES]).astart()
        async for _ev in proc.output_events():
            pass
        args = [0.05] if verb == "aprofile" else []
        await getattr(proc, verb)(*args)

    with pytest.raises(ProcessError, match="output_events"):
        asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))


@pytest.mark.parametrize("verb", ["aoutput", "aoutput_bytes", "aprofile"])
def test_capture_verbs_after_an_early_break_from_an_exited_child_are_diagnosed(verb: str) -> None:
    # The boundary the docs state, from the side that is easy to get wrong: what
    # spends the run for these three verbs is the events stream having TAKEN THE
    # RUN OVER — which it does the moment its exit probe sees the child gone — not
    # the iterator having reached its end. An early `break` out of a command that
    # finished while it was being read lands on this side too, so "raises after a
    # drained stream" would be a promise narrower than the code (a user who broke
    # out early and got the error would read it as a bug).
    #
    # Deterministic, not a race: the child exits right after its first line, but
    # its grandchild keeps stdout open and prints a second later. The `__anext__`
    # that fetches that late line therefore has to park with the child already
    # gone — the drive probes every 50 ms while parked, so the finisher is armed —
    # and it still returns a line rather than ending the stream, so the `break`
    # below really is early, with the pipe still held open by the grandchild.
    async def scenario() -> tuple[list[str], bool, str | None]:
        proc = await Command(PY, ["-c", _EXIT_LEAVING_A_TALKING_GRANDCHILD]).astart()
        texts: list[str] = []
        broke_early = False
        async for ev in proc.output_events():
            texts.append(ev.text.rstrip())
            if texts[-1] == "late":
                broke_early = True
                break
        args = [0.05] if verb == "aprofile" else []
        try:
            await getattr(proc, verb)(*args)
        except ProcessError as exc:
            return texts, broke_early, str(exc)
        return texts, broke_early, None

    texts, broke_early, message = asyncio.run(
        asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS)
    )
    # The premise first: the loop was left early (mid-stream), not exhausted —
    # otherwise this would silently degenerate into the drained test above.
    assert broke_early, f"the grandchild's late line never arrived: {texts}"
    assert texts == ["parent-done", "late"], texts
    assert message is not None, f"{verb}() did not raise after an early break"
    assert "output_events" in message


def test_capture_verbs_still_report_a_run_left_while_the_child_was_running() -> None:
    # The other side of that boundary, pinned so it cannot drift unnoticed: break
    # out while the child is STILL RUNNING and nothing has been taken over —
    # nothing polls the events drive after the `break`, so its exit probe never
    # runs again and the run stays with the handle. `output()` then does exactly
    # what it did before the processkit 3.0 migration: waits for the exit and
    # returns the run with empty captures (stdout went to the iterator, stderr was
    # delivered as events). The narrowing above is only what the joint finisher
    # forces, never a wider "you streamed events, so no capture verbs" rule — and
    # `docs/streaming.md` documents both rows of the table because which one a
    # given `break` hits depends on the child's timing.
    code = "import time; print('first', flush=True); time.sleep(0.8)"

    async def scenario() -> ProcessResult:
        proc = await Command(PY, ["-c", code]).astart()
        async for _ev in proc.output_events():
            break  # the child sleeps on for a while yet
        return await proc.aoutput()

    result = asyncio.run(asyncio.wait_for(scenario(), timeout=_EVENTS_DEADLINE_SECONDS))
    assert result.stdout == ""
    assert result.stderr == ""
    assert result.outcome.exited_zero


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


def test_pty_interactive_input_round_trips_over_terminal_master() -> None:
    async def scenario() -> ProcessResult:
        code = "import sys; line=sys.stdin.readline(); print('reply:' + line.strip(), flush=True)"
        proc = await Command(PY, ["-c", code]).pty().keep_stdin_open().astart()
        stdin = proc.take_stdin()
        await stdin.write_line("hello")
        return await proc.aoutput()

    result = asyncio.run(asyncio.wait_for(scenario(), timeout=20.0))
    assert "reply:hello" in result.stdout


def test_pty_send_control_interrupts_the_child() -> None:
    async def scenario() -> Outcome:
        code = "import time; print('ready', flush=True); time.sleep(30)"
        proc = await Command(PY, ["-c", code]).pty().keep_stdin_open().astart()
        lines = proc.stdout_lines()
        assert (await anext(lines)).strip().endswith("ready")
        stdin = proc.take_stdin()
        await stdin.send_control("c")
        return await proc.aoutcome()

    outcome = asyncio.run(asyncio.wait_for(scenario(), timeout=20.0))
    assert not outcome.exited_zero


def test_resize_pty_accepts_live_terminal_and_rejects_plain_run() -> None:
    code = "import time; print('ready', flush=True); time.sleep(30)"
    pty_proc = Command(PY, ["-c", code]).pty(cols=100, rows=30).start()
    try:
        pty_proc.resize_pty(120, 40)
        with pytest.raises(ValueError, match="positive"):
            pty_proc.resize_pty(0, 40)
    finally:
        pty_proc.kill()
        pty_proc.outcome()

    plain_proc = Command(PY, ["-c", code]).start()
    try:
        with pytest.raises(Unsupported):
            plain_proc.resize_pty(120, 40)
    finally:
        plain_proc.kill()
        plain_proc.outcome()


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


def test_interactive_stdin_send_control_writes_control_byte() -> None:
    async def scenario() -> bytes:
        proc = await Command(PY, ["-c", _ECHO_ONE_STDIN_BYTE]).keep_stdin_open().astart()
        stdin = proc.take_stdin()
        await stdin.send_control("d")
        await stdin.close()
        result = await proc.aoutput_bytes()
        return result.stdout

    assert asyncio.run(scenario()) == b"\x04"


def test_interactive_stdin_send_control_rejects_invalid_argument() -> None:
    async def scenario() -> None:
        proc = await Command(PY, ["-c", _ECHO_ONE_STDIN_BYTE]).keep_stdin_open().astart()
        stdin = proc.take_stdin()
        with pytest.raises(ValueError):
            await stdin.send_control("0")
        with pytest.raises(ValueError):
            await stdin.send_control("cc")
        await stdin.close()
        await proc.aoutcome()

    asyncio.run(scenario())


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
        proc.aoutcome()
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


def test_bare_finish_with_output_limit_ignores_the_overflow_cap() -> None:
    # processkit 2.1.0: a bare finish() (no preceding stdout_lines()) no longer
    # enforces the capture policy's overflow cap over output nobody asked to
    # capture. A low max_lines cap with on_overflow="error" previously could
    # spuriously raise OutputTooLarge even though the caller never captured
    # stdout via stdout_lines() -- it now just discards the flood.
    code = "[print(f'line{i}', flush=True) for i in range(2000)]"
    proc = Command(PY, ["-c", code]).output_limit(max_lines=5, on_overflow="error").start()
    finished = proc.finish()  # no stdout_lines() beforehand
    assert finished.exited_zero
    assert finished.code == 0


def test_bare_afinish_with_output_limit_ignores_the_overflow_cap() -> None:
    # The async twin of the test above.
    async def scenario() -> Finished:
        code = "[print(f'line{i}', flush=True) for i in range(2000)]"
        cmd = Command(PY, ["-c", code]).output_limit(max_lines=5, on_overflow="error")
        proc = await cmd.astart()
        return await proc.afinish()  # no stdout_lines() beforehand

    finished = asyncio.run(scenario())
    assert finished.exited_zero
    assert finished.code == 0


def test_outcome_after_a_dropped_partial_stdout_lines_stream_ignores_the_cap() -> None:
    # processkit 2.1.0: the adjacent half of the same fix. wait()/profile()
    # (here, outcome()) called AFTER a stdout_lines() stream was started but
    # dropped before EOF (partial consumption) must not fall back to reusing
    # the caller's overflow-capped sink over the rest of the (unconsumed)
    # output -- it also routes through the internal discard sink, uncapped.
    async def scenario() -> Outcome:
        code = "[print(f'line{i}', flush=True) for i in range(2000)]"
        cmd = Command(PY, ["-c", code]).output_limit(max_lines=5, on_overflow="error")
        proc = await cmd.astart()
        seen = 0
        async for _line in proc.stdout_lines():
            seen += 1
            if seen >= 2:
                break  # drop the stream before EOF -- partial consumption
        return await proc.aoutcome()

    outcome = asyncio.run(scenario())
    assert outcome.exited_zero


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


def test_running_process_live_counters_track_streamed_output_and_elapsed_time() -> None:
    # `test_running_process_live_getters` above only ever asserts the counters'
    # starting `(0, None)` state -- a regression where `stdout_line_count` /
    # `stderr_line_count` got stuck there instead of tracking real output would
    # pass unnoticed. Here the child emits a known, fixed number of lines on
    # each stream, then sleeps briefly before exiting. Draining stdout via
    # `stdout_lines()` blocks until the child's stdout pipe closes -- i.e. until
    # the child has exited -- by which point stderr (drained in the background
    # the whole time, per docs/streaming.md) is fully captured too, so both
    # counters can be asserted against their known totals right after the loop
    # ends, while the handle is still live (`finish()`/`aoutcome()` blanks the
    # getters -- "None once consumed", see `stdout_line_count` in running.rs).
    stdout_n = 7
    stderr_n = 4
    code = (
        "import sys, time\n"
        f"for i in range({stdout_n}): print(f'out{{i}}', flush=True)\n"
        f"for i in range({stderr_n}): print(f'err{{i}}', file=sys.stderr, flush=True)\n"
        "time.sleep(0.2)\n"
    )

    async def scenario() -> tuple[int | None, int | None, float, float]:
        proc = await Command(PY, ["-c", code]).astart()
        elapsed_before = proc.elapsed_seconds or 0.0
        async for _line in proc.stdout_lines():
            pass  # drain until the child's stdout closes (i.e. the child exits)
        stdout_count = proc.stdout_line_count
        stderr_count = proc.stderr_line_count
        elapsed_after = proc.elapsed_seconds or 0.0
        await proc.afinish()  # reap
        return stdout_count, stderr_count, elapsed_before, elapsed_after

    stdout_count, stderr_count, elapsed_before, elapsed_after = asyncio.run(scenario())
    assert stdout_count == stdout_n
    assert stderr_count == stderr_n
    # The child slept 0.2s before exiting -- elapsed time must have grown.
    assert elapsed_after > elapsed_before


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


def test_on_stdout_line_fires_with_start_and_stdout_lines() -> None:
    # The per-line handler (T-037) also fires on a streamed run, not just the
    # whole-run capture verbs — same lines the iterator yields.
    seen: list[str] = []

    async def scenario() -> list[str]:
        proc = await Command(PY, ["-c", _PRINT_LINES]).on_stdout_line(seen.append).astart()
        lines = [line.rstrip() async for line in proc.stdout_lines()]
        await proc.afinish()
        return lines

    lines = asyncio.run(scenario())
    assert lines == [f"line{i}" for i in range(5)]
    assert seen == [f"line{i}" for i in range(5)]


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
            # Finished.timed_out/signal mirror .outcome for a real timeout too.
            assert finished.timed_out is finished.outcome.timed_out
            assert finished.signal == finished.outcome.signal
            return finished.outcome.timed_out

    # Outer bound: if the deadline were not enforced (the pre-1.2.0 behavior) the
    # stream would hang; fail loudly at 30s instead of hanging the suite.
    assert asyncio.run(asyncio.wait_for(scenario(), timeout=30.0))


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM trapping is POSIX-specific")
def test_shared_group_streaming_kills_a_signal_trapping_child_that_closes_stdout(
    tmp_path: pathlib.Path,
) -> None:
    # processkit 2.1.0: the one race that fix closes. A child that traps the
    # graceful signal and closes stdout (but does NOT exit) previously survived
    # if the consumer dropped its `RunningProcess` handle mid-grace: the closed
    # stream let the consumer's handle-drop abort the in-flight hard-kill
    # watchdog before it fired, so the child lived on until the *shared group
    # itself* was later dropped. The final SIGKILL is now a detached task no
    # handle-drop can abort.
    ready = tmp_path / "ready"
    code = (
        "import signal, sys, time\n"
        "signal.signal(signal.SIGTERM, lambda *a: sys.stdout.close())\n"
        f"open({str(ready)!r}, 'w').write('x')\n"
        "time.sleep(30)\n"
    )

    async def scenario() -> int:
        # `group` deliberately stays alive (in scope, un-dropped) for the whole
        # scenario: the assertion below must be satisfied by the per-command
        # watchdog's own hard kill, not by the group's own (best-effort)
        # teardown, which would mask the exact race this test targets.
        group = ProcessGroup(shutdown_grace=0.3)
        cmd = Command(PY, ["-c", code]).timeout(0.5)
        proc = await group.astart(cmd)
        pid = proc.pid
        assert pid is not None

        # Wait for the child to install its SIGTERM handler before its own
        # deadline trips, so the signal actually reaches a live trap.
        await asyncio.to_thread(wait_until, ready.exists, 10.0)

        async for _line in proc.stdout_lines():  # arms the deadline watchdog
            pass  # ends at EOF, once the child closes stdout on SIGTERM

        # The child is still alive here (it trapped the signal instead of
        # exiting) -- drop the handle right away, without ever calling
        # finish()/outcome() on it: the exact race the fix closes.
        del proc
        gc.collect()

        assert wait_dead(pid, timeout=10.0), (
            "the signal-trapping child survived its shared-group timeout + handle drop"
        )
        return pid

    asyncio.run(asyncio.wait_for(scenario(), timeout=30.0))


# --- stdout_tee / stderr_tee — Python writer sink, async paths (T-038) -------


def test_stdout_tee_to_writer_fires_on_the_async_path() -> None:
    # The writer-object tee works on the async verbs too — one bridge, both
    # paths, exactly like the file tee and the per-line callbacks.
    buf = io.StringIO()

    async def scenario() -> ProcessResult:
        return await Command(PY, ["-c", _PRINT_LINES]).stdout_tee(buf).aoutput()

    result = asyncio.run(scenario())
    assert result.is_success
    assert buf.getvalue() == "line0\nline1\nline2\nline3\nline4\n"


def test_stdout_tee_propagates_non_attribute_error_from_write_lookup() -> None:
    # `is_python_writer` probes `sink.write`; only `AttributeError` means "no
    # such attribute, treat as a path". A sink whose `write` is a property (or
    # `__getattr__`) that raises something else must see that original
    # exception surface, not get reinterpreted as "this is a path" and fail
    # with a confusing "expected str/PathLike" TypeError instead.
    class BrokenWriter:
        @property
        def write(self) -> object:
            raise RuntimeError("write is not ready yet")

    with pytest.raises(RuntimeError, match="write is not ready yet"):
        Command(PY, ["-c", _PRINT_LINES]).stdout_tee(BrokenWriter())  # type: ignore[arg-type]


def test_tee_to_slow_writer_does_not_block_the_event_loop() -> None:
    # A blocking (sleeping) write() must not stall the asyncio loop: each write is
    # dispatched to the runtime's blocking pool, so a concurrent asyncio task keeps
    # ticking while the tee absorbs the slow writer's backpressure — and every line
    # still arrives (no deadlock).
    class SlowWriter:
        def __init__(self) -> None:
            self.chunks: list[str] = []

        def write(self, data: str) -> int:
            time.sleep(0.02)  # blocks ~20ms per write (time.sleep releases the GIL)
            self.chunks.append(data)
            return len(data)

    async def scenario() -> tuple[ProcessResult, SlowWriter, int]:
        writer = SlowWriter()
        stop = asyncio.Event()
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0.005)

        tick_task = asyncio.create_task(ticker())
        # 8 lines, each a line-write + a "\n"-write of ~20ms => >300ms of blocking
        # writes on the pool; the loop stays free to tick throughout.
        code = "[print(f'line{i}', flush=True) for i in range(8)]"
        result = await Command(PY, ["-c", code]).stdout_tee(writer).aoutput()
        stop.set()
        await tick_task
        return result, writer, ticks

    result, writer, ticks = asyncio.run(scenario())
    assert result.is_success
    # No deadlock and correct mirroring: every line reached the slow writer.
    expected = "".join(f"line{i}\n" for i in range(8))
    assert "".join(writer.chunks) == expected
    # The event loop kept running during the blocking writes — had write() run on
    # the loop thread, the ticker could not have advanced. Generous margin.
    assert ticks > 3
