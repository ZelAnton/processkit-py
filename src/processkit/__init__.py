"""processkit — thin Python bindings to the `processkit` Rust crate.

Process containment with a kernel-backed no-orphan guarantee: spawn child
process trees and tear them down whole, with honest results (a non-zero exit is
data, a timeout is captured, a cancellation is an error).

Both a synchronous surface and an asyncio-native one are provided:

- Sync: `Command(...).output()` / `.run()`, `with ProcessGroup() as g:`.
- Async: `await Command(...).aoutput()` / `.arun()` / `.astart()`,
  `async with ProcessGroup() as g:`, and streaming over a `RunningProcess`
  (`async for line in proc.stdout_lines(): ...`, interactive `take_stdin()`).

Cancelling an awaited run tears down the whole process tree.
"""

from __future__ import annotations

from ._processkit import (
    Cancelled,
    Command,
    Finished,
    NonZeroExit,
    Outcome,
    OutputEvent,
    OutputEvents,
    ProcessError,
    ProcessGroup,
    ProcessNotFound,
    ProcessResult,
    ProcessStdin,
    RunningProcess,
    Signalled,
    StdoutLines,
    Timeout,
    Unsupported,
)

__all__ = [
    "Cancelled",
    "Command",
    "Finished",
    "NonZeroExit",
    "Outcome",
    "OutputEvent",
    "OutputEvents",
    "ProcessError",
    "ProcessGroup",
    "ProcessNotFound",
    "ProcessResult",
    "ProcessStdin",
    "RunningProcess",
    "Signalled",
    "StdoutLines",
    "Timeout",
    "Unsupported",
]
