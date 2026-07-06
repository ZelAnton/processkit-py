"""The runner test seam: `Runner` (real), `ScriptedRunner` (test double), the
`Reply` variants (ok/fail/timeout/signalled/pending/with_stdout/lines), the
`RecordReplayRunner` record/replay cassette runner, the `RecordingRunner` spy
(+ its `Invocation`), the `DryRunRunner` render-only double, and `ProcessRunner`
protocol conformance.

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
    CliClient,
    Command,
    NonZeroExit,
    ProcessError,
    ProcessNotFound,
    ProcessRunner,
    Runner,
    Signalled,
    Supervisor,
    Timeout,
    Unsupported,
    output_all,
)
from processkit.testing import (
    DryRunRunner,
    Invocation,
    RecordingRunner,
    RecordReplayRunner,
    Reply,
    ScriptedRunner,
)

from .conftest import NO_SUCH_PROGRAM

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
        await proc.aoutcome()
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
        outcome = await proc.aoutcome()
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
    with pytest.raises(Timeout) as excinfo:
        runner.run(Command("x"))
    # Reply.timeout() takes no duration: the deadline is unknown to this
    # scripted run, so timeout_seconds must read None, not a misleading 0.0.
    assert excinfo.value.timeout_seconds is None


def test_reply_signalled() -> None:
    runner = ScriptedRunner()
    runner.fallback(Reply.signalled(15))
    assert runner.output(Command("x")).signal == 15
    with pytest.raises(Signalled):
        runner.run(Command("x"))


def test_reply_signalled_with_no_number_reads_none_not_missing() -> None:
    # Reply.signalled() with no argument models a real Unix signal-kill the
    # kernel didn't report a number for. `.signal` must still be present and
    # read `None` (per the stub's `signal: int | None`), not raise
    # AttributeError — a regression the accessor-based map_err rewrite
    # (map_err's field attachment now driven by Error's accessors rather than
    # a per-variant setattr) could silently reintroduce, since `error.signal()`
    # returns `None` for this exact case too.
    runner = ScriptedRunner()
    runner.fallback(Reply.signalled())
    with pytest.raises(Signalled) as excinfo:
        runner.run(Command("x"))
    assert excinfo.value.signal is None


def test_reply_with_stdout_on_failure() -> None:
    # with_stdout() attaches stdout to a reply (e.g. a failure that still printed).
    runner = ScriptedRunner()
    runner.fallback(Reply.fail(1, "err").with_stdout("partial output"))
    result = runner.output(Command("x"))
    assert result.code == 1
    assert result.stdout == "partial output"
    assert "err" in result.stderr


def test_reply_with_stderr_on_success() -> None:
    # with_stderr() attaches stderr to a reply — including a successful reply,
    # so a scripted success can carry stderr without the `fail(0, ...)`
    # workaround.
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("all good").with_stderr("a warning"))
    result = runner.output(Command("x"))
    assert result.code == 0
    assert result.stdout == "all good"
    assert result.stderr == "a warning"


def test_reply_pending_never_exits() -> None:
    # Reply.pending() models a run that never ends on its own — only cancellation
    # or a timeout stops it. The documented "prove your orchestration cancels a
    # blocked call" pattern. This case has NO Command.timeout attached — it must
    # still park forever, stopped only by an external cancellation/wait_for; see
    # the *_respects_command_timeout_* tests below for the (distinct) case where
    # a Command.timeout IS attached.
    runner = ScriptedRunner()
    runner.fallback(Reply.pending())

    async def scenario() -> None:
        proc = runner.start(Command("server"))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(proc.aoutcome(), timeout=0.3)

    asyncio.run(scenario())


def test_scripted_runner_bulk_verb_respects_command_timeout_on_a_pending_reply() -> None:
    # processkit 2.1.0: ScriptedRunner's bulk verbs (output/run, not just
    # start()) now honor Command.timeout on a Reply.pending() reply — it
    # resolves timed-out at the deadline instead of parking forever, matching
    # the live Runner and the scripted start() path. (test_reply_pending_never_exits
    # above pins the still-supported case: pending with NO timeout parks forever.)
    runner = ScriptedRunner()
    runner.fallback(Reply.pending())

    result = runner.output(Command("x").timeout(0.2))
    assert result.timed_out

    with pytest.raises(Timeout):
        runner.run(Command("x").timeout(0.2))


def test_scripted_runner_async_bulk_verb_respects_command_timeout_on_a_pending_reply() -> None:
    # The async twin of the test above (aoutput, not output).
    runner = ScriptedRunner()
    runner.fallback(Reply.pending())

    async def scenario() -> bool:
        result = await runner.aoutput(Command("x").timeout(0.2))
        return result.timed_out

    assert asyncio.run(asyncio.wait_for(scenario(), timeout=10.0))


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


def test_cassette_records_and_replays_streaming(tmp_path: pathlib.Path) -> None:
    # Since processkit 1.1.0 the cassette runner covers `start` too: recording is
    # capture-whole (the child runs to completion, then the handle replays its
    # lines), and replay serves them through a real streaming `RunningProcess`.
    cassette = tmp_path / "stream.json"
    cmd = Command(PY, ["-c", "import random; print(random.random()); print('done')"])

    async def stream(runner: RecordReplayRunner) -> list[str]:
        proc = runner.start(cmd)
        lines = [line.rstrip() async for line in proc.stdout_lines()]
        await proc.aoutcome()
        return lines

    recorder = RecordReplayRunner.record(str(cassette))
    recorded = asyncio.run(stream(recorder))
    recorder.save()
    assert recorded[-1] == "done"  # the deterministic tail line

    # Replaying the same argv serves the recorded (random) line — a real respawn
    # would print a different number, so equality proves nothing was spawned.
    replayer = RecordReplayRunner.replay(str(cassette))
    assert asyncio.run(stream(replayer)) == recorded


def test_cassette_output_bytes_is_unsupported(tmp_path: pathlib.Path) -> None:
    # A cassette stores lossy-UTF-8 *text*, so it cannot reproduce exact bytes —
    # `output_bytes` through the record/replay runner raises `Unsupported` (1.1.0).
    # Capture bytes from a real or scripted runner instead.
    rec = RecordReplayRunner.record(str(tmp_path / "c.json"))
    with pytest.raises(Unsupported):
        rec.output_bytes(Command(PY, ["-c", "print('x')"]))


def test_recording_runner_output_bytes_proxies_to_the_inner_runner(tmp_path: pathlib.Path) -> None:
    # processkit 2.1.0: RecordingRunner.output_bytes() no longer falls through
    # to the trait's start-based default — it proxies straight to the INNER
    # runner's own output_bytes. Wrap a RecordReplayRunner (whose output_bytes
    # honestly raises Unsupported, per test_cassette_output_bytes_is_unsupported
    # above) and confirm the SAME Unsupported comes through — not a successful,
    # lossily re-encoded result via the start-based default — and that the call
    # still lands in rec.calls() (recorded despite the inner runner's error).
    inner = RecordReplayRunner.record(str(tmp_path / "c.json"))
    rec = RecordingRunner.new(inner)

    with pytest.raises(Unsupported):
        rec.output_bytes(Command(PY, ["-c", "print('x')"]))

    calls = rec.calls()
    assert [c.program for c in calls] == [PY]


def test_cassette_records_and_replays_a_failed_call(tmp_path: pathlib.Path) -> None:
    # processkit 2.1.0: a cassette now records a *failed* call too (previously
    # only successful calls were recordable, and a failed real run replayed as
    # a misleading `CassetteMiss` instead of the real error). Record a genuine
    # spawn failure (a missing program), then replay it and check the SAME
    # typed exception comes back with the SAME structured fields — not a
    # `CassetteMiss` and not a lossy/generic `ProcessError`.
    cassette = tmp_path / "failure.json"

    recorder = RecordReplayRunner.record(str(cassette))
    with pytest.raises(ProcessNotFound) as recorded:
        recorder.run(Command(NO_SUCH_PROGRAM))
    recorder.save()
    assert cassette.is_file()

    replayer = RecordReplayRunner.replay(str(cassette))
    with pytest.raises(ProcessNotFound) as replayed:
        replayer.run(Command(NO_SUCH_PROGRAM))

    assert type(replayed.value) is type(recorded.value)
    assert replayed.value.program == recorded.value.program
    assert NO_SUCH_PROGRAM in replayed.value.program
    assert str(replayed.value) == str(recorded.value)


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


def test_recording_runner_new_wraps_an_arbitrary_scripted_runner() -> None:
    # The general form behind replying(): wrap a ScriptedRunner already
    # configured with its own rules, recording every call made through it —
    # not just a fresh runner replying with one canned Reply.
    scripted = ScriptedRunner()
    scripted.on(["git"], Reply.ok("git-reply"))
    scripted.on(["ls"], Reply.fail(2, "no such dir"))
    rec = RecordingRunner.new(scripted)

    assert rec.run(Command("git", ["status"])) == "git-reply"
    with pytest.raises(NonZeroExit):
        rec.run(Command("ls"))

    calls = rec.calls()
    assert [c.program for c in calls] == ["git", "ls"]


def test_recording_runner_new_wraps_the_real_runner() -> None:
    rec = RecordingRunner.new(Runner())
    assert rec.run(Command(PY, ["-c", "print('real')"])) == "real"
    assert rec.only_call().program == PY


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


def test_invocation_env_is_and_has_env() -> None:
    # env_is()/has_env() answer the *effective* override (last write wins),
    # unlike scanning the raw `env` dict by hand.
    rec = RecordingRunner.replying(Reply.ok(""))
    command = Command("tool").env("LOG", "info").env("LOG", "debug").env_remove("DROP")
    rec.run(command)
    inv = rec.only_call()
    assert inv.env_is("LOG", "debug")
    assert not inv.env_is("LOG", "info")
    assert inv.has_env("LOG")
    assert not inv.has_env("DROP")  # removed, not "set"
    assert not inv.has_env("MISSING")
    # `env` is plain Python dict semantics, not platform env-key rules: a
    # same-case duplicate key collapses to its last value here too (dict
    # construction, not folding) -- only a *differently-cased* Windows
    # duplicate would survive as two separate entries.
    assert inv.env == {"LOG": "debug", "DROP": None}


@pytest.mark.skipif(
    sys.platform != "win32", reason="env-key case-insensitivity is Windows-specific"
)
def test_invocation_env_is_case_insensitive_on_windows() -> None:
    rec = RecordingRunner.replying(Reply.ok(""))
    command = Command("tool").env("Path", "custom")
    rec.run(command)
    inv = rec.only_call()
    assert inv.env_is("PATH", "custom")
    assert inv.has_env("path")


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


# --- ScriptedRunner: miss/precedence/on_sequence (E1.5) ---------------------


def test_scripted_runner_miss_with_no_fallback_raises_plain_process_error() -> None:
    # A miss (no rule matched, no fallback()) must raise a plain ProcessError —
    # NOT ProcessNotFound/FileNotFoundError. The crate reports this as a `Spawn`
    # carrying `io::ErrorKind::NotFound`, which `errors.rs::map_err`'s
    # `is_not_found()` check deliberately excludes (that predicate is true only
    # for a genuine missing *program*, `Error::NotFound`) — pinning this closes
    # the loop on that classification for the one case that could plausibly be
    # confused with it.
    runner = ScriptedRunner()
    with pytest.raises(ProcessError) as excinfo:
        runner.run(Command("unscripted"))
    assert type(excinfo.value) is ProcessError
    assert not isinstance(excinfo.value, ProcessNotFound)
    assert not isinstance(excinfo.value, FileNotFoundError)


def test_scripted_runner_multiple_on_rules_precedence() -> None:
    # Rules are matched in REGISTRATION order (first match wins), not by
    # specificity — a broader rule registered first shadows a narrower one
    # registered after it, per the crate's documented `matched_reply` semantics.
    runner = ScriptedRunner()
    runner.on(["git"], Reply.ok("broad"))
    runner.on(["git", "status"], Reply.ok("narrow"))
    assert runner.run(Command("git", ["status"])) == "broad"

    # Registering the more specific rule first lets it win instead.
    specific_first = ScriptedRunner()
    specific_first.on(["git", "status"], Reply.ok("narrow"))
    specific_first.on(["git"], Reply.ok("broad"))
    assert specific_first.run(Command("git", ["status"])) == "narrow"


def test_scripted_runner_on_sequence_progresses_then_repeats_last() -> None:
    runner = ScriptedRunner()
    runner.on_sequence(["deploy"], [Reply.fail(1, "flaky"), Reply.ok("ok")])
    with pytest.raises(NonZeroExit):
        runner.run(Command("deploy"))
    assert runner.run(Command("deploy")) == "ok"
    # Exhausted: the last reply keeps repeating.
    assert runner.run(Command("deploy")) == "ok"
    assert runner.run(Command("deploy")) == "ok"


def test_scripted_runner_on_sequence_rejects_empty_replies() -> None:
    runner = ScriptedRunner()
    with pytest.raises(ValueError):
        runner.on_sequence(["deploy"], [])


# --- when() / with_line_delay (C7 batch B) -----------------------------------


def test_scripted_runner_when_matches_by_predicate() -> None:
    # when() matches on the whole Command via its own inspection accessors
    # (`program`/`arguments`, from C7 batch A) — not just an argv prefix
    # (`on()`), and not restricted to a simple prefix match at all.
    runner = ScriptedRunner()
    runner.when(lambda cmd: "--dangerous" in cmd.arguments, Reply.ok("sandboxed"))
    runner.fallback(Reply.ok("default"))
    assert runner.run(Command("tool", ["--dangerous"])) == "sandboxed"
    assert runner.run(Command("tool", ["--safe"])) == "default"


def test_scripted_runner_when_predicate_raising_is_treated_as_no_match() -> None:
    # A raising predicate is infallible from the crate's perspective — treated
    # as "does not match" (surfaced via the unraisable hook, not propagated).
    captured: list[BaseException] = []

    def hook(unraisable: object) -> None:
        exc = getattr(unraisable, "exc_value", None)
        if isinstance(exc, BaseException):
            captured.append(exc)

    def boom(cmd: Command) -> bool:
        raise ValueError("predicate exploded")

    runner = ScriptedRunner()
    runner.when(boom, Reply.ok("matched"))
    runner.fallback(Reply.ok("fallback"))

    old_hook = sys.unraisablehook
    sys.unraisablehook = hook
    try:
        assert runner.run(Command("tool")) == "fallback"
    finally:
        sys.unraisablehook = old_hook
    assert captured
    assert isinstance(captured[0], ValueError)


def test_reply_with_line_delay_spaces_out_stdout_lines() -> None:
    import time

    runner = ScriptedRunner()
    runner.on(["server"], Reply.lines(["one", "two", "three"]).with_line_delay(0.1))

    async def scenario() -> tuple[list[str], float]:
        proc = runner.start(Command("server"))
        started = time.monotonic()
        lines = [line.rstrip() async for line in proc.stdout_lines()]
        await proc.aoutcome()
        return lines, time.monotonic() - started

    lines, elapsed = asyncio.run(scenario())
    assert lines == ["one", "two", "three"]
    # 3 lines at 0.1s each is at least ~0.2s of delay (the first line doesn't
    # necessarily wait); a generous lower bound avoids flaking on scheduling
    # jitter while still proving the delay actually happened.
    assert elapsed >= 0.15


# --- DryRunRunner: render-only double (T-022) --------------------------------


def test_dry_run_runner_renders_without_spawning() -> None:
    # Every verb renders the command to its display-quoted line and returns a
    # synthetic success — no process is spawned. `only_command()` exposes the
    # rendered text (like `Command.command_line()`), the whole point of the seam.
    runner = DryRunRunner()
    result = runner.output(Command("rm", ["-rf", "build"]))
    assert result.is_success
    assert result.code == 0
    assert result.stdout == ""  # a dry run has no real output to fake
    assert runner.only_command() == "rm -rf build"


def test_dry_run_runner_success_code_follows_command_success_codes() -> None:
    # The synthetic "success" exit is drawn from the command's own
    # `success_codes` (not a hardcoded 0), so `is_success` and the checking
    # verbs still agree for a command whose accepted set excludes 0.
    runner = DryRunRunner()
    result = runner.output(Command("tool").success_codes([2]))
    assert result.code == 2
    assert result.is_success


def test_dry_run_runner_commands_collects_every_call_in_order() -> None:
    runner = DryRunRunner()
    runner.run(Command("git", ["status"]))
    runner.exit_code(Command("ls", ["-la"]))
    assert runner.commands() == ["git status", "ls -la"]


def test_dry_run_runner_only_command_raises_unless_exactly_one() -> None:
    runner = DryRunRunner()
    with pytest.raises(ProcessError):
        runner.only_command()  # zero calls
    runner.run(Command("a"))
    runner.run(Command("b"))
    with pytest.raises(ProcessError):
        runner.only_command()  # two calls


def test_dry_run_runner_on_invocation_echoes_live_and_still_collects() -> None:
    # `on_invocation(callback)` fires as each call happens (e.g. to print a
    # `--dry-run` echo) IN ADDITION TO the collected `commands()` snapshot.
    echoed: list[str] = []
    runner = DryRunRunner()
    runner.on_invocation(echoed.append)
    runner.run(Command("git", ["push", "--tags"]))
    runner.run(Command("kubectl", ["apply"]))
    assert echoed == ["git push --tags", "kubectl apply"]
    assert runner.commands() == echoed  # both surfaces agree


def test_dry_run_runner_on_invocation_raising_callback_is_swallowed() -> None:
    # The echo is a fire-and-forget side effect: a raising callback is surfaced
    # via the unraisable hook (like `ScriptedRunner.when`'s predicate), never
    # propagated to derail the run it was only observing.
    captured: list[BaseException] = []

    def hook(unraisable: object) -> None:
        exc = getattr(unraisable, "exc_value", None)
        if isinstance(exc, BaseException):
            captured.append(exc)

    def boom(_line: str) -> None:
        raise ValueError("echo exploded")

    runner = DryRunRunner()
    runner.on_invocation(boom)

    old_hook = sys.unraisablehook
    sys.unraisablehook = hook
    try:
        # The run still succeeds despite the broken echo.
        assert runner.output(Command("deploy")).is_success
    finally:
        sys.unraisablehook = old_hook
    assert captured
    assert isinstance(captured[0], ValueError)
    assert runner.only_command() == "deploy"  # still collected


def test_dry_run_runner_async_verbs_render_without_spawning() -> None:
    # The async verbs render and collect too (they route through the same seam).
    runner = DryRunRunner()

    async def scenario() -> None:
        result = await runner.aoutput(Command("terraform", ["apply"]))
        assert result.is_success
        assert await runner.aexit_code(Command("helm", ["upgrade"])) == 0

    asyncio.run(scenario())
    assert runner.commands() == ["terraform apply", "helm upgrade"]


def test_dry_run_runner_satisfies_process_runner() -> None:
    runner = DryRunRunner()
    _accepts_runner(runner)  # static (mypy) signature conformance, not just isinstance
    assert isinstance(runner, ProcessRunner)


# --- DryRunRunner injected at all three injection points (T-022) -------------


def test_output_all_accepts_dry_run_runner() -> None:
    # Driven through the dry-run double, `output_all` renders every command and
    # spawns nothing — the rendered lines prove each command reached the runner.
    runner = DryRunRunner()
    results = output_all([Command("rm", ["-rf", "a"]), Command("rm", ["-rf", "b"])], runner=runner)
    assert all(r.is_success for r in results if not isinstance(r, ProcessError))
    assert runner.commands() == ["rm -rf a", "rm -rf b"]


def test_supervisor_accepts_dry_run_runner() -> None:
    runner = DryRunRunner()
    outcome = Supervisor(Command("deploy", ["--now"]), restart="never", runner=runner).run()
    assert outcome.final_result.is_success
    assert runner.only_command() == "deploy --now"


def test_cli_client_accepts_dry_run_runner() -> None:
    # A `CliClient` wired to the dry-run double renders each built command
    # (program + per-call args) and never spawns; `run()` returns the (empty)
    # synthetic stdout.
    runner = DryRunRunner()
    client = CliClient("kubectl", runner=runner)
    assert client.run(["apply", "-f", "manifest.yaml"]) == ""
    assert runner.only_command() == "kubectl apply -f manifest.yaml"
