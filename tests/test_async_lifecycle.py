"""Async-bridge lifecycle: every `a`-prefixed verb returns a *lazy*,
owner-aware awaitable, not an eagerly-spawned task.

The bridge in `src/runtime.rs` used to hand each verb's future straight to
`pyo3_async_runtimes`' `future_into_py`, which spawns the work on the shared
tokio runtime the instant the verb is called and keeps it running even if the
awaitable is never awaited, its last owner is dropped, or the loop closes. That
leaked children (a bare `Command.aoutput()` with no `await`) and, worse, pinned
an unbounded `Supervisor(restart="always").arun()` -- plus every Python callback
it captured -- for the life of the interpreter.

These tests pin the fixed contract: nothing runs until the first `await`
(so a dropped-without-await verb starts no process and releases what it
captured), and an operation left active when the loop is torn down is still
reaped. The cancellation half of the contract (an explicitly cancelled awaited
run tears down its tree) lives in `test_async.py`; this module covers the
never-awaited / owner-lost / loop-shutdown halves.

Tests drive asyncio with ``asyncio.run`` so no pytest-asyncio plugin is needed.
"""

from __future__ import annotations

import asyncio
import gc
import pathlib
import socket
import weakref

import pytest

from processkit import Command, Supervisor

from ._liveness import is_alive, read_pid_when_ready, wait_dead
from .conftest import PY, spawn_grandchild_command

# A grandchild-spawning child writes its grandchild PID to the pid file as its
# very first act, then sleeps -- so "the pid file never appears" is proof the
# child never ran at all. The never-await scenarios drop the awaitable, then
# keep the loop turning for this long: an *eagerly*-spawned bridge would have
# started its child (and written the pid file) within this window, so a still-
# empty pid file after it proves the work never started.
_START_GRACE = 1.5


def test_completion_never_calls_into_the_loop_from_a_runtime_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The completion handoff must stay off ``call_soon_threadsafe``.

    The old bridge called it while attached to Python on a tokio thread. The
    call wakes the loop after queuing the result, so the awaiting coroutine
    could resume and start interpreter finalization before that thread had
    left Python. The socket wakeup path has no reason to call this method at
    all; making it fail pins that architectural safety property directly.
    """

    async def scenario() -> None:
        loop = asyncio.get_running_loop()

        def forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("async completion used call_soon_threadsafe")

        monkeypatch.setattr(loop, "call_soon_threadsafe", forbidden)
        result = await asyncio.wait_for(Command(PY, ["-c", "print('done')"]).aoutput(), 10.0)
        assert result.stdout.strip() == "done"

    asyncio.run(scenario())


def test_completion_reuses_one_wakeup_socket_per_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streaming-style repeated awaits must not allocate a socket each time."""

    async def scenario() -> None:
        real_socketpair = socket.socketpair
        calls = 0

        def recording_socketpair() -> tuple[socket.socket, socket.socket]:
            nonlocal calls
            calls += 1
            return real_socketpair()

        # Patch after asyncio.run created its own loop/self-pipe; only bridge
        # socketpairs are counted.
        monkeypatch.setattr(socket, "socketpair", recording_socketpair)
        for _ in range(3):
            result = await Command(PY, ["-c", "pass"]).aexit_code()
            assert result == 0
        assert calls == 1

    asyncio.run(scenario())


