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

from importlib.metadata import PackageNotFoundError, version

from ._aio import wait_for, wait_for_line, wait_for_port
from ._processkit import (
    BytesResult,
    Cancelled,
    CliClient,
    Command,
    Finished,
    NonZeroExit,
    Outcome,
    OutputEvent,
    OutputEvents,
    OutputTooLarge,
    PermissionDenied,
    Pipeline,
    ProcessError,
    ProcessGroup,
    ProcessGroupStats,
    ProcessNotFound,
    ProcessResult,
    ProcessStdin,
    RecordReplayRunner,
    Reply,
    ResourceLimit,
    Runner,
    RunningProcess,
    RunProfile,
    ScriptedRunner,
    Signalled,
    StdoutLines,
    SupervisionOutcome,
    Supervisor,
    Timeout,
    Unsupported,
    aoutput_all,
    aoutput_all_bytes,
    output_all,
    output_all_bytes,
)

try:
    __version__ = version("processkit")
except PackageNotFoundError:  # not installed (e.g. running from a source tree)
    __version__ = "unknown"

__all__ = [
    "BytesResult",
    "Cancelled",
    "CliClient",
    "Command",
    "Finished",
    "NonZeroExit",
    "Outcome",
    "OutputEvent",
    "OutputEvents",
    "OutputTooLarge",
    "PermissionDenied",
    "Pipeline",
    "ProcessError",
    "ProcessGroup",
    "ProcessGroupStats",
    "ProcessNotFound",
    "ProcessResult",
    "ProcessStdin",
    "RecordReplayRunner",
    "Reply",
    "ResourceLimit",
    "RunProfile",
    "Runner",
    "RunningProcess",
    "ScriptedRunner",
    "Signalled",
    "StdoutLines",
    "SupervisionOutcome",
    "Supervisor",
    "Timeout",
    "Unsupported",
    "aoutput_all",
    "aoutput_all_bytes",
    "output_all",
    "output_all_bytes",
    "wait_for",
    "wait_for_line",
    "wait_for_port",
]
