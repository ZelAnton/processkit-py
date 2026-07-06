"""Public type aliases, exported so callers can annotate their own wrappers.

`StrPath` is what every program/path argument accepts; `Args` is an argv-like
list/tuple of them — deliberately **not** `Sequence[StrPath]`, since `str`
itself is structurally a `Sequence[str]` (each character is a `str`), so that
spelling would let a bare string slip through everywhere an argv list is
expected — `cmd.args("--flag")` type-checks against `Sequence[str]` but
explodes it into one argument per *character* at runtime. `list`/`tuple`
cover the overwhelming majority of real call sites (literals, and args
collected into a list); wrap another iterable in `list(...)` at the call site
if you hit this. `SignalName` is the set of portable signal names accepted by
`Command.timeout_signal()` / `ProcessGroup.signal()`; `RetryIf` is the set of
named retry-classifier presets accepted by `Command.retry()` / `CliClient`'s
`default_retry_if=`; `LineTerminatorName` is the set of line-framing presets
accepted by `Command.line_terminator()` / `Command.stdout_line_terminator()` /
`Command.stderr_line_terminator()` — `"newline"` (the default, splitting only
on `\n`) or `"carriage_return"` (also splitting on a bare `\r`, for live
carriage-return progress output); the shorthand aliases `"lf"`/`"cr"` are
accepted at runtime too but are deliberately left out of this Literal so the
canonical spelling is what type checkers surface. `Priority` is the set of
named CPU-scheduling presets accepted by `Command.priority()` — a direct
snake_case mirror of the crate's `Priority` enum variants. `ReadableBuffer` is
what `Command.stdin_bytes()` / `ProcessStdin.write()` accept — `bytes` and
every other object PyO3 extracts a byte buffer from via the buffer protocol
(`bytearray`, `memoryview`), not just `bytes` itself. Kept here as the single
runtime+stub source (the compiled module's `.pyi` imports them), so a caller
can `from processkit import (Args, LineTerminatorName, Priority,
ReadableBuffer, RetryIf, SignalName, StrPath)`.
"""

from __future__ import annotations

import os
from typing import Literal

StrPath = str | os.PathLike[str]
Args = list[StrPath] | tuple[StrPath, ...]
SignalName = Literal["term", "kill", "int", "hup", "quit", "usr1", "usr2"]
RetryIf = Literal["transient", "transient_or_timeout"]
LineTerminatorName = Literal["newline", "carriage_return"]
Priority = Literal["idle", "below_normal", "normal", "above_normal", "high"]
ReadableBuffer = bytes | bytearray | memoryview

__all__ = [
    "Args",
    "LineTerminatorName",
    "Priority",
    "ReadableBuffer",
    "RetryIf",
    "SignalName",
    "StrPath",
]
