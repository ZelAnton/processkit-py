"""The runner test seam: `Runner` (real), `ScriptedRunner` (test double), the
`Reply` variants (ok/fail/timeout/signalled/pending/with_stdout/lines), the
`RecordReplayRunner` record/replay cassette runner, and `ProcessRunner` protocol
conformance.

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
    RecordReplayRunner,
    Reply,
    Runner,
    ScriptedRunner,
    Signalled,
    Timeout,
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
    assert isinstance(rec, ProcessRunner)
