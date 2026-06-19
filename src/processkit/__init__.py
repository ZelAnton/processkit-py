"""processkit — thin Python bindings to the `processkit` Rust crate.

Process containment with a kernel-backed no-orphan guarantee: spawn child
process trees and tear them down whole, with honest results (a non-zero exit is
data, a timeout is captured, a cancellation is an error).

This is Phase 1: a synchronous `Command` builder, a typed `ProcessResult`, and a
`ProcessGroup` context manager, plus a provisional async surface
(`Command.aoutput` / `Command.arun`). The full async surface — streaming,
readiness probes, and `async with ProcessGroup` — lands in later phases.
"""

from __future__ import annotations

from ._processkit import (
    Cancelled,
    Command,
    NonZeroExit,
    ProcessError,
    ProcessGroup,
    ProcessNotFound,
    ProcessResult,
    RunningProcess,
    Signalled,
    Timeout,
    Unsupported,
)

__all__ = [
    "Cancelled",
    "Command",
    "NonZeroExit",
    "ProcessError",
    "ProcessGroup",
    "ProcessNotFound",
    "ProcessResult",
    "RunningProcess",
    "Signalled",
    "Timeout",
    "Unsupported",
]
