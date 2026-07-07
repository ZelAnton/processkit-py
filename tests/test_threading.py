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
    Unsupported,
)
from processkit.testing import RecordReplayRunner, Reply, ScriptedRunner

from ._liveness import wait_dead
from .conftest import PY

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


def test_group_start_vs_shutdown_race_never_hangs_or_leaks_a_child() -> None:
    # Known limitation, pinned rather than assumed away: `start()` takes a
    # shared (`&self`) borrow and `shutdown()`/`__exit__` take an exclusive
    # (`&mut self`) borrow at the PyO3 binding layer. A genuine cross-thread
    # race between the two can therefore surface as a raw `RuntimeError`
    # ("Already borrowed" / "Already mutably borrowed") from PyO3's own
    # reentrancy guard, instead of the library's own `ProcessError` — this
    # construction is not currently hardened against `start()` and
    # `shutdown()`/`__exit__` being called concurrently, from different
    # threads, on the very same group instance (as opposed to the
    # `kill_all()` case above, which only ever takes a shared borrow and is
    # safe). What must still hold, whichever of those two exception shapes
    # comes back (or a clean success): no thread hangs, and no started child
    # process survives past the test.
    n_threads = 8
    group = ProcessGroup()
    outcomes: list[str] = []
    lock = threading.Lock()

    def start_one() -> None:
        try:
            running = group.start(Command(PY, ["-c", "import time; time.sleep(5)"]))
            assert running.pid is not None
            with lock:
                outcomes.append("started")
                started_pids.append(running.pid)
        except ProcessError:
            with lock:
                outcomes.append("rejected")
        except RuntimeError as exc:
            assert "borrow" in str(exc).lower(), f"unexpected RuntimeError: {exc!r}"
            with lock:
                outcomes.append("borrow_race")

    started_pids: list[int] = []
    threads = [threading.Thread(target=start_one) for _ in range(n_threads)]
    for t in threads:
        t.start()

    try:
        group.shutdown()
    except RuntimeError as exc:
        assert "borrow" in str(exc).lower(), f"unexpected RuntimeError: {exc!r}"

    for t in threads:
        t.join(timeout=30)

    assert len(outcomes) == n_threads
    assert all(kind in ("started", "rejected", "borrow_race") for kind in outcomes)

    # Whatever the race above did, the group must end the test fully torn
    # down: retry shutdown() (idempotent once no other thread contends for the
    # borrow) until it actually goes through.
    for _ in range(50):
        try:
            group.shutdown()
            break
        except RuntimeError:
            time.sleep(0.05)

    for pid in started_pids:
        assert wait_dead(pid, timeout=15.0), f"child {pid} survived the start/shutdown race"


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