def test_completion_closes_wakeup_socket_when_event_loop_goes_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared receiver must not survive as a pending task at loop teardown."""

    readers: list[socket.socket] = []

    async def scenario() -> None:
        real_socketpair = socket.socketpair

        def recording_socketpair() -> tuple[socket.socket, socket.socket]:
            reader, writer = real_socketpair()
            readers.append(reader)
            return reader, writer

        monkeypatch.setattr(socket, "socketpair", recording_socketpair)
        assert await Command(PY, ["-c", "pass"]).aexit_code() == 0
        # The completed awaiter runs before the hub's idle callback. Yield once
        # more so that callback can close the otherwise-pending sock_recv task.
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert len(readers) == 1
    assert readers[0].fileno() == -1


def test_completion_closes_wakeup_socket_after_last_operation_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled last operation must retire the hub, not park it armed.

    Only a *completion* wakes the shared receiver, and only the idle callback it
    schedules ever closes an idle hub. A cancelled operation instead drops its
    entry silently (`PyCancelCallback`), so cancelling the last one left the hub
    armed with nothing able to wake it -- pinning this socket and a pending
    `sock_recv` task on a loop that has no processkit work left at all. Asserted
    from *inside* the loop: `asyncio.run`'s own shutdown cancels leftover tasks
    and would close the socket afterwards either way, hiding the difference.
    """

    readers: list[socket.socket] = []

    async def scenario() -> None:
        real_socketpair = socket.socketpair

        def recording_socketpair() -> tuple[socket.socket, socket.socket]:
            reader, writer = real_socketpair()
            readers.append(reader)
            return reader, writer

        monkeypatch.setattr(socket, "socketpair", recording_socketpair)
        task = asyncio.ensure_future(Command(PY, ["-c", "import time; time.sleep(60)"]).aoutput())
        await asyncio.sleep(0.2)  # register with the hub and arm its receive
        assert len(readers) == 1, "the operation never reached the completion hub"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Retirement costs a few turns: the wakeup byte, the receive it
        # completes, the drain that finds nothing ready, then the idle callback.
        for _ in range(200):
            if readers[0].fileno() == -1:
                break
            await asyncio.sleep(0.01)
        assert readers[0].fileno() == -1, (
            "the hub stayed armed after its last operation was cancelled"
        )

    asyncio.run(scenario())


