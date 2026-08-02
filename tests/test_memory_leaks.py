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

_MIB = 1024 * 1024
_WARMUP_ITERATIONS = 3
_BASE_ITERATIONS = 20


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
    object_count: int
    traced_bytes: int


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


def _posix_rss_bytes() -> int | None:
    system = platform.system()
    if system == "Linux":
        try:
            fields = Path("/proc/self/statm").read_text(encoding="ascii").split()
            resident_pages = int(fields[1])
            return resident_pages * mmap.PAGESIZE
        except (FileNotFoundError, IndexError, OSError, ValueError):
            return None

    try:
        resource = cast(_ResourceModule, importlib.import_module("resource"))
    except ImportError:
        return None

    maximum_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return maximum_rss if system == "Darwin" else maximum_rss * 1024


def _rss_bytes() -> int | None:
    # process_info anchors the sample to the live process instance under test.
    # MemberInfo does not currently expose RSS, so a platform probe supplies the
    # resident-byte value without widening processkit's public API.
    from processkit import process_info

    if process_info(os.getpid()) is None:
        return None
    if platform.system() == "Windows":
        return _windows_rss_bytes()
    return _posix_rss_bytes()


def _snapshot_memory() -> _MemorySnapshot:
    gc.collect()
    object_count = len(gc.get_objects())
    rss_bytes = _rss_bytes()
    snapshot = tracemalloc.take_snapshot()
    traced_bytes = sum(stat.size for stat in snapshot.statistics("filename"))
    return _MemorySnapshot(rss_bytes, object_count, traced_bytes)


def _assert_growth_within(
    name: str,
    baseline: int,
    final: int,
    *,
    percentage: float,
    absolute: int,
) -> None:
    growth = final - baseline
    allowed = max(absolute, round(baseline * percentage / 100.0))
    assert growth <= allowed, (
        f"{name} grew by {growth:,} from {baseline:,} to {final:,}; "
        f"allowed {allowed:,} ({percentage:.0f}% or {absolute:,}, whichever is larger)"
    )


def _assert_stable_memory(baseline: _MemorySnapshot, final: _MemorySnapshot) -> None:
    if baseline.rss_bytes is not None and final.rss_bytes is not None:
        _assert_growth_within(
            "RSS",
            baseline.rss_bytes,
            final.rss_bytes,
            percentage=20.0,
            absolute=32 * _MIB,
        )
    _assert_growth_within(
        "tracemalloc bytes",
        baseline.traced_bytes,
        final.traced_bytes,
        percentage=20.0,
        absolute=1 * _MIB,
    )
    _assert_growth_within(
        "GC-tracked objects",
        baseline.object_count,
        final.object_count,
        percentage=2.0,
        absolute=500,
    )


def _measure_iterations(operation: Callable[[], None]) -> None:
    tracemalloc.start()
    try:
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
