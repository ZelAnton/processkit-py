"""Public type aliases, exported so callers can annotate their own wrappers.

`StrPath` is what every program/path argument accepts; `Args` is an argv-like
list/tuple of them — deliberately **not** `Sequence[StrPath]`, since `str`
itself is structurally a `Sequence[str]` (each character is a `str`), so that
spelling would let a bare string slip through everywhere an argv list is
expected — `cmd.args("--flag")` type-checks against `Sequence[str]` but
explodes it into one argument per *character* at runtime. `list` is
invariant, though, so a plain `Args = list[StrPath] | tuple[StrPath, ...]`
would itself reject the single most common real call site — a variable
annotated `list[str]` (or `list[pathlib.Path]`, or `list[os.PathLike[str]]`)
passed straight through, e.g. `args: list[str] = [...]; cmd.args(args)` — even
though it's exactly the homogeneous case `Args` is meant to welcome. `Args` is
therefore spelled as a union of the concrete homogeneous list shapes
(`list[str]`, `list[Path]`, `list[os.PathLike[str]]`) instead of the single
invariant `list[StrPath]`, so each of those common list annotations is
accepted on its own terms. A *mixed*-element `str`/`os.PathLike[str]` argv
still works, just spelled as a `tuple` rather than a `list` literal — e.g.
`cmd.args((path, "literal"))` — since `list[StrPath]` isn't a member of this
union anymore (adding it back to also cover a mixed-element `[path,
"literal"]` *list* literal reintroduces the invariance trap in a different
guise: mypy's context-sensitive inference for a `[...]` display against a
`Union` stops trying element types once more than one `list[...]` alternative
is present, so it would silently widen the literal to `list[object]` and
*fail* to type-check against any of them). `list`/`tuple` cover the
overwhelming majority of real call sites (literals, and args collected into a
list); wrap another iterable in `list(...)` at the call site if you hit this.
`SignalName` is the
set of portable signal names accepted by
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
ReadableBuffer, RetryIf, SignalName, StrPath)`. `RunnerLike` lives here for a
related but distinct reason: it's a plain (non-`Literal`) union alias over the
five runner pyclasses (`Runner`, `ScriptedRunner`, `RecordReplayRunner`,
`RecordingRunner`, `DryRunRunner`) used only internally by `_processkit.pyi`'s
own signatures (not part of the public `processkit.__all__` surface), and
`mypy.stubtest` requires every name a `.pyi`-only module exposes to also exist
at runtime — a compiled extension's stub (`_processkit.pyi`) has no backing
Python source, so a `TypeAlias` defined directly in it is never present in the
runtime object stubtest introspects. Defining it here instead, importing the
five runner classes from the actual compiled extension module, makes
`RunnerLike` a real runtime name that `_processkit.pyi` imports (`from
._types import RunnerLike`), the same mechanism `StrPath`/`Args` use above —
just without the top-level package re-export, since `RunnerLike` isn't meant
for callers to import directly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Protocol, TypeAlias

from ._processkit import (
    DryRunRunner,
    RecordingRunner,
    RecordReplayRunner,
    Runner,
    ScriptedRunner,
)

StrPath = str | os.PathLike[str]


class SupportsWrite(Protocol):
    """A minimal text sink accepted by `Command.stdout_tee` / `stderr_tee`
    alongside a file path: any object with a callable `write(str)` — an
    `io.StringIO`, `sys.stderr`, a text-mode file, a logger wrapper. The tee
    passes each decoded line (and the trailing `"\\n"`) to `write` as a `str`,
    so a *binary* writer (`io.BytesIO`, a `"wb"` file) is the wrong sink here.
    The return value is ignored (`io.StringIO.write` returns an `int`, a bare
    logger wrapper may return `None`), hence `object`. Lives here — not inline
    in `_processkit.pyi` — because `mypy.stubtest` requires every name the
    compiled module's stub references to exist at runtime, and a compiled
    extension's `.pyi` has no backing runtime source (the same reason
    `RunnerLike` lives here)."""

    def write(self, data: str, /) -> object: ...


Args = list[str] | list[Path] | list[os.PathLike[str]] | tuple[StrPath, ...]
SignalName = Literal["term", "kill", "int", "hup", "quit", "usr1", "usr2"]
RetryIf = Literal["transient", "transient_or_timeout"]
LineTerminatorName = Literal["newline", "carriage_return"]
Priority = Literal["idle", "below_normal", "normal", "above_normal", "high"]
ReadableBuffer = bytes | bytearray | memoryview
# Every runner accepted in place of the real `Runner` (mirrors
# `runner.rs::extract_runner`'s accepted set) — named once so the `runner=`
# call sites and `RecordingRunner.new` in `_processkit.pyi` don't each repeat
# the same five-way union.
RunnerLike: TypeAlias = (
    Runner | ScriptedRunner | RecordReplayRunner | RecordingRunner | DryRunRunner
)

__all__ = [
    "Args",
    "LineTerminatorName",
    "Priority",
    "ReadableBuffer",
    "RetryIf",
    "SignalName",
    "StrPath",
]
