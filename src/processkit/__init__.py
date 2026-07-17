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

A `RunningProcess`'s *consuming* verbs each come in a sync/async pair, like
everywhere else in this library: `outcome`/`aoutcome` (named to dodge the
reserved word `await`), `finish`/`afinish`, `output`/`aoutput`,
`output_bytes`/`aoutput_bytes`, `profile`/`aprofile`, and
`shutdown`/`ashutdown` (matching `ProcessGroup.shutdown`/`ashutdown`) — use
whichever matches your code, regardless of whether the handle came from
`start()` or `astart()`. Cancelling an awaited run tears down the whole
process tree.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from threading import Lock

from ._aio import WaitTimeout, sample_stats, wait_for_line, wait_for_path, wait_for_port, wait_until
from ._processkit import (
    BytesResult,
    CancellationToken,
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
    which,
)
from ._protocols import ProcessRunner, StreamingRunner
from ._types import (
    Args,
    LineTerminatorName,
    Priority,
    ReadableBuffer,
    RetryIf,
    SignalName,
    StrPath,
)

_VERSION_LOCK = Lock()


def __getattr__(name: str) -> str:
    # Lazy `__version__` (PEP 562): `importlib.metadata.version()` scans
    # installed-package metadata, a cost every `import processkit` would
    # otherwise pay even when nothing reads `__version__`. The lock makes the
    # first lookup single-flight on free-threaded builds; publishing the result
    # in the module globals makes every later read an ordinary attribute lookup.
    if name == "__version__":
        with _VERSION_LOCK:
            # Another thread may have populated the module while this one was
            # waiting for the lock after its initial attribute miss.
            cached = globals().get("__version__")
            if isinstance(cached, str):
                return cached
            try:
                # Distribution name is `processkit-py` (the bare `processkit` is
                # taken on PyPI); the import name stays `processkit`. The metadata
                # lookup keys off the distribution name.
                resolved = version("processkit-py")
            except PackageNotFoundError:  # not installed (e.g. running from a source tree)
                resolved = "unknown"
            globals()["__version__"] = resolved
            return resolved
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Args",
    "BytesResult",
    "CancellationToken",
    "Cancelled",
    "CliClient",
    "Command",
    "Finished",
    "LineTerminatorName",
    "NonZeroExit",
    "Outcome",
    "OutputEvent",
    "OutputEvents",
    "OutputTooLarge",
    "PermissionDenied",
    "Pipeline",
    "Priority",
    "ProcessError",
    "ProcessGroup",
    "ProcessGroupStats",
    "ProcessNotFound",
    "ProcessResult",
    "ProcessRunner",
    "ProcessStdin",
    "ReadableBuffer",
    "ResourceLimit",
    "RetryIf",
    "RunProfile",
    "Runner",
    "RunningProcess",
    "SignalName",
    "Signalled",
    "StdoutLines",
    "StrPath",
    "StreamingRunner",
    "SupervisionOutcome",
    "Supervisor",
    "Timeout",
    "Unsupported",
    "WaitTimeout",
    "aoutput_all",
    "aoutput_all_bytes",
    "enable_logging",
    "output_all",
    "output_all_bytes",
    "sample_stats",
    "wait_for_line",
    "wait_for_path",
    "wait_for_port",
    "wait_until",
    "which",
]
