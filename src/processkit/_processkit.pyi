"""Type stubs for the compiled `_processkit` extension module.

mypy cannot see into the PyO3 cdylib, so the public surface is declared here.
Keep this in sync with `src/lib.rs`.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from types import TracebackType

StrPath = str | os.PathLike[str]

class ProcessResult:
    """The captured result of a finished run. A non-zero exit, a timeout, and a
    signal-kill are all reported as data here — never raised by `output()`."""

    @property
    def stdout(self) -> str: ...
    @property
    def stderr(self) -> str: ...
    @property
    def code(self) -> int | None: ...
    @property
    def is_success(self) -> bool: ...
    @property
    def timed_out(self) -> bool: ...
    @property
    def signal(self) -> int | None: ...
    @property
    def program(self) -> str: ...
    @property
    def duration_seconds(self) -> float: ...
    def combined(self) -> str: ...
    def __repr__(self) -> str: ...

class Command:
    """A command builder. Builder methods return a new `Command`."""

    def __init__(self, program: StrPath, args: Sequence[str] | None = ...) -> None: ...
    def arg(self, arg: str) -> Command: ...
    def args(self, args: Sequence[str]) -> Command: ...
    def cwd(self, path: StrPath) -> Command: ...
    def env(self, key: str, value: str) -> Command: ...
    def timeout(self, seconds: float) -> Command: ...
    def output(self) -> ProcessResult: ...
    def run(self) -> str: ...
    def exit_code(self) -> int: ...
    def probe(self) -> bool: ...
    async def aoutput(self) -> ProcessResult: ...
    async def arun(self) -> str: ...
    def __repr__(self) -> str: ...

class RunningProcess:
    """A handle to a process started inside a `ProcessGroup`."""

    @property
    def pid(self) -> int | None: ...
    def __repr__(self) -> str: ...

class ProcessGroup:
    """A kill-on-drop container for a process tree; use as a context manager."""

    def __init__(self) -> None: ...
    def __enter__(self) -> ProcessGroup: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None = ...,
        exc_value: BaseException | None = ...,
        traceback: TracebackType | None = ...,
    ) -> bool: ...
    def start(self, command: Command) -> RunningProcess: ...
    @property
    def mechanism(self) -> str: ...
    def members(self) -> list[int]: ...
    def shutdown(self) -> None: ...
    def __repr__(self) -> str: ...

class ProcessError(Exception):
    """Base class for every error raised by this package."""

class NonZeroExit(ProcessError):
    """`run()` / `exit_code()` got a non-zero exit."""

    program: str
    code: int
    stdout: str
    stderr: str

class Timeout(ProcessError):
    """A run exceeded its configured timeout."""

    program: str
    timeout_seconds: float
    stdout: str
    stderr: str

class Cancelled(ProcessError):
    """A run was cancelled via a cancellation token (Phase 2 surface)."""

    program: str

class Signalled(ProcessError):
    """A run was killed by a signal."""

    program: str
    signal: int | None
    stdout: str
    stderr: str

class ProcessNotFound(ProcessError):
    """The program could not be found / spawned."""

    program: str

class Unsupported(ProcessError):
    """The operation is not supported on this platform."""
