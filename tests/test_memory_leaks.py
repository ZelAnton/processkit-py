"""Memory and reference stability checks for repeated binding operations."""

from __future__ import annotations

import asyncio
import ctypes
import gc
import importlib
import mmap
import os
import pickle
import platform
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import pytest

from processkit import Command, ProcessGroup, Supervisor, Unsupported
from processkit.testing import Reply, ScriptedRunner

from .conftest import PY

# `leak` is registered in `[tool.pytest.ini_options] markers` (pyproject.toml),
# whose default `addopts` deselects it (`-m "not leak"`) so this module never
# collects under `just test`, a bare `uv run pytest`, `docker/Dockerfile`'s
# default CMD, canary.yml/canary-next.yml, or the mutmut baseline pass.
# Callers that actually want it select this file/marker explicitly, always
# alongside `-p no:xdist` (nightly-hardening.yml's `memory-leaks` job, `just
# leak-test`) — `-p no:xdist` because process-level RSS is only meaningful
# measured serially in one interpreter, not split across xdist workers.
pytestmark = pytest.mark.leak

_KIB = 1024
# See its use in `_assert_stable_memory` for the calibration rationale.
_HANDLE_GROWTH_TOLERANCE = 8
# R-02 fix-cycle finding: at 20 iterations/3 warmup, RSS/tracemalloc/gc-object
# noise on a real (non-leaking) Windows dev box empirically overlaps the same
# order of magnitude as the exact injected-leak signal (tens of KB and low
# hundreds of bytes respectively) -- see the
# `test_harness_detects_an_injected_os_handle_leak` canary below for why the
# OS handle/fd metric, not iteration count alone, is what actually closes that
# gap (a one-time allocator/measurement fluctuation does not scale with
# iteration count the way a genuine per-iteration leak does, so more
# iterations does still help the *ratio*, all else equal). Iteration count is
# raised modestly from the original 20 (not pushed further): each real
# iteration here spawns a real subprocess, some of them two, and this module
# was empirically observed (in this fix cycle, running its full test order
# back to back on Windows) to occasionally trip the ~60s per-test timeout
# threshold, and independently the stdlib's `socket.socketpair()` fallback
# used by `asyncio`'s Windows proactor loop, via intermittent, load-dependent
# OS-level slowness unrelated to this module's own logic -- more iterations
# means more exposure to that pre-existing hazard, not just a better signal-
# to-noise ratio, so this stays a modest raise, not an aggressive one.
_WARMUP_ITERATIONS = 3
_BASE_ITERATIONS = 24


def _stress_scale() -> int:
    try:
        scale = int(os.environ.get("PROCESSKIT_STRESS_SCALE", "1"))
    except ValueError:
        return 1
    return max(1, scale)


_STRESS_SCALE = _stress_scale()
_ITERATIONS = _BASE_ITERATIONS * _STRESS_SCALE


@dataclass(frozen=True)
class _MemorySnapshot:
    rss_bytes: int | None
    # True when `rss_bytes` is a POSIX peak (`ru_maxrss`, monotonic
    # non-decreasing for the process lifetime), not the current resident size --
    # see `_posix_rss_bytes`. Growth is still a meaningful "did usage ratchet up
    # further during the measured iterations" signal either way, but the two
    # are not the same quantity and must not be reported under an unqualified
    # "RSS" label.
    rss_is_peak: bool
    object_count: int
    traced_bytes: int
    # Exact OS handle/fd count -- unlike the three metrics above, this one is
    # effectively noise-free (an integer syscall result, not bytes subject to
    # allocator/working-set fluctuation): repeated calibration on this project
    # showed RSS swinging +-tens of KB per iteration on Windows with *no*
    # correlation to an actual injected leak, while GetProcessHandleCount /
    # `/proc/self/fd` returned an exact, reproducible delta of 0 for non-leaking
    # code and the exact expected count for a deliberately unclosed handle. This
    # is what actually detects a forgotten-close class of PyO3/Rust-side handle
    # leak (unclosed pipe/process handle) -- the class RSS/tracemalloc/gc proved
    # blind to for a single retained Python-side object (see the R-02 fix-cycle
    # review). `None` when no platform probe is available.
    handle_count: int | None


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("page_fault_count", ctypes.c_ulong),
        ("peak_working_set_size", ctypes.c_size_t),
        ("working_set_size", ctypes.c_size_t),
        ("quota_peak_paged_pool_usage", ctypes.c_size_t),
        ("quota_paged_pool_usage", ctypes.c_size_t),
        ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
        ("quota_non_paged_pool_usage", ctypes.c_size_t),
        ("pagefile_usage", ctypes.c_size_t),
        ("peak_pagefile_usage", ctypes.c_size_t),
    ]


