"""Cross-platform process-liveness helpers for the teardown tests.

The orphan-leak tests assert that a *grandchild* process is dead after a
``ProcessGroup`` tears down. Checking "is PID N alive" portably needs a tiny bit
of per-OS code.

The platform split is on ``sys.platform`` (not ``os.name``) so that a type
checker analyses only the branch for the platform it is run on — the Windows
``ctypes`` calls are invisible to mypy on Linux, and vice versa.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time
from collections.abc import Callable

_POLL_INTERVAL = 0.05


if sys.platform == "win32":
    # From-imports only (no bare `import ctypes`) to keep a single import style.
    from ctypes import POINTER, WinDLL, byref, wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259

    # Built once at import time, not on every `is_alive` call: the DLL handle
    # and signatures never change, and `is_alive` is polled in a tight loop by
    # `wait_until`/`wait_dead`.
    _kernel32 = WinDLL("kernel32", use_last_error=True)
    # Declare signatures explicitly: a HANDLE is pointer-width, so the default
    # `c_int` return type would truncate it on 64-bit Windows.
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        POINTER(wintypes.DWORD),
    ]
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        POINTER(wintypes.FILETIME),
        POINTER(wintypes.FILETIME),
        POINTER(wintypes.FILETIME),
        POINTER(wintypes.FILETIME),
    ]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    def is_alive(pid: int) -> bool:
        """Whether the process with this PID is currently running."""
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not _kernel32.GetExitCodeProcess(handle, byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            _kernel32.CloseHandle(handle)

    def _process_start_key(pid: int) -> object | None:
        """An opaque, per-instance key for whatever process currently owns
        `pid` (its OS-reported creation time), or `None` if it can't be read
        right now. See the module docstring addendum on `wait_dead` for why
        this exists: it is only ever used for *equality* comparisons across
        two live reads of the same `pid`, never parsed as an actual date."""
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            ok = _kernel32.GetProcessTimes(
                handle, byref(creation), byref(exit_time), byref(kernel_time), byref(user_time)
            )
            if not ok:
                return None
            return (creation.dwLowDateTime, creation.dwHighDateTime)
        finally:
            _kernel32.CloseHandle(handle)

else:

    def is_alive(pid: int) -> bool:
        """Whether the process with this PID is currently running."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # The process exists but is owned by another user.
            return True
        return True

    def _process_start_key(pid: int) -> object | None:
        """An opaque, per-instance key for whatever process currently owns
        `pid` (its OS-reported start time), or `None` if it can't be read
        right now. See the module docstring addendum on `wait_dead` for why
        this exists: it is only ever used for *equality* comparisons across
        two live reads of the same `pid`, never parsed as an actual date.

        Shells out to the standard `ps` utility rather than reading `/proc`:
        `/proc/<pid>` exists on Linux but not on macOS, while `ps -o lstart=`
        is available on both, so one code path covers every POSIX target this
        suite runs on.
        """
        try:
            result = subprocess.run(
                ["ps", "-o", "lstart=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        line = result.stdout.strip()
        return line or None


def wait_until(predicate: Callable[[], bool], timeout: float) -> bool:
    """Poll ``predicate`` until it is true or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL_INTERVAL)
    return predicate()


def wait_dead(pid: int, timeout: float) -> bool:
    """Wait until the process with this PID is gone.

    A raw ``is_alive(pid)`` check alone can't tell "the process we've been
    watching is still running" apart from "the OS already recycled this PID
    for a different, unrelated process" -- between one poll and the next, the
    original process can die and the PID get reused before we look again. That
    would make this function busy-wait for the *new* occupant to also exit,
    typically well past `timeout`: a spurious timeout/flake, not a false
    "dead" report (the failure mode leans safe, just noisy).

    To close that gap, this polls a per-instance start-time key
    (`_process_start_key`) alongside the raw liveness check: the key is
    captured on the first poll that observes the PID alive, and every later
    live poll compares its freshly read key against that snapshot. A mismatch
    means the PID's current occupant is not the process this call started
    watching, i.e. the original is provably gone -- reported as dead right
    away instead of spinning to the full timeout. When the start-time key is
    unavailable (`None` on either read, e.g. the platform helper failed), the
    comparison degrades to always-equal, i.e. the original raw-PID-only
    behavior -- no regression, just no added correlation for that poll. The
    baseline key is only captured once a poll observes a real (non-`None`)
    key, so a transient `None` on the first live poll doesn't get "frozen" as
    the permanent baseline -- correlation kicks in as soon as a real key
    becomes available, rather than being disabled for the rest of the wait.
    """
    captured_key: list[object] = []

    def _gone() -> bool:
        if not is_alive(pid):
            return True
        key = _process_start_key(pid)
        if not captured_key:
            if key is not None:
                captured_key.append(key)
            return False
        prior = captured_key[0]
        if key is None or prior is None:
            # A read failed on this poll -- treat the comparison as
            # unavailable rather than as a mismatch, so a transient `ps`
            # hiccup/TOCTOU can't be misread as "PID recycled".
            return False
        return key != prior

    return wait_until(_gone, timeout)


def read_pid_when_ready(path: os.PathLike[str] | str, timeout: float) -> int:
    """Wait for a PID file written by a child process and return the PID."""
    pid_path = pathlib.Path(path)

    def _ready() -> bool:
        return pid_path.exists() and pid_path.read_text().strip().isdigit()

    if not wait_until(_ready, timeout):
        raise TimeoutError(f"PID file {pid_path} was not written in time")
    return int(pid_path.read_text().strip())
