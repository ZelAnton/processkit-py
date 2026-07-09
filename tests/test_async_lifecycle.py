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
import weakref

from processkit import Supervisor

from ._liveness import is_alive, read_pid_when_ready, wait_dead
from .conftest import spawn_grandchild_command

# A grandchild-spawning child writes its grandchild PID to the pid file as its
# very first act, then sleeps -- so "the pid file never appears" is proof the
# child never ran at all. The never-await scenarios drop the awaitable, then
# keep the loop turning for this long: an *eagerly*-spawned bridge would have
# started its child (and written the pid file) within this window, so a still-
# empty pid file after it proves the work never started.
_START_GRACE = 1.5


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
