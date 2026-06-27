"""The `ProcessRunner` protocol — the typed seam for dependency injection.

Write code that takes a runner against this protocol, and it accepts the real
`Runner`, a `ScriptedRunner`, a replaying `RecordReplayRunner`, or any custom
double with the same verbs — all checked by the type checker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ._processkit import BytesResult, Command, ProcessResult, RunningProcess

__all__ = ["ProcessRunner"]


@runtime_checkable
class ProcessRunner(Protocol):
    """The runner verb surface as a structural type.

    `Runner`, `ScriptedRunner`, and `RecordReplayRunner` all satisfy it — annotate
    an injected runner as `ProcessRunner` so your code accepts any of them. A
    hand-rolled double can implement the capture/check verbs (`output`/`run`/…)
    easily, but `start`/`astart` must return a `RunningProcess`, which has no public
    constructor — and the built-in runners are `@final`, so a fully-conforming custom
    runner in practice means *wrapping* one (delegating `start`/`astart` to it; use
    `ScriptedRunner` for streaming doubles).
    (`CliClient` is *not* a `ProcessRunner` — its verbs take per-call args, not a
    `Command`, and it has no `start`/`astart`.)
    """

    def output(self, command: Command) -> ProcessResult: ...
    def output_bytes(self, command: Command) -> BytesResult: ...
    def run(self, command: Command) -> str: ...
    def exit_code(self, command: Command) -> int: ...
    def probe(self, command: Command) -> bool: ...
    def start(self, command: Command) -> RunningProcess: ...
    async def aoutput(self, command: Command) -> ProcessResult: ...
    async def aoutput_bytes(self, command: Command) -> BytesResult: ...
    async def arun(self, command: Command) -> str: ...
    async def aexit_code(self, command: Command) -> int: ...
    async def aprobe(self, command: Command) -> bool: ...
    async def astart(self, command: Command) -> RunningProcess: ...
