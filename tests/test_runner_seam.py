"""The runner test seam: `Runner` (real), `ScriptedRunner` (test double), the
`Reply` variants (ok/fail/timeout/signalled/pending/with_stdout/lines), the
`RecordReplayRunner` record/replay cassette runner, the `RecordingRunner` spy
(+ its `Invocation`), and `ProcessRunner` protocol conformance.

Code written against a runner can be exercised with scripted replies — no real
process — while production passes a real `Runner`.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

from processkit import (
    BytesResult,
    Command,
    NonZeroExit,
    ProcessError,
    ProcessRunner,
    Runner,
    Signalled,
    Timeout,
)
from processkit.testing import (
    Invocation,
    RecordingRunner,
    RecordReplayRunner,
    Reply,
    ScriptedRunner,
)

PY = sys.executable


def test_real_runner_runs() -> None:
    runner = Runner()
    assert runner.run(Command(PY, ["-c", "print('via runner')"])) == "via runner"
    assert runner.output(Command(PY, ["-c", "import sys; sys.exit(2)"])).code == 2


def test_scripted_runner_matches_prefix() -> None:
    runner = ScriptedRunner()
    runner.on(["git", "rev-parse"], Reply.ok("abc123"))
    runner.fallback(Reply.fail(127, "command not scripted"))

    result = runner.output(Command("git", ["rev-parse", "HEAD"]))
    assert result.stdout.strip() == "abc123"
    assert result.is_success


def test_scripted_runner_fallback() -> None:
    runner = ScriptedRunner()
    runner.fallback(Reply.fail(1, "nope"))
    result = runner.output(Command("anything"))
    assert result.code == 1
    assert "nope" in result.stderr


def test_scripted_runner_run_raises_on_failure() -> None:
    runner = ScriptedRunner()
    runner.fallback(Reply.fail(3, "boom"))
    with pytest.raises(NonZeroExit):
        runner.run(Command("whatever"))


def test_scripted_runner_streams_lines() -> None:
    runner = ScriptedRunner()
    runner.on(["server"], Reply.lines(["listening", "ready"]))

    async def scenario() -> list[str]:
        proc = runner.start(Command("server"))
        lines = [line.rstrip() async for line in proc.stdout_lines()]
        await proc.wait()
        return lines

    assert asyncio.run(scenario()) == ["listening", "ready"]


def test_dependency_injection_pattern() -> None:
    # Code is written against a runner; tests pass a ScriptedRunner.
    def latest_commit(runner: Runner | ScriptedRunner) -> str:
        return runner.run(Command("git", ["rev-parse", "HEAD"]))

    scripted = ScriptedRunner()
    scripted.on(["git"], Reply.ok("deadbeef"))
    assert latest_commit(scripted) == "deadbeef"


def test_async_runner_dependency_injection() -> None:
    # Async code written against a runner is testable with a ScriptedRunner.
    async def latest_commit(runner: Runner | ScriptedRunner) -> str:
        return await runner.arun(Command("git", ["rev-parse", "HEAD"]))

    async def scenario() -> str:
        scripted = ScriptedRunner()
        scripted.on(["git"], Reply.ok("cafebabe"))
        return await latest_commit(scripted)

    assert asyncio.run(scenario()) == "cafebabe"


def test_real_runner_async() -> None:
    async def scenario() -> str:
        return await Runner().arun(Command(PY, ["-c", "print('async runner')"]))

    assert asyncio.run(scenario()) == "async runner"


def test_runner_probe_reads_exit_code() -> None:
    # `probe` is one of the run verbs the runner macro generates for every runner;
    # exercise it so a mis-wired forwarder (e.g. to exit_code) can't slip through.
    runner = ScriptedRunner()
    runner.on(["ok"], Reply.ok(""))
    runner.on(["bad"], Reply.fail(1, ""))
    assert runner.probe(Command("ok")) is True
    assert runner.probe(Command("bad")) is False


def test_runner_async_verbs_each_route_correctly() -> None:
    # Drive every async verb the runner macro emits — aoutput / aoutput_bytes /
    # aexit_code / aprobe / astart. They all return an awaitable, so a forwarder
    # wired to the wrong helper would still compile and pass stubtest; only calling
    # each one proves the macro routes it to the matching `runner_a*` helper.
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("async"))

    async def scenario() -> None:
        result = await runner.aoutput(Command("x"))
        assert result.stdout == "async"
        assert result.is_success

        raw = await runner.aoutput_bytes(Command("x"))
        assert isinstance(raw, BytesResult)
        assert raw.stdout == b"async"

        assert await runner.aexit_code(Command("x")) == 0
        assert await runner.aprobe(Command("x")) is True

        proc = await runner.astart(Command("x"))
        outcome = await proc.wait()
        assert outcome.exited_zero

    asyncio.run(scenario())


def test_scripted_result_for_mocking() -> None:
    # ScriptedRunner is also a factory for genuine ProcessResult objects to feed
    # to unittest.mock-style fakes.
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("mocked output"))
    fake = runner.output(Command("x"))
    assert fake.stdout == "mocked output"
    assert fake.is_success


def test_reply_timeout() -> None:
    runner = ScriptedRunner()
    runner.fallback(Reply.timeout())
    assert runner.output(Command("x")).timed_out
    with pytest.raises(Timeout):
        runner.run(Command("x"))


def test_reply_signalled() -> None:
    runner = ScriptedRunner()
    runner.fallback(Reply.signalled(15))
    assert runner.output(Command("x")).signal == 15
    with pytest.raises(Signalled):
        runner.run(Command("x"))


def test_reply_with_stdout_on_failure() -> None:
    # with_stdout() attaches stdout to a reply (e.g. a failure that still printed).
    runner = ScriptedRunner()
    runner.fallback(Reply.fail(1, "err").with_stdout("partial output"))
    result = runner.output(Command("x"))
    assert result.code == 1
    assert result.stdout == "partial output"
    assert "err" in result.stderr


def test_reply_pending_never_exits() -> None:
    # Reply.pending() models a run that never ends on its own — only cancellation
    # or a timeout stops it. The documented "prove your orchestration cancels a
    # blocked call" pattern.
    runner = ScriptedRunner()
    runner.fallback(Reply.pending())

    async def scenario() -> None:
        proc = runner.start(Command("server"))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=0.3)

    asyncio.run(scenario())


# --- runner bytes -----------------------------------------------------------


def test_runner_output_bytes() -> None:
    result = Runner().output_bytes(Command(PY, ["-c", "print('rb')"]))
    assert isinstance(result, BytesResult)
    assert result.stdout.strip() == b"rb"


def test_scripted_runner_output_bytes() -> None:
    scripted = ScriptedRunner()
    scripted.on(["git"], Reply.ok("deadbeef"))
    result = scripted.output_bytes(Command("git", ["rev-parse", "HEAD"]))
    assert isinstance(result, BytesResult)
    assert result.stdout == b"deadbeef"


# --- record / replay --------------------------------------------------------


def test_replay_serves_recorded_output_without_respawning(tmp_path: pathlib.Path) -> None:
    cassette = tmp_path / "cassette.json"
    # Record a real run whose output is non-deterministic, then persist it.
    recorder = RecordReplayRunner.record(str(cassette))
    cmd = Command(PY, ["-c", "import random; print(random.random())"])
    first = recorder.run(cmd)
    recorder.save()
    assert cassette.is_file()

    # Replaying the same argv returns the *recorded* value — a real re-spawn would
    # print a new random number, so equality proves nothing was spawned.
    replayer = RecordReplayRunner.replay(str(cassette))
    replayed = replayer.run(Command(PY, ["-c", "import random; print(random.random())"]))
    assert replayed == first


def test_cassette_miss_carries_program(tmp_path: pathlib.Path) -> None:
    cassette = str(tmp_path / "cassette.json")
    rec = RecordReplayRunner.record(cassette)
    rec.run(Command(PY, ["-c", "print('a')"]))
    rec.save()

    rep = RecordReplayRunner.replay(cassette)
    with pytest.raises(ProcessError) as excinfo:
        rep.run(Command(PY, ["-c", "print('DIFFERENT')"]))  # absent from the cassette
    assert getattr(excinfo.value, "program", None), "cassette miss should carry .program"


# --- ProcessRunner protocol conformance -------------------------------------


def _accepts_runner(runner: ProcessRunner) -> None:
    # The annotation is the test: if this type-checks for the calls below, the
    # concrete runners structurally satisfy the protocol.
    assert runner is not None


def test_runner_classes_satisfy_process_runner() -> None:
    _accepts_runner(Runner())  # static conformance (mypy) + runtime use
    _accepts_runner(ScriptedRunner())
    assert isinstance(Runner(), ProcessRunner)
    assert isinstance(ScriptedRunner(), ProcessRunner)


def test_record_replay_runner_satisfies_process_runner(tmp_path: pathlib.Path) -> None:
    rec = RecordReplayRunner.record(str(tmp_path / "c.json"))
    _accepts_runner(rec)  # static (mypy) signature conformance, not just isinstance
    assert isinstance(rec, ProcessRunner)


# --- RecordingRunner spy ----------------------------------------------------


def test_recording_runner_replies_and_records() -> None:
    # `replying` gives a canned reply to every command AND records each call, so a
    # test can assert what its code ran without spawning anything.
    rec = RecordingRunner.replying(Reply.ok("canned"))
    assert rec.run(Command("git", ["rev-parse", "HEAD"])) == "canned"
    assert rec.exit_code(Command("ls", ["-la"])) == 0

    calls = rec.calls()
    assert [c.program for c in calls] == ["git", "ls"]
    assert calls[0].args == ["rev-parse", "HEAD"]
    assert calls[1].has_flag("-la")
    assert not calls[0].has_flag("--nope")


def test_recording_runner_only_call() -> None:
    rec = RecordingRunner.replying(Reply.ok(""))
    rec.run(Command("solo", ["once"]))
    invocation = rec.only_call()
    assert isinstance(invocation, Invocation)
    assert invocation.program == "solo"
    assert invocation.args == ["once"]


def test_recording_runner_only_call_raises_unless_exactly_one() -> None:
    rec = RecordingRunner.replying(Reply.ok(""))
    with pytest.raises(ProcessError):
        rec.only_call()  # zero calls
    rec.run(Command("a"))
    rec.run(Command("b"))
    with pytest.raises(ProcessError):
        rec.only_call()  # two calls


def test_invocation_captures_cwd_env_stdin(tmp_path: pathlib.Path) -> None:
    rec = RecordingRunner.replying(Reply.ok(""))
    command = (
        Command("tool", ["--flag"])
        .cwd(tmp_path)
        .env("LOG", "info")
        .env_remove("DROP")
        .stdin_text("input")
    )
    rec.run(command)
    inv = rec.only_call()
    assert inv.cwd == str(tmp_path)
    assert inv.env == {"LOG": "info", "DROP": None}
    assert inv.has_stdin is True
    # repr is redacted: program + env NAMES are shown, argv values + env VALUES are not.
    text = repr(inv)
    assert "tool" in text  # program shown
    assert "LOG" in text  # env name shown
    assert "--flag" not in text  # argv value hidden
    assert "info" not in text  # env value hidden


def test_recording_runner_async_records() -> None:
    # The async verbs record too (they route through the same recorded path).
    rec = RecordingRunner.replying(Reply.ok("async-canned"))

    async def scenario() -> str:
        return await rec.arun(Command("deploy", ["--now"]))

    assert asyncio.run(scenario()) == "async-canned"
    assert rec.only_call().program == "deploy"


def test_recording_runner_satisfies_process_runner() -> None:
    rec = RecordingRunner.replying(Reply.ok(""))
    _accepts_runner(rec)  # static (mypy) signature conformance, not just isinstance
    assert isinstance(rec, ProcessRunner)