class _ResourceUsage(Protocol):
    ru_maxrss: int


class _ResourceModule(Protocol):
    RUSAGE_SELF: int

    def getrusage(self, who: int, /) -> _ResourceUsage: ...


def _windows_rss_bytes() -> int | None:
    win_dll = cast(Callable[..., ctypes.CDLL], vars(ctypes)["WinDLL"])
    kernel32 = win_dll("kernel32", use_last_error=True)
    psapi = win_dll("psapi", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    get_process_memory_info = psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    get_process_memory_info.restype = ctypes.c_int

    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    succeeded = get_process_memory_info(get_current_process(), ctypes.byref(counters), counters.cb)
    if not succeeded:
        return None
    return int(counters.working_set_size)


def _posix_rss_bytes() -> tuple[int, bool] | None:
    """Returns `(bytes, is_peak)`, or `None` if no probe is available."""
    system = platform.system()
    if system == "Linux":
        try:
            fields = Path("/proc/self/statm").read_text(encoding="ascii").split()
            resident_pages = int(fields[1])
            return resident_pages * mmap.PAGESIZE, False
        except (FileNotFoundError, IndexError, OSError, ValueError):
            return None

    try:
        resource = cast(_ResourceModule, importlib.import_module("resource"))
    except ImportError:
        return None

    # `ru_maxrss` is the process's PEAK resident size since it started, not its
    # current resident size -- monotonic non-decreasing for the process
    # lifetime. It is still a meaningful growth signal (a new high-water mark
    # during the measured iterations means usage genuinely increased further
    # past whatever it reached during warmup), but callers must not report it
    # as plain "RSS" -- see `_MemorySnapshot.rss_is_peak`.
    maximum_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return (maximum_rss if system == "Darwin" else maximum_rss * 1024), True


def _rss_bytes() -> tuple[int, bool] | None:
    # process_info anchors the sample to the live process instance under test.
    # MemberInfo does not currently expose RSS, so a platform probe supplies the
    # resident-byte value without widening processkit's public API.
    from processkit import process_info

    if process_info(os.getpid()) is None:
        return None
    if platform.system() == "Windows":
        windows_rss = _windows_rss_bytes()
        return None if windows_rss is None else (windows_rss, False)
    return _posix_rss_bytes()


def _windows_handle_count() -> int | None:
    win_dll = cast(Callable[..., ctypes.CDLL], vars(ctypes)["WinDLL"])
    kernel32 = win_dll("kernel32", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    get_process_handle_count = kernel32.GetProcessHandleCount
    get_process_handle_count.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    get_process_handle_count.restype = ctypes.c_int

    count = ctypes.c_ulong(0)
    succeeded = get_process_handle_count(get_current_process(), ctypes.byref(count))
    if not succeeded:
        return None
    return int(count.value)


def _posix_handle_count() -> int | None:
    # Both are procfs/fdescfs conventions exposing one entry per open file
    # descriptor for the calling process -- Linux always has `/proc/self/fd`;
    # macOS/*BSD expose the equivalent at `/dev/fd` when `fdescfs` is mounted
    # (the common case). `os.listdir` opens and closes its own directory fd
    # internally, so it does not perturb the count it returns.
    for candidate in ("/proc/self/fd", "/dev/fd"):
        try:
            return len(os.listdir(candidate))
        except OSError:
            continue
    return None


def _handle_count() -> int | None:
    if platform.system() == "Windows":
        return _windows_handle_count()
    return _posix_handle_count()


def _snapshot_memory() -> _MemorySnapshot:
    gc.collect()
    object_count = len(gc.get_objects())
    rss = _rss_bytes()
    handle_count = _handle_count()
    snapshot = tracemalloc.take_snapshot()
    traced_bytes = sum(stat.size for stat in snapshot.statistics("filename"))
    rss_bytes, rss_is_peak = (None, False) if rss is None else (rss[0], rss[1])
    return _MemorySnapshot(rss_bytes, rss_is_peak, object_count, traced_bytes, handle_count)


def _assert_growth_within(
    name: str, baseline: int, final: int, *, per_iteration_budget: int
) -> None:
    # Normalized purely to the iteration count actually run (R-02 fix-cycle
    # review, plan item 1), not a `max(percentage_of_baseline, flat_constant)`
    # blend: empirical calibration on this project showed baseline-relative
    # percentage is the wrong lever for these two metrics -- a 20%-of-baseline
    # allowance was simultaneously way too loose for RSS (a modest baseline in
    # the tens of MB makes 20% many megabytes, dwarfing any realistic small
    # leak) and too tight for tracemalloc bytes (a modest few-KB baseline makes
    # 20% smaller than this suite's own legitimate per-iteration allocation
    # churn, e.g. the streaming-iterators scenario). `per_iteration_budget` is
    # instead picked directly from real measured growth on a real (non-leaking)
    # run of each scenario in this module, with a >=3x safety margin for a
    # noisier CI runner -- see the per-call sites in `_assert_stable_memory`
    # for the specific calibration numbers.
    growth = final - baseline
    allowed = per_iteration_budget * _ITERATIONS
    assert growth <= allowed, (
        f"{name} grew by {growth:,} from {baseline:,} to {final:,} across "
        f"{_ITERATIONS} iterations; allowed {allowed:,} "
        f"({per_iteration_budget:,}/iteration)"
    )


def _assert_stable_memory(baseline: _MemorySnapshot, final: _MemorySnapshot) -> None:
    # A platform probe silently returning `None` must not let this test pass
    # having quietly skipped the metric that class of probe backs -- fail
    # visibly (skip, not a silent pass on the remaining metrics) instead of
    # looking identical to a run where every metric was actually checked.
    if baseline.rss_bytes is None or final.rss_bytes is None:
        pytest.skip("RSS probe unavailable on this platform/process (see _rss_bytes)")
    if baseline.handle_count is None or final.handle_count is None:
        pytest.skip("OS handle/fd-count probe unavailable on this platform (see _handle_count)")

    # Exact-count metric (see `_MemorySnapshot.handle_count`) checked first,
    # deliberately: it is the only metric here with no measurement noise (an
    # integer syscall result, not bytes/counts subject to allocator or GC
    # churn), so it is also the one a synthetic leak -- like the OS-handle
    # canary below -- can reliably trip *first*, before an unrelated Python-
    # side side effect of that same synthetic leak (e.g. the list it appends
    # to) also happens to cross the GC-object-count threshold below.
    if baseline.handle_count is not None and final.handle_count is not None:
        handle_growth = final.handle_count - baseline.handle_count
        # `_HANDLE_GROWTH_TOLERANCE` is a small fixed allowance, not scaled to
        # `_ITERATIONS` like the metrics below -- deliberately: a real
        # forgotten-close leak grows this by ~1-2 handles *per iteration*
        # (dozens over a full run), while calibration (running this module's
        # full test order back to back) observed the count itself occasionally
        # lag by a handful before settling -- e.g. Windows IOCP-backed
        # overlapped I/O completions can finish reclaiming a proactor-loop
        # socket's handle slightly after the Python-level `close()`/gc.collect()
        # that preceded this snapshot. The tolerance stays well above that
        # observed slop while remaining a small fraction of what a genuine
        # sustained per-iteration leak would show (see the canary test below).
        assert handle_growth <= _HANDLE_GROWTH_TOLERANCE, (
            f"OS handle/fd count grew by {handle_growth:,} from {baseline.handle_count:,} "
            f"to {final.handle_count:,} across {_ITERATIONS} iterations (tolerance "
            f"{_HANDLE_GROWTH_TOLERANCE}); a forgotten close()/Drop on a Rust-side pipe "
            f"or process handle leaks roughly one handle per iteration, well above this"
        )

    rss_label = "RSS (peak, not resident -- see rss_is_peak)" if final.rss_is_peak else "RSS"
    # Calibration (this module's actual scenarios, real non-leaking code,
    # Windows, several repeated runs): worst observed growth was
    # command_output's (2 real subprocess round trips/iteration) 152-815 KiB
    # depending on the run -- run-to-run variance on this metric turned out
    # wider than a single calibration sample suggested, so this keeps a wide
    # margin above the *worst* run seen, not just one: 128 KiB/iteration is
    # still ~8x tighter than the old flat 32 MiB absolute.
    _assert_growth_within(
        rss_label, baseline.rss_bytes, final.rss_bytes, per_iteration_budget=128 * _KIB
    )
    # Calibration: worst observed growth was streaming_iterators' 17.8 KiB
    # (two astart()+async-generator-consume round trips/iteration) -- 3
    # KiB/iteration gives that a >=5x margin while staying ~11x tighter than
    # the old flat 1 MiB absolute.
    _assert_growth_within(
        "tracemalloc bytes",
        baseline.traced_bytes,
        final.traced_bytes,
        per_iteration_budget=3 * _KIB,
    )
    # Calibration: worst observed growth was command_output's 7 objects over
    # 30 iterations. This metric cannot see a PyO3-side handle/reference leak
    # at all regardless of threshold (`#[pyclass]` instances are not
    # GC-tracked -- see the handle_count field docstring and the R-02 review),
    # so it stays generous rather than being tuned tight for a signal it
    # structurally cannot detect; it still catches a genuine pure-Python
    # reference-cycle/object-accumulation leak.
    _assert_growth_within(
        "GC-tracked objects", baseline.object_count, final.object_count, per_iteration_budget=5
    )


def _measure_iterations(operation: Callable[[], None]) -> None:
    tracemalloc.start()
    try:
        # Prime tracemalloc's own internal bookkeeping (frame/traceback tables)
        # with a throwaway snapshot *before* the baseline sample. Without this,
        # the one-time allocation cost of the first-ever `take_snapshot()` call
        # in this process is paid for *after* baseline RSS is read (inside the
        # baseline `_snapshot_memory()` call itself) and is then still resident
        # by the time the final RSS is read -- silently eating into the growth
        # budget for a fixed cost that has nothing to do with the operation
        # under test (R-02 fix-cycle finding).
        tracemalloc.take_snapshot()

        for _ in range(_WARMUP_ITERATIONS):
            operation()
        baseline = _snapshot_memory()

        for _ in range(_ITERATIONS):
            operation()
        final = _snapshot_memory()
    finally:
        tracemalloc.stop()

    _assert_stable_memory(baseline, final)


def test_command_output_memory_is_stable() -> None:
    async def async_output() -> None:
        result = await Command(PY, ["-c", "print('async')"]).aoutput()
        assert result.stdout.strip() == "async"

    def operation() -> None:
        result = Command(PY, ["-c", "print('sync')"]).output()
        assert result.stdout.strip() == "sync"
        asyncio.run(async_output())

    _measure_iterations(operation)


def test_result_pickle_memory_is_stable() -> None:
    finished = Command(PY, ["-c", "pass"]).start().finish()

    def operation() -> None:
        runner = ScriptedRunner()
        runner.fallback(Reply.fail(3, "expected"))
        result = runner.output(Command("scripted"))

        try:
            pickle.dumps(result)
        except TypeError:
            # ProcessResult intentionally refuses pickle because hidden command
            # configuration cannot be reconstructed faithfully.
            pass
        else:
            pytest.fail("ProcessResult unexpectedly became picklable")

        payload = pickle.dumps((result.outcome, finished))
        restored_outcome, restored_finished = cast(tuple[object, object], pickle.loads(payload))
        assert restored_outcome == result.outcome
        assert restored_finished == finished

    _measure_iterations(operation)


def test_process_group_teardown_memory_is_stable() -> None:
    def operation() -> None:
        with ProcessGroup() as group:
            process = group.start(Command(PY, ["-c", "pass"]))
            assert process.outcome().exited_zero

    _measure_iterations(operation)


def test_streaming_iterators_memory_is_stable() -> None:
    async def scenario() -> None:
        lines_process = await Command(PY, ["-c", "print('line')"]).astart()
        lines = [line async for line in lines_process.stdout_lines()]
        lines_finished = await lines_process.afinish()
        assert lines == ["line"]
        assert lines_finished.exited_zero

        events_process = await Command(PY, ["-c", "print('event')"]).astart()
        events = [event async for event in events_process.lifecycle_events()]
        events_finished = await events_process.afinish()
        assert events[0].kind == "started"
        assert events[-1].kind == "exited"
        assert events_finished.exited_zero

    def operation() -> None:
        asyncio.run(scenario())

    _measure_iterations(operation)


def test_pty_session_memory_is_stable() -> None:
    def operation() -> None:
        result = Command(PY, ["-c", "print('pty')"]).pty().output()
        assert "pty" in result.stdout

    try:
        operation()
    except Unsupported as exc:
        pytest.skip(f"PTY sessions are unsupported on this platform: {exc}")

    _measure_iterations(operation)


def test_supervisor_scripted_restarts_memory_is_stable() -> None:
    def operation() -> None:
        runner = ScriptedRunner()
        runner.on_sequence(
            ["service"],
            [Reply.fail(1, "first"), Reply.fail(2, "second"), Reply.ok("ready")],
        )
        outcome = Supervisor(
            Command("service"),
            restart="on_crash",
            max_restarts=4,
            backoff_initial=0.001,
            backoff_factor=1.0,
            jitter=False,
            runner=runner,
        ).run()
        assert outcome.restarts == 2
        assert outcome.final_result.stdout == "ready"

    _measure_iterations(operation)


def test_harness_detects_an_injected_os_handle_leak() -> None:
    """Permanent regression guard for the harness itself (R-02 fix-cycle review).

    Proves the OS handle/fd-count check in `_assert_stable_memory` is actually
    wired into the pass/fail contract, using a leak this test fully controls
    (an unclosed `os.pipe()` per iteration) rather than depending on
    processkit's own current, possibly-changing internal behavior.

    This does not use RSS/tracemalloc/gc-object counts for the canary signal:
    empirical calibration during the R-02 fix showed those three swinging by
    tens of KB (RSS) or low hundreds of bytes (tracemalloc) per iteration on a
    real, non-leaking Windows dev box -- the same order of magnitude as the
    exact leak class this module exists to catch (see the comment above
    `_BASE_ITERATIONS`) -- so a canary built on them would itself be flaky.
    OS handle/fd counts are exact integers with no such noise (calibration:
    delta 0 for non-leaking code, exact delta for a real leak), which is
    exactly why `_assert_stable_memory` checks that metric first (see its
    comment) and why it is what this canary exercises.

    If this test ever stops raising, the sensitivity of the handle/fd-count
    detector has regressed (its threshold loosened, or its probe silently
    stopped resolving to a working platform mechanism) -- that regression,
    not a real leak, is what this failure means.
    """
    leaked_pipes: list[tuple[int, int]] = []

    def leaky_operation() -> None:
        leaked_pipes.append(os.pipe())  # deliberately never closed

    try:
        with pytest.raises(AssertionError, match=r"OS handle/fd count grew"):
            _measure_iterations(leaky_operation)
    finally:
        for read_fd, write_fd in leaked_pipes:
            os.close(read_fd)
            os.close(write_fd)
