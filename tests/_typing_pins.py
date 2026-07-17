"""Static type pins for the public surface.

`assert_type` checks that the load-bearing return / property / exception-attribute
types resolve exactly as the stub promises. These are verified by **mypy** (a CI
gate), not executed: everything lives under `if TYPE_CHECKING`, so at runtime the
module is empty (no subprocess spawned, no `typing.assert_type` import on the 3.10
floor) while mypy still type-checks the whole block.

This closes the one drift class neither the AST guard (tests/test_api_surface.py)
nor `mypy.stubtest` can see — a compiled callable carries no runtime
`__annotations__`, so a wrong *type* (return, property, or exception attribute) in
`_processkit.pyi` would otherwise ship silently. A renamed/retyped value here
fails mypy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio
    import io
    import os
    import pathlib
    from collections.abc import Awaitable, Callable, Coroutine
    from typing import assert_type

    from processkit import (
        Args,
        BytesResult,
        CliClient,
        Command,
        Finished,
        NonZeroExit,
        Outcome,
        OutputTooLarge,
        PermissionDenied,
        Pipeline,
        ProcessError,
        ProcessNotFound,
        ProcessResult,
        ProcessRunner,
        Runner,
        RunningProcess,
        RunProfile,
        Signalled,
        SignalName,
        StrPath,
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
    from processkit.testing import Invocation, RecordingRunner

    def _command_verb_return_types(cmd: Command) -> None:
        assert_type(cmd.output(), ProcessResult)
        assert_type(cmd.run(), str)
        assert_type(cmd.output_bytes(), BytesResult)
        assert_type(cmd.exit_code(), int)
        assert_type(cmd.probe(), bool)
        assert_type(cmd.start(), RunningProcess)

    # The exported aliases are usable as annotations (importable from processkit).
    def _public_aliases(program: StrPath, signal: SignalName) -> None:
        assert_type(Command(program).timeout_signal(signal), Command)

    # `Args` itself is usable as an annotation on a caller's own wrapper
    # (the module docstring's stated purpose for exporting it).
    def _args_alias_usable_as_annotation(program: str, args: Args) -> None:
        assert_type(Command(program, args), Command)
        assert_type(Command(program).args(args), Command)

    # `Args` accepts a variable annotated `list[str]` (the single most common
    # real call site) passed straight through to both the `Command.__init__`
    # and `.args()` sites — `list` is invariant, so this only works because
    # `Args` includes `list[str]` itself rather than relying on
    # `list[StrPath]` to cover it (see `_types.py`'s docstring).
    def _args_alias_accepts_list_str(program: str, str_args: list[str]) -> None:
        assert_type(Command(program, str_args), Command)
        assert_type(Command(program).args(str_args), Command)

    # Same, for a variable annotated `list[os.PathLike[str]]` — the other
    # homogeneous list shape `Args` names explicitly rather than accepting
    # only through `list[StrPath]`'s (non-)invariance.
    def _args_alias_accepts_list_pathlike(
        program: str, pathlike_args: list[os.PathLike[str]]
    ) -> None:
        assert_type(Command(program, pathlike_args), Command)
        assert_type(Command(program).args(pathlike_args), Command)

    # A `tuple[StrPath, ...]` — heterogeneous mixes of `str`/`os.PathLike[str]`
    # allowed, unlike the homogeneous list variants — is still accepted.
    def _args_alias_accepts_mixed_tuple(
        program: str, tuple_args: tuple[str | pathlib.Path, ...]
    ) -> None:
        assert_type(Command(program, tuple_args), Command)
        assert_type(Command(program).args(tuple_args), Command)

    # A bare `str` must still *not* type-check as `Args` — `Args` is
    # deliberately not `Sequence[StrPath]` (a `str` is structurally a
    # `Sequence[str]`), so this must stay flagged by mypy; `warn_unused_ignores`
    # (part of `strict = true`) turns "the ignore below is unnecessary" into a
    # hard mypy failure, so this pin fails loudly if the invariant regresses.
    def _args_alias_rejects_bare_string(program: str, bare: str) -> None:
        Command(program, bare)  # type: ignore[arg-type]
        Command(program).args(bare)  # type: ignore[arg-type]

    # A heterogeneous `list[str | pathlib.Path]` variable (mixed element
    # types, as opposed to a `tuple`) is still rejected — `Args` names
    # concrete homogeneous list element types (`str`, `Path`,
    # `os.PathLike[str]`) rather than the `StrPath` union itself, since a
    # `list[StrPath]` parameter would (by invariance) reject the common
    # `list[str]`/`list[Path]` cases this fix exists for.
    def _args_alias_rejects_heterogeneous_list(
        program: str, mixed_list: list[str | pathlib.Path]
    ) -> None:
        Command(program, mixed_list)  # type: ignore[arg-type]

    # tee builders return a Command (chainable) and take EITHER a StrPath sink
    # (plus the keyword-only `append` flag) OR a Python writer object with a
    # callable `write(str)` — e.g. `io.StringIO`, structurally a `SupportsWrite`.
    def _tee_builder_return_types(cmd: Command, path: StrPath, writer: io.StringIO) -> None:
        assert_type(cmd.stdout_tee(path), Command)
        assert_type(cmd.stderr_tee(path, append=True), Command)
        assert_type(cmd.stdout_tee(writer), Command)
        assert_type(cmd.stderr_tee(writer), Command)

    # per-line handler builders return a Command (chainable) and take a
    # `Callable[[str], None]` callback.
    def _line_handler_builder_return_types(cmd: Command, on_line: Callable[[str], None]) -> None:
        assert_type(cmd.on_stdout_line(on_line), Command)
        assert_type(cmd.on_stderr_line(on_line), Command)

    async def _command_async_verb_return_types(cmd: Command) -> None:
        assert_type(await cmd.aoutput(), ProcessResult)
        assert_type(await cmd.arun(), str)
        assert_type(await cmd.aoutput_bytes(), BytesResult)

    def _a_verb_return_types(
        cmd: Command,
        pipe: Pipeline,
        runner: Runner,
        proc: RunningProcess,
        sup: Supervisor,
        client: CliClient,
    ) -> None:
        assert_type(cmd.aoutput(), Awaitable[ProcessResult])
        assert_type(cmd.aoutput_bytes(), Awaitable[BytesResult])
        assert_type(cmd.arun(), Awaitable[str])
        assert_type(cmd.aexit_code(), Awaitable[int])
        assert_type(cmd.aprobe(), Awaitable[bool])
        assert_type(cmd.astart(), Awaitable[RunningProcess])
        assert_type(pipe.aoutput(), Awaitable[ProcessResult])
        assert_type(runner.aoutput(cmd), Awaitable[ProcessResult])
        assert_type(proc.aoutcome(), Awaitable[Outcome])
        assert_type(proc.afinish(), Awaitable[Finished])
        assert_type(proc.aoutput(), Awaitable[ProcessResult])
        assert_type(sup.arun(), Awaitable[SupervisionOutcome])
        assert_type(client.aoutput(["x"]), Awaitable[ProcessResult])

    def _a_verbs_are_not_coroutines(cmd: Command, loop: asyncio.AbstractEventLoop) -> None:
        # `a`-verbs return the runtime's custom awaitable, not a native coroutine.
        # The ignores are required: strict mypy fails if the contract regresses.
        coro: Coroutine[object, object, ProcessResult] = cmd.aoutput()  # type: ignore[assignment]
        asyncio.run(cmd.aoutput())  # type: ignore[arg-type]
        loop.create_task(cmd.aoutput())  # type: ignore[arg-type]
        assert_type(asyncio.ensure_future(cmd.aoutput()), asyncio.Task[ProcessResult])

    def _batch_return_types(cmds: list[Command]) -> None:
        assert_type(output_all(cmds), list[ProcessResult | ProcessError])
        assert_type(output_all_bytes(cmds), list[BytesResult | ProcessError])
        assert_type(aoutput_all(cmds), Awaitable[list[ProcessResult | ProcessError]])
        assert_type(aoutput_all_bytes(cmds), Awaitable[list[BytesResult | ProcessError]])
        assert_type(enable_logging(), bool)

    def _pipeline_and_runner_return_types(pipe: Pipeline, runner: Runner, cmd: Command) -> None:
        assert_type(pipe.run(), str)
        assert_type(pipe.output(), ProcessResult)
        assert_type(runner.output(cmd), ProcessResult)

    def _cli_client_return_types(client: CliClient) -> None:
        assert_type(client.run(["x"]), str)
        assert_type(client.exit_code(["x"]), int)

    def _cli_client_is_a_process_runner(client: CliClient) -> None:
        runner: ProcessRunner = client
        assert_type(runner, ProcessRunner)

    def _supervisor_return_type(sup: Supervisor) -> None:
        assert_type(sup.run(), SupervisionOutcome)

    def _recording_runner_types(rec: RecordingRunner, inv: Invocation) -> None:
        assert_type(rec.output(Command("x")), ProcessResult)
        assert_type(rec.calls(), list[Invocation])
        assert_type(rec.only_call(), Invocation)
        assert_type(inv.program, str)
        assert_type(inv.args, list[str])
        assert_type(inv.cwd, str | None)
        assert_type(inv.env, dict[str, str | None])
        assert_type(inv.has_stdin, bool)
        assert_type(inv.has_flag("x"), bool)

    def _running_process_sync_return_types(proc: RunningProcess) -> None:
        assert_type(proc.outcome(), Outcome)
        assert_type(proc.finish(), Finished)
        assert_type(proc.output(), ProcessResult)

    async def _running_process_async_return_types(proc: RunningProcess) -> None:
        assert_type(await proc.aoutcome(), Outcome)
        assert_type(await proc.afinish(), Finished)
        assert_type(await proc.aoutput(), ProcessResult)

    def _result_property_types(r: ProcessResult, b: BytesResult, o: Outcome) -> None:
        assert_type(r.stdout, str)
        assert_type(r.code, int | None)
        assert_type(r.is_success, bool)
        assert_type(r.signal, int | None)
        assert_type(r.combined, str)
        assert_type(r.diagnostic, str | None)
        assert_type(r.outcome, Outcome)
        assert_type(b.stdout, bytes)
        assert_type(b.stderr, str)
        assert_type(b.diagnostic, str | None)
        assert_type(b.outcome, Outcome)
        assert_type(o.code, int | None)
        assert_type(o.exited_zero, bool)

    def _run_profile_property_types(rp: RunProfile) -> None:
        assert_type(rp.code, int | None)
        assert_type(rp.signal, int | None)
        assert_type(rp.timed_out, bool)
        assert_type(rp.outcome, Outcome)
        assert_type(rp.avg_cpu_cores, float | None)
        assert_type(rp.samples, int)

    def _finished_property_types(fin: Finished) -> None:
        assert_type(fin.outcome, Outcome)
        assert_type(fin.stderr, str)
        assert_type(fin.code, int | None)
        assert_type(fin.exited_zero, bool)
        assert_type(fin.timed_out, bool)
        assert_type(fin.signal, int | None)

    def _exception_attr_types(
        nz: NonZeroExit,
        to: Timeout,
        sg: Signalled,
        nf: ProcessNotFound,
        pd: PermissionDenied,
        otl: OutputTooLarge,
        un: Unsupported,
    ) -> None:
        assert_type(nz.code, int)
        assert_type(nz.stdout, str)
        assert_type(to.timeout_seconds, float | None)
        assert_type(sg.signal, int | None)
        assert_type(nf.program, str)
        assert_type(pd.program, str | None)
        assert_type(otl.max_lines, int | None)
        assert_type(otl.max_bytes, int | None)
        assert_type(otl.total_lines, int)
        assert_type(otl.total_bytes, int)
        assert_type(un.operation, str)