def test_completion_closes_wakeup_socket_when_its_event_loop_is_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A loop collected with its hub still open must not leak the socket.

    `asyncio.run` cancels every leftover task before closing its loop, which
    drives the hub's cancelled branch and closes the reader there. A loop driven
    by hand -- `run_until_complete` then `close`, what `tests/test_event_loops.py`
    does for uvloop and an ordinary way to embed a private loop -- cancels
    nothing and stops the moment its main coroutine returns, so it can be torn
    down before `PyHubIdleCallback` (the only thing that retires an idle hub)
    ever gets its turn. The weak-key map's anchor is then the reader's last
    owner, and dropping it -- which the collected loop triggers, from the map's
    own removal callback -- has to close the descriptor, or it dies unclosed as a
    `ResourceWarning` raised against whatever unrelated code runs that GC pass.

    Dropping that idle callback on the floor pins the "torn down too early"
    state deterministically, rather than racing a real loop's shutdown.
    """

    readers: list[socket.socket] = []
    loop = asyncio.new_event_loop()
    # Weak, and the real `call_soon` is reached through the class: a bound
    # method (or a `monkeypatch` undo entry) held by this frame would keep the
    # loop alive and there would be nothing to collect below.
    loop_ref = weakref.ref(loop)

    def recording_socketpair() -> tuple[socket.socket, socket.socket]:
        reader, writer = real_socketpair()
        readers.append(reader)
        return reader, writer

    def call_soon_dropping_hub_idle(callback: object, *args: object, **kwargs: object) -> object:
        if type(callback).__name__ == "PyHubIdleCallback":
            return None
        live = loop_ref()
        assert live is not None
        return type(live).call_soon(live, callback, *args, **kwargs)  # type: ignore[arg-type]

    real_socketpair = socket.socketpair
    # Patched only after the loop exists: a loop builds its own self-pipe
    # socketpair at construction, and only the hub's belongs in `readers`.
    monkeypatch.setattr(socket, "socketpair", recording_socketpair)
    loop.call_soon = call_soon_dropping_hub_idle  # type: ignore[assignment]

    async def scenario() -> None:
        assert await Command(PY, ["-c", "pass"]).aexit_code() == 0
        # Turns to spare: the hub would retire itself here if its idle callback
        # were reaching the loop at all.
        for _ in range(5):
            await asyncio.sleep(0)

    loop.run_until_complete(scenario())
    loop.close()
    assert len(readers) == 1
    assert readers[0].fileno() != -1, (
        "the hub retired itself, so this never exercised loop collection"
    )

    del loop
    gc.collect()
    assert readers[0].fileno() == -1, "collecting the event loop left the hub's wakeup socket open"


def test_dropped_aoutput_without_await_never_spawns(pid_file: pathlib.Path) -> None:
    # Building the awaitable and dropping it without ever awaiting must start
    # nothing: a Rust future is inert until polled, and the lazy bridge does not
    # hand it to the runtime until the first `await`. Done inside a live loop so
    # an eager bridge (the old behavior) would genuinely have a loop to spawn on.
    async def scenario() -> None:
        awaitable = spawn_grandchild_command(pid_file).aoutput()
        del awaitable
        gc.collect()
        # Turn the loop: an eager spawn would reach its pid-file write by now.
        await asyncio.sleep(_START_GRACE)

    asyncio.run(scenario())
    assert not pid_file.exists(), (
        "aoutput() dropped without await spawned a process -- the bridge is not lazy"
    )


def test_dropped_astart_without_await_never_spawns(pid_file: pathlib.Path) -> None:
    # `astart()` is lazy too: no handle, no process, until awaited.
    async def scenario() -> None:
        awaitable = spawn_grandchild_command(pid_file).astart()
        del awaitable
        gc.collect()
        await asyncio.sleep(_START_GRACE)

    asyncio.run(scenario())
    assert not pid_file.exists(), "astart() dropped without await spawned a process"


def test_dropped_arun_releases_callbacks_and_never_supervises(
    pid_file: pathlib.Path,
) -> None:
    # The motivating case: an unbounded restart="always" supervisor whose
    # `arun()` awaitable is dropped without ever being awaited must start no
    # restart loop (no child ever spawns) and must release the Python callback
    # it captured, rather than pinning it -- and everything it closes over --
    # for the life of the interpreter.
    holder: dict[str, weakref.ref[object]] = {}

    class _Sentinel:
        """Weak-referenceable marker held *only* through the captured callback,
        so the weakref dying proves the callback was released."""

        flag = False

    async def scenario() -> None:
        sentinel = _Sentinel()
        holder["weak"] = weakref.ref(sentinel)

        def stop_when(_result: object) -> bool:
            # Close over `sentinel`: any surviving reference to this predicate
            # keeps the sentinel alive, so the weakref is our release probe.
            return sentinel.flag

        supervisor = Supervisor(
            spawn_grandchild_command(pid_file),
            restart="always",
            stop_when=stop_when,
        )
        awaitable = supervisor.arun()
        # Drop the supervision work without ever awaiting it: `del awaitable`
        # releases the supervisor (and the callback it captured) held by the
        # bridge, and the remaining owners -- the `stop_when` closure and
        # `sentinel` -- fall out of scope when this coroutine returns.
        del awaitable, supervisor
        gc.collect()
        # Turn the loop: an eager supervisor would have spawned its child by now.
        await asyncio.sleep(_START_GRACE)

    asyncio.run(scenario())
    gc.collect()

    assert not pid_file.exists(), (
        "arun() dropped without await started supervision (spawned the child)"
    )
    assert holder["weak"]() is None, (
        "arun() dropped without await kept its stop_when callback alive"
    )


def test_event_loop_shutdown_with_active_operation_reaps_tree(
    pid_file: pathlib.Path,
) -> None:
    # An operation still active when the event loop is torn down must be reaped,
    # not leaked. Here the scenario returns while its `aoutput()` task is still
    # pending; `asyncio.run` cancels every pending task (and runs the
    # cancellation to completion, tearing the tree down) before closing the
    # loop.
    async def scenario() -> int:
        task = asyncio.ensure_future(spawn_grandchild_command(pid_file).aoutput())
        grandchild_pid = await asyncio.to_thread(read_pid_when_ready, pid_file, 10.0)
        assert is_alive(grandchild_pid)
        # Leave `task` deliberately pending: loop shutdown must reap it.
        assert not task.done()
        return grandchild_pid

    grandchild_pid = asyncio.run(scenario())
    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived event-loop shutdown"
    )


def test_awaited_astart_still_runs_and_tears_down(pid_file: pathlib.Path) -> None:
    # Sanity counterpart to the never-awaited tests: laziness must not break the
    # ordinary path -- an awaited verb still starts its work, and an explicit
    # async teardown still reaps the whole private tree, grandchild included.
    async def scenario() -> int:
        proc = await spawn_grandchild_command(pid_file).astart()
        grandchild_pid = await asyncio.to_thread(read_pid_when_ready, pid_file, 10.0)
        assert is_alive(grandchild_pid)
        await proc.ashutdown(grace_seconds=0.2)
        return grandchild_pid

    grandchild_pid = asyncio.run(scenario())
    assert wait_dead(grandchild_pid, timeout=10.0), (
        f"grandchild {grandchild_pid} survived an awaited astart() + ashutdown()"
    )
