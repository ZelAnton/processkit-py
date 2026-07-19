"""The runner protocols — the typed seam for dependency injection.

Write code that takes a runner against `ProcessRunner` or `StreamingRunner`,
and it accepts the real `Runner`, a `ScriptedRunner`, a replaying
`RecordReplayRunner`, a recording `RecordingRunner`, or any custom double with
the matching verbs — all checked by the type checker.

`ProcessRunner` is the capture/check verb surface (`output`/`output_bytes`/
`run`/`exit_code`/`probe`, plus their `a`-prefixed async twins) — annotate with it when your code
only ever materializes a result and never streams. `StreamingRunner` extends it
with `start`/`astart`, for code that also needs a live `RunningProcess` handle.
Every built-in runner satisfies `StreamingRunner` (the narrower `ProcessRunner`
is a strict subset, so it's satisfied too) — the split exists so a custom
double, or an annotation on your own injection point, can commit to only the
capabilities it actually needs, instead of the full 12-verb surface either way.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ._processkit import BytesResult, Command, ProcessResult, RunningProcess

__all__ = ["ProcessRunner", "StreamingRunner"]


@runtime_checkable
class ProcessRunner(Protocol):
    """The capture/check run verbs as a structural type: `output`/`output_bytes`/
    `run`/`exit_code`/`probe` and their `a`-prefixed async twins — no streaming.

    Every built-in runner satisfies this (and the wider `StreamingRunner`).
    Prefer this narrower protocol when your own code only calls these verbs —
    a hand-rolled double then only needs to implement five verbs (times two
    for the async twins), not the full runner surface.
    `CliClient` also satisfies `ProcessRunner`: each capture/check verb accepts
    either per-call `Args` (which it combines with its bound program) or a
    `Command` (whose explicit settings win over client defaults). It is not a
    `StreamingRunner`, because it has no `start`/`astart` verbs.
    """

    # `command` is positional-only (`/`) here: it is what every conforming
    # implementation actually accepts by *position* (see e.g. `ProcessGroup`/
    # `Runner` in `_processkit.pyi`), while `CliClient` — also intended to
    # satisfy this protocol (see `_cli_client_is_a_process_runner` in
    # `tests/_typing_pins.py`) — genuinely names its own parameter `call`
    # (it accepts `Args | Command`, not just `Command`), not `command`.
    # Without `/`, that parameter-name mismatch is a real mypy/pyright
    # divergence for protocol structural matching: mypy accepts it, pyright
    # rejects it (reportAssignmentType). Marking the protocol's parameter
    # positional-only removes the name from the structural contract entirely
    # (correctly — no caller of this protocol may pass it by keyword), which
    # satisfies both type checkers instead of suppressing one.
    def output(self, command: Command, /) -> ProcessResult: ...
    def output_bytes(self, command: Command, /) -> BytesResult: ...
    def run(self, command: Command, /) -> str: ...
    def exit_code(self, command: Command, /) -> int: ...
    def probe(self, command: Command, /) -> bool: ...
    def aoutput(self, command: Command, /) -> Awaitable[ProcessResult]: ...
    def aoutput_bytes(self, command: Command, /) -> Awaitable[BytesResult]: ...
    def arun(self, command: Command, /) -> Awaitable[str]: ...
    def aexit_code(self, command: Command, /) -> Awaitable[int]: ...
    def aprobe(self, command: Command, /) -> Awaitable[bool]: ...


@runtime_checkable
class StreamingRunner(ProcessRunner, Protocol):
    """`ProcessRunner` plus `start`/`astart` — the full runner verb surface,
    for code that also needs a live `RunningProcess` handle to stream.

    `Runner`, `ScriptedRunner`, `RecordReplayRunner`, and `RecordingRunner` all
    satisfy it. A hand-rolled double can implement the capture/check verbs
    easily, but `start`/`astart` must return a `RunningProcess`, which has no
    public constructor — and the built-in runners are `@final`, so a
    fully-conforming custom runner in practice means *wrapping* one
    (delegating `start`/`astart` to it; use `ScriptedRunner` for streaming
    doubles).
    """

    def start(self, command: Command, /) -> RunningProcess: ...
    def astart(self, command: Command, /) -> Awaitable[RunningProcess]: ...
