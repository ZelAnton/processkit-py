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
import sys
import time
from collections.abc import Callable

_POLL_INTERVAL = 0.05


if sys.platform == "win32":
    # From-imports only (no bare `import ctypes`) to keep a single import style.
    from ctypes import POINTER, WinDLL, byref, wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259

    def is_alive(pid: int) -> bool:
        """Whether the process with this PID is currently running."""
        kernel32 = WinDLL("kernel32", use_last_error=True)
        # Declare signatures explicitly: a HANDLE is pointer-width, so the
        # default `c_int` return type would truncate it on 64-bit Windows.
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            POINTER(wintypes.DWORD),
        ]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

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


def wait_until(predicate: Callable[[], bool], timeout: float) -> bool:
    """Poll ``predicate`` until it is true or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL_INTERVAL)
    return predicate()


def wait_dead(pid: int, timeout: float) -> bool:
    """Wait until the process with this PID is gone (no loop-variable closure)."""
    return wait_until(lambda: not is_alive(pid), timeout)


def read_pid_when_ready(path: os.PathLike[str] | str, timeout: float) -> int:
    """Wait for a PID file written by a child process and return the PID."""
    pid_path = pathlib.Path(path)

    def _ready() -> bool:
        return pid_path.exists() and pid_path.read_text().strip().isdigit()

    if not wait_until(_ready, timeout):
        raise TimeoutError(f"PID file {pid_path} was not written in time")
    return int(pid_path.read_text().strip())
