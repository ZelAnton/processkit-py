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
    from typing import assert_type

    from processkit import (
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

    async def _command_async_verb_return_types(cmd: Command) -> None:
        assert_type(await cmd.aoutput(), ProcessResult)
        assert_type(await cmd.arun(), str)
        assert_type(await cmd.aoutput_bytes(), BytesResult)

    def _batch_return_types(cmds: list[Command]) -> None:
        assert_type(output_all(cmds), list[ProcessResult | ProcessError])
        assert_type(output_all_bytes(cmds), list[BytesResult | ProcessError])
        assert_type(enable_logging(), bool)

    def _pipeline_and_runner_return_types(pipe: Pipeline, runner: Runner, cmd: Command) -> None:
        assert_type(pipe.run(), str)
        assert_type(pipe.output(), ProcessResult)
        assert_type(runner.output(cmd), ProcessResult)

    def _cli_client_return_types(client: CliClient) -> None:
        assert_type(client.run(["x"]), str)
        assert_type(client.exit_code(["x"]), int)

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

    async def _running_process_return_types(proc: RunningProcess) -> None:
        assert_type(await proc.wait(), Outcome)
        assert_type(await proc.finish(), Finished)
        assert_type(await proc.output(), ProcessResult)

    def _result_property_types(r: ProcessResult, b: BytesResult, o: Outcome) -> None:
        assert_type(r.stdout, str)
        assert_type(r.code, int | None)
        assert_type(r.is_success, bool)
        assert_type(r.signal, int | None)
        assert_type(r.combined, str)
        assert_type(b.stdout, bytes)
        assert_type(b.stderr, str)
        assert_type(o.code, int | None)
        assert_type(o.exited_zero, bool)

    def _run_profile_property_types(rp: RunProfile) -> None:
        assert_type(rp.code, int | None)
        assert_type(rp.signal, int | None)
        assert_type(rp.timed_out, bool)
        assert_type(rp.outcome, Outcome)
        assert_type(rp.avg_cpu_cores, float | None)
        assert_type(rp.samples, int)

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
        assert_type(pd.program, str)
        assert_type(otl.max_lines, int | None)
        assert_type(otl.max_bytes, int | None)
        assert_type(otl.total_lines, int)
        assert_type(otl.total_bytes, int)
        assert_type(un.operation, str)
