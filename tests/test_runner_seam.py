"""The runner test seam: `Runner` (real) and `ScriptedRunner` (test double).

Code written against a runner can be exercised with scripted replies — no real
process — while production passes a real `Runner`.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from processkit import Command, NonZeroExit, Reply, Runner, ScriptedRunner

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
