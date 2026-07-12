"""Thread-safety of the Python-facing surface — the suite that backs the
first-class free-threaded-CPython claim (`gil_used = false`, a dedicated
cp314t wheel, the whole suite re-run on 3.14t in CI). Every other test file is
single-threaded (the only prior `threading` use anywhere was SIGINT delivery
in `test_command.py`); this file is the one place several threads genuinely
touch the same `Command`/`ProcessGroup`/`CliClient`/runner-double/
`CancellationToken` object at once.

Each test synchronizes threads with a `threading.Barrier`/`Event` (never a bare
`time.sleep` standing in for "prove no race happened") and relies on the
suite-wide `pytest-timeout` (`timeout = 60`, `timeout_method = "thread"` in
`pyproject.toml`) as the hang guard — no bespoke per-test timeout mechanism. A
short `time.sleep` does still appear in a couple of places below, but only to
give a just-spawned child a moment to actually start before it is cancelled/
signalled from another thread — the same pattern `test_command.py` and
`test_cli_client.py` already use for `cancel_on`, not a substitute for real
synchronization.

`PROCESSKIT_STRESS_SCALE` (see `test_hardening.py`) scales the thread/
iteration counts here too, so a scheduled nightly/weekly hardening run can
exercise this file harder without slowing down the default PR-gate run.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import os
import pathlib
import threading
import time

from processkit import (
    CancellationToken,
    Cancelled,
    CliClient,
    Command,
    NonZeroExit,
    ProcessError,
    ProcessGroup,
    Supervisor,
    Unsupported,
)
from processkit.testing import RecordReplayRunner, Reply, ScriptedRunner

from ._liveness import wait_dead
from .conftest import NO_SUCH_PROGRAM, PY

# See `test_hardening.py`'s `_stress_scale` for the rationale (kept small here
# on purpose, duplicated rather than imported — test modules don't reach into
# each other's internals): defaults to 1 (fast PR gate), overridable for a
# scheduled hardening run.


def _stress_scale() -> int:
    try:
        scale = int(os.environ.get("PROCESSKIT_STRESS_SCALE", "1"))
    except ValueError:
        scale = 1
    return max(1, scale)


_SCALE = _stress_scale()


# --- parallel sync verbs from a thread pool ---------------------------------


def test_parallel_output_from_thread_pool_returns_correct_results_per_thread() -> None:
    # Several threads spawn and wait on short-lived children AT THE SAME TIME
    # via `ThreadPoolExecutor`; each call must come back with exactly its own
    # (distinguishable) stdout/exit code — no cross-thread data corruption —
    # and none may raise an unexpected exception (`future.result()` would
    # re-raise it here).
    n = 16 * _SCALE

    def run_one(i: int) -> tuple[int, str, int | None]:
        code = f"import sys; sys.stdout.write('worker-{i}'); sys.exit({i % 7})"
        result = Command(PY, ["-c", code]).output()
        return i, result.stdout, result.code

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = [f.result() for f in [pool.submit(run_one, i) for i in range(n)]]

    assert len(results) == n
    for i, stdout, code in results:
        assert stdout == f"worker-{i}", "a worker saw another worker's stdout"
        assert code == i % 7, "a worker saw another worker's exit code"


def test_parallel_run_from_thread_pool_raises_only_for_its_own_failure() -> None:
    # The `.run()` verb (raises NonZeroExit on failure) mixed across threads:
    # only the threads whose OWN command fails must see an exception, and it
    # must carry THEIR OWN exit code, not a neighbor's.
    n = 16 * _SCALE

    def run_one(i: int) -> tuple[int, str | None, int | None]:
        should_fail = i % 2 == 0
        code = f"import sys; sys.stdout.write('r-{i}'); sys.exit({0 if not should_fail else i + 1})"
        try:
            out = Command(PY, ["-c", code]).run()
            return i, out, None
        except NonZeroExit as exc:
            return i, None, exc.code

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run_one, range(n)))

    for i, out, exit_code in results:
        if i % 2 == 0:
            assert out is None
            assert exit_code == i + 1
        else:
            assert out == f"r-{i}"
            assert exit_code is None


# --- a shared ProcessGroup under concurrent start() -------------------------


def test_shared_process_group_concurrent_starts_are_consistent() -> None:
    # Several threads call `group.start(...)` on the SAME group at once (all
    # released together via a Barrier, not staggered) — the group's bookkeeping
    # must stay consistent: every thread gets back a distinct real pid (no
    # handle aliasing/corruption), `stats()` doesn't crash, and the group's own
    # `__exit__` still reaps every one of them.
    n_threads = 8 * _SCALE
    barrier = threading.Barrier(n_threads)
    pids: list[int] = []
    lock = threading.Lock()

    def start_one() -> None:
        barrier.wait(timeout=30)
        running = group.start(Command(PY, ["-c", "import time; time.sleep(5)"]))
        assert running.pid is not None
        with lock:
            pids.append(running.pid)

    with ProcessGroup() as group:
        threads = [threading.Thread(target=start_one) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(pids) == n_threads
        assert len(set(pids)) == n_threads, "two threads got back the same pid"

        with contextlib.suppress(Unsupported):
            # Not a strict `== n_threads` count: the mechanism's own count can
            # include bookkeeping beyond just these direct children (see
            # `test_group_stats`'s own `>= 1`, not an exact figure) — the point
            # here is only that a concurrent `stats()` call doesn't raise/crash.
            stats = group.stats()
            assert stats.active_process_count >= 1

    # The `with` block's `__exit__` (a single shutdown, no longer racing any
    # `start()` call) must still reap every child that the concurrent starts
    # above created.
    for pid in pids:
        assert wait_dead(pid, timeout=15.0), f"child {pid} survived the group's teardown"


def test_group_start_races_with_kill_all_stay_consistent() -> None:
    # `kill_all()` (like `start()`) takes only a shared borrow at the binding
    # layer, so — unlike `shutdown()`/`__exit__` below — racing it against
    # concurrent `start()` calls on the same group is expected to be safe: no
    # crash, no corruption, and every `start()` call resolves cleanly one way
    # or the other (a real pid, or a clean `ProcessError` for the rare loser of
    # the spawn-vs-kill race), never any other exception type.
    n_threads = 8 * _SCALE
    outcomes: list[tuple[str, int | None]] = []
    lock = threading.Lock()
    stop = threading.Event()

    def start_one() -> None:
        try:
            running = group.start(Command(PY, ["-c", "import time; time.sleep(2)"]))
            outcome: tuple[str, int | None] = ("started", running.pid)
        except ProcessError:
            outcome = ("rejected", None)
        with lock:
            outcomes.append(outcome)

    def kill_loop() -> None:
        while not stop.is_set():
            group.kill_all()
            time.sleep(0.01)

    with ProcessGroup() as group:
        killer = threading.Thread(target=kill_loop)
        killer.start()
        threads = [threading.Thread(target=start_one) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        stop.set()
        killer.join(timeout=30)

        assert len(outcomes) == n_threads
        assert all(kind in ("started", "rejected") for kind, _ in outcomes)

        for kind, pid in outcomes:
            if kind == "started":
                assert pid is not None
                assert wait_dead(pid, timeout=15.0), f"child {pid} survived kill_all()"


def test_group_start_vs_shutdown_race_is_hardened_and_reaps_the_tree() -> None:
    # Regression for T-052 (was a *pinned known limitation* before the fix):
    # `ProcessGroup` is now `#[pyclass(frozen)]` with an interior `Mutex`, so
    # `start()` on one thread racing `shutdown()`/`__exit__` on another no longer
    # collides on PyO3's per-object borrow flag. The concurrent `start()` must
    # resolve cleanly EITHER way — a real pid (it won the race, the child was
    # started before the group closed) or the library's own `ProcessError` (it
    # lost, the group was already closed) — and NEVER a raw `RuntimeError`
    # ("Already borrowed"). There is deliberately no `except RuntimeError`
    # clause: a raw borrow error must now propagate and fail the test.
    #
    # The second half is the load-bearing part of the fix: because `__exit__`/
    # `shutdown()` no longer extract a `&mut self` borrow that can fail *before*
    # the teardown body, the graceful teardown is never skipped — so every child
    # that DID start is reaped by the group's own shutdown here, not left alive
    # for a later hard kill when the object is GC'd.
    n_threads = 8
    group = ProcessGroup()
    outcomes: list[str] = []
    started_pids: list[int] = []
    lock = threading.Lock()
    # +1 for the main thread: every starter and the shutdown are released from
    # the barrier together, to actually hit the race window rather than run the
    # starts fully before the teardown.
    barrier = threading.Barrier(n_threads + 1)

    def start_one() -> None:
        barrier.wait(timeout=30)
        try:
            running = group.start(Command(PY, ["-c", "import time; time.sleep(5)"]))
            assert running.pid is not None
            with lock:
                outcomes.append("started")
                started_pids.append(running.pid)
        except ProcessError:
            with lock:
                outcomes.append("rejected")

    threads = [threading.Thread(target=start_one) for _ in range(n_threads)]
    for t in threads:
        t.start()

    # Release the starters and tear the group down at (nearly) the same instant.
    barrier.wait(timeout=30)
    group.shutdown()

    for t in threads:
        t.join(timeout=30)

    assert len(outcomes) == n_threads
    assert all(kind in ("started", "rejected") for kind in outcomes), (
        f"a start resolved as neither a pid nor a clean ProcessError: {outcomes!r}"
    )

    # A single graceful `shutdown()` above (now always reliable — no borrow race
    # to retry around) must have reaped every child that started.
    for pid in started_pids:
        assert wait_dead(pid, timeout=15.0), f"child {pid} survived the group's graceful teardown"


def test_group_methods_during_teardown_never_raise_a_raw_borrow_error() -> None:
    # Regression for T-052: with `ProcessGroup` frozen + interior `Mutex`, any
    # `&self` method (`stats`, `members`, `kill_all`, `__repr__`) called from
    # other threads WHILE `shutdown()` tears the group down returns a value or a
    # clean, typed error (`ProcessError` once closed, or `Unsupported` where the
    # mechanism can't answer) — never a raw `RuntimeError("Already borrowed")`
    # from PyO3's reentrancy guard, which the old `&mut self`-holding `shutdown`
    # produced for the whole (GIL-released) teardown window.
    n_callers = 8
    group = ProcessGroup()
    # Seed a real child so the teardown has non-trivial work to do.
    group.start(Command(PY, ["-c", "import time; time.sleep(5)"]))

    raw_errors: list[BaseException] = []
    stop = threading.Event()
    lock = threading.Lock()

    def caller() -> None:
        # Cheap, read-only-ish ops only (no spawning in a hot loop): the point is
        # to hammer the borrow surface, not to start a storm of processes.
        ops = (group.stats, group.members, group.kill_all, lambda: repr(group))
        while not stop.is_set():
            for op in ops:
                try:
                    op()
                except (ProcessError, Unsupported):
                    pass  # typed, expected — the group is closing/closed
                except RuntimeError as exc:  # the bug this test guards against
                    with lock:
                        raw_errors.append(exc)
                    return

    callers = [threading.Thread(target=caller) for _ in range(n_callers)]
    for t in callers:
        t.start()

    # Let the callers spin against the live group briefly, then tear it down out
    # from under them.
    time.sleep(0.1)
    group.shutdown()
    stop.set()

    for t in callers:
        t.join(timeout=30)

    assert not raw_errors, f"a concurrent method saw a raw borrow error: {raw_errors!r}"


def test_running_process_teardown_races_with_getters_are_hardened() -> None:
    # Regression for T-052, the `RunningProcess` half: the consuming verbs
    # (`shutdown`/`outcome`/`__exit__`/…) used to hold a `&mut self` PyO3 borrow
    # across the entire GIL-released wait, so a concurrent `&self` getter
    # (`pid`, `repr`, `owns_group`) from another thread hit "Already borrowed".
    # Now `RunningProcess` is frozen + interior `Mutex`: those getters return a
    # value or `None` (once the handle is consumed) — never a raw `RuntimeError`
    # — and the process is still torn down.
    n_readers = 8
    proc = Command(PY, ["-c", "import time; time.sleep(5)"]).start()
    pid = proc.pid
    assert pid is not None

    raw_errors: list[BaseException] = []
    stop = threading.Event()
    lock = threading.Lock()

    def reader() -> None:
        while not stop.is_set():
            try:
                _ = proc.pid
                _ = repr(proc)
                _ = proc.owns_group
            except RuntimeError as exc:  # the bug this test guards against
                with lock:
                    raw_errors.append(exc)
                return

    readers = [threading.Thread(target=reader) for _ in range(n_readers)]
    for t in readers:
        t.start()

    # Let the readers spin against the live handle, then consume it from under
    # them with a graceful shutdown.
    time.sleep(0.1)
    proc.shutdown(grace_seconds=1.0)
    stop.set()

    for t in readers:
        t.join(timeout=30)

    assert not raw_errors, f"a concurrent getter saw a raw borrow error: {raw_errors!r}"
    assert wait_dead(pid, timeout=15.0), "the process survived its graceful shutdown"


# --- a Supervisor under a concurrent second run() ---------------------------


def test_supervisor_concurrent_run_never_raises_a_raw_borrow_error() -> None:
    # Regression for T-100, the `Supervisor` half of the T-052 family: `run()`
    # used to take a `&mut self` PyO3 borrow and hold it across the whole
    # (GIL-released) supervision loop, so a second `run()` from another thread
    # while one is in flight raced the per-object borrow flag and surfaced a raw
    # `RuntimeError("Already borrowed")`. Now `Supervisor` is frozen + interior
    # `Mutex`: the concurrent call resolves to the library's own typed
    # `ProcessError` ("already been run") — never a raw borrow error. Driven
    # through a `ScriptedRunner` so no real process spawns. There is deliberately
    # no `except RuntimeError` that hides the bug: a raw borrow error propagates
    # and fails the test.
    mid_run = threading.Event()
    release = threading.Event()

    def stop(_result: object) -> bool:
        # Runs on the tokio supervision worker while the main thread is parked in
        # `block_on`: signal that a `run()` is genuinely mid-flight, then hold
        # here until the second thread has made its concurrent call, so the race
        # window is real rather than assumed.
        mid_run.set()
        release.wait(timeout=30)
        return True  # stop after the first incarnation

    runner = ScriptedRunner()
    runner.fallback(Reply.ok("x"))
    sup = Supervisor(Command(NO_SUCH_PROGRAM), restart="always", stop_when=stop, runner=runner)

    outcomes: list[str] = []
    lock = threading.Lock()

    def second_run() -> None:
        mid_run.wait(timeout=30)  # only call once the first run() is mid-flight
        try:
            sup.run()
            outcome = "ran-twice"  # a supervisor must never run a second time
        except ProcessError:
            outcome = "typed"  # the expected, clean rejection
        except RuntimeError as exc:  # the bug this test guards against
            outcome = f"raw:{exc}"
        finally:
            release.set()  # let the first run's predicate return and finish
        with lock:
            outcomes.append(outcome)

    t = threading.Thread(target=second_run)
    t.start()
    first = sup.run()
    t.join(timeout=30)

    assert first.stopped == "predicate"
    assert outcomes == ["typed"], f"a concurrent run() did not reject cleanly: {outcomes!r}"


# --- a shared CliClient under concurrent calls ------------------------------


def test_shared_cli_client_concurrent_calls_return_correct_results() -> None:
    client = CliClient(PY)
    n = 16 * _SCALE

    def call_one(i: int) -> tuple[int, str]:
        return i, client.run(["-c", f"print('client-{i}')"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(call_one, range(n)))

    assert len(results) == n
    for i, out in results:
        assert out == f"client-{i}"


# --- a shared ScriptedRunner / RecordReplayRunner under concurrency ---------


def test_shared_scripted_runner_concurrent_calls_route_to_the_right_rule() -> None:
    # Rules are registered once, up front; only lookups happen concurrently —
    # each call must be routed by the rule that matches ITS OWN argv, never a
    # neighbor's.
    n_rules = 8
    runner = ScriptedRunner()
    for i in range(n_rules):
        runner.on([f"worker{i}"], Reply.ok(f"reply-{i}"))

    def call_one(i: int) -> tuple[int, str]:
        result = runner.output(Command(f"worker{i}"))
        return i, result.stdout

    calls = list(range(n_rules)) * (4 * _SCALE)
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_rules) as pool:
        results = list(pool.map(call_one, calls))

    for i, out in results:
        assert out == f"reply-{i}"


def test_shared_scripted_runner_on_sequence_advances_exactly_once_per_call() -> None:
    # `on_sequence` carries mutable per-rule progression state (which reply is
    # "next"), unlike the stateless prefix rules above — the interesting
    # thread-safety question. `n` concurrent calls (all released together via
    # a Barrier) against a sequence of exactly `n` distinct replies must
    # collectively consume each reply EXACTLY once: the returned bag of
    # results must be the full set, with no reply skipped (a lost update) or
    # handed to two threads at once (a torn read of the progression counter).
    n = 8 * _SCALE
    runner = ScriptedRunner()
    runner.on_sequence(["deploy"], [Reply.ok(f"seq-{i}") for i in range(n)])
    barrier = threading.Barrier(n)

    def call_one(_: int) -> str:
        barrier.wait(timeout=30)
        return runner.run(Command("deploy"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
        outputs = list(pool.map(call_one, range(n)))

    assert sorted(outputs) == sorted(f"seq-{i}" for i in range(n))


def test_shared_record_replay_runner_concurrent_replays_are_correct(tmp_path: pathlib.Path) -> None:
    n = 8 * _SCALE
    cassette = tmp_path / "concurrent.json"
    recorder = RecordReplayRunner.record(str(cassette))
    for i in range(n):
        recorder.run(Command(PY, ["-c", f"print('replay-{i}')"]))
    recorder.save()

    replayer = RecordReplayRunner.replay(str(cassette))

    def call_one(i: int) -> tuple[int, str]:
        return i, replayer.run(Command(PY, ["-c", f"print('replay-{i}')"]))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(call_one, range(n)))

    for i, out in results:
        assert out == f"replay-{i}"


# --- CancellationToken.cancel() from a different thread --------------------


def test_cancel_from_one_thread_stops_sync_runs_in_other_threads() -> None:
    # A single token shared across several threads' own `Command(...).run()`
    # calls: firing `cancel()` from the main thread must stop every one of
    # them, each raising `Cancelled` on its OWN thread.
    token = CancellationToken()
    n_workers = 4 * _SCALE
    results: list[BaseException | None] = [None] * n_workers

    def worker(i: int) -> None:
        cmd = Command(PY, ["-c", "import time; time.sleep(30)"]).cancel_on(token)
        try:
            cmd.run()
        except Cancelled as exc:
            results[i] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
    for t in threads:
        t.start()

    # Give every child a moment to actually start before cancelling (mirrors
    # `test_cancel_on_tears_down_the_run_and_raises_cancelled` in
    # test_command.py) — not a substitute for the Cancelled assertion below.
    time.sleep(0.3)
    token.cancel()

    for t in threads:
        t.join(timeout=30)

    for i, result in enumerate(results):
        assert isinstance(result, Cancelled), f"worker {i} did not observe Cancelled: {result!r}"
        assert result.program == PY


# --- mixed sync calls from worker threads over a running event loop --------


def test_mixed_sync_calls_from_threads_over_a_running_event_loop() -> None:
    # The main thread drives an asyncio event loop (`asyncio.run`) while
    # several worker threads make ordinary SYNC `Command(...).output()` calls
    # at the same time — the scenario the pyo3-async-runtimes bridge must not
    # let corrupt either side's state. Both the sync workers' results and the
    # loop's own async results must come back correct and undisturbed.
    n_workers = 4 * _SCALE
    iterations = 5
    sync_results: list[tuple[int, int, str, int | None]] = []
    lock = threading.Lock()

    def sync_worker(i: int) -> None:
        for j in range(iterations):
            code = f"import sys; sys.stdout.write('sw-{i}-{j}'); sys.exit({(i + j) % 5})"
            result = Command(PY, ["-c", code]).output()
            with lock:
                sync_results.append((i, j, result.stdout, result.code))

    threads = [threading.Thread(target=sync_worker, args=(i,)) for i in range(n_workers)]
    for t in threads:
        t.start()

    async def main_loop() -> list[str]:
        return [await Command(PY, ["-c", f"print('async-{i}')"]).arun() for i in range(6)]

    async_outs = asyncio.run(main_loop())

    for t in threads:
        t.join(timeout=30)

    assert async_outs == [f"async-{i}" for i in range(6)]
    assert len(sync_results) == n_workers * iterations
    for i, j, stdout, code in sync_results:
        assert stdout == f"sw-{i}-{j}", "a sync worker saw another worker's/the loop's stdout"
        assert code == (i + j) % 5, "a sync worker saw another worker's/the loop's exit code"
