"""processkit — thin Python bindings to the `processkit` Rust crate.

Process containment with a kernel-backed no-orphan guarantee: spawn child
process trees and tear them down whole, with honest results (a non-zero exit is
data, a timeout is captured, a cancellation is an error).

Both a synchronous surface and an asyncio-native one are provided:

- Sync: `Command(...).output()` / `.run()`, `with ProcessGroup() as g:`, and
  `Command(...).start()` for a scoped background child you watch and tear down.
- Async: `await Command(...).aoutput()` / `.arun()` / `.astart()`,
  `async with ProcessGroup() as g:`, and streaming over a `RunningProcess`
  (`async for line in proc.stdout_lines(): ...`, interactive `take_stdin()`).

A `RunningProcess`'s *consuming* verbs (`wait` / `finish` / `output` /
`output_bytes` / `profile` / `shutdown`) are coroutines with no `a` prefix —
they exist for streaming/interactive use and have no synchronous twin to
disambiguate from — so they are awaited whether the handle came from `start()`
or `astart()`. Cancelling an awaited run tears down the whole process tree.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from ._aio import wait_for, wait_for_line, wait_for_port
from ._processkit import (
    BytesResult,
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
    ResourceLimit,
    Runner,
    RunningProcess,
    RunProfile,
    Signalled,
    StdoutLines,
    SupervisionOutcome,
    Supervisor,
    Timeout,
    Unsupported,
    aoutput_all,
    aoutput_all_bytes,
    enable_logging,
    output_all,
    output_all_bytes,
)
from ._runner import ProcessRunner
from ._types import SignalName, StrPath


def __getattr__(name: str) -> str:
    # Lazy `__version__` (PEP 562): `importlib.metadata.version()` scans
    # installed-package metadata, a cost every `import processkit` would
    # otherwise pay even when nothing reads `__version__`. Computed only on
    # first access; nothing caches it since a re-scan is cheap once resolved.
    if name == "__version__":
        try:
            # Distribution name is `processkit-py` (the bare `processkit` is
            # taken on PyPI); the import name stays `processkit`. The metadata
            # lookup keys off the distribution name.
            return version("processkit-py")
        except PackageNotFoundError:  # not installed (e.g. running from a source tree)
            return "unknown"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BytesResult",
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
    "ProcessRunner",
    "ProcessStdin",
    "ResourceLimit",
    "RunProfile",
    "Runner",
    "RunningProcess",
    "SignalName",
    "Signalled",
    "StdoutLines",
    "StrPath",
    "SupervisionOutcome",
    "Supervisor",
    "Timeout",
    "Unsupported",
    "aoutput_all",
    "aoutput_all_bytes",
    "enable_logging",
    "output_all",
    "output_all_bytes",
    "wait_for",
    "wait_for_line",
    "wait_for_port",
]
