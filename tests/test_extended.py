"""Tests for the extended (1.1) surface: Command knobs, batch, profiling,
encoding, CliClient, record/replay, and runner/RunningProcess bytes."""

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
    ProcessResult,
    RecordReplayRunner,
    Reply,
    Runner,
    RunProfile,
    ScriptedRunner,
    Unsupported,
    aoutput_all,
    aoutput_all_bytes,
    output_all,
    output_all_bytes,
)

PY = sys.executable

NO_SUCH = "processkit-no-such-binary-xyzzy"


# --- Command knobs ----------------------------------------------------------


def test_success_codes_replaces_success_set() -> None:
    # success_codes replaces the default {0}: [0, 3] accepts both.
    assert Command(PY, ["-c", "import sys; sys.exit(3)"]).success_codes([0, 3]).output().is_success
    assert Command(PY, ["-c", "print(1)"]).success_codes([0, 3]).run() == "1"
    # [3] alone makes exit 0 a failure.
    with pytest.raises(NonZeroExit):
        Command(PY, ["-c", "print(1)"]).success_codes([3]).run()
    # An empty sequence is rejected (it would accept nothing).
    with pytest.raises(ValueError):
        Command(PY, ["-c", "print(1)"]).success_codes([])


def test_encoding_decodes_non_utf8() -> None:
    # 0xe9 is 'é' in latin-1 but invalid UTF-8.
    code = "import sys; sys.stdout.buffer.write(b'\\xe9\\n')"
    assert Command(PY, ["-c", code]).encoding("iso-8859-1").run() == "é"


def test_encoding_rejects_unknown_label() -> None:
    with pytest.raises(ValueError):
        Command(PY, ["-c", "pass"]).encoding("not-a-real-encoding")


def test_stdout_null_rejects_capture_verbs() -> None:
    # null/inherit are non-capturing: the one-shot capture verbs error clearly
    # rather than silently returning empty output.
    with pytest.raises(ProcessError):
        Command(PY, ["-c", "print('hidden')"]).stdout("null").output()


def test_stdout_null_works_with_start_then_wait() -> None:
    async def scenario() -> int | None:
        proc = await Command(PY, ["-c", "print('hidden')"]).stdout("null").astart()
        return (await proc.wait()).code

    assert asyncio.run(scenario()) == 0


def test_stdout_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        # An invalid mode is the point of the test; mypy would flag the literal.
        Command(PY, ["-c", "pass"]).stdout("bogus")  # type: ignore[arg-type]


def test_builder_knobs_chain_builds() -> None:
    # Every lifetime / redirect / privilege knob builds into a valid Command.
    cmd = (
        Command(PY, ["-c", "print('ok')"])
        .kill_on_parent_death()
        .create_no_window()
        .timeout_grace(0.5)
        .timeout_signal("term")
        .uid(0)
        .gid(0)
        .groups([0])
        .setsid()
    )
    assert isinstance(cmd, Command)
    # The cross-platform lifetime knobs actually run.
    assert "ok" in Command(PY, ["-c", "print('ok')"]).kill_on_parent_death().run()


@pytest.mark.skipif(
    sys.platform != "win32", reason="privilege-drop behavior is POSIX-specific / root-dependent"
)
def test_privilege_drop_unsupported_on_windows() -> None:
    # Privilege drops are never silently skipped: on Windows the run raises.
    with pytest.raises(Unsupported) as excinfo:
        Command(PY, ["-c", "print('x')"]).uid(0).run()
    # The structured `.operation` field names what wasn't supported.
    assert excinfo.value.operation


def test_inherit_env_filters_to_allowlist() -> None:
    import os

    os.environ["PK_KEEP"] = "kept"
    os.environ["PK_DROP"] = "dropped"
    try:
        code = "import os; print(os.environ.get('PK_KEEP', '-'), os.environ.get('PK_DROP', '-'))"
        cmd = Command(PY, ["-c", code]).env_clear().inherit_env(["PK_KEEP"])
        if sys.platform == "win32":
            cmd = cmd.env("SYSTEMROOT", os.environ.get("SYSTEMROOT", r"C:\Windows"))
        assert cmd.run() == "kept -"
    finally:
        del os.environ["PK_KEEP"]
        del os.environ["PK_DROP"]


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM trapping is POSIX-specific")
def test_timeout_grace_delivers_signal_before_kill(tmp_path: pathlib.Path) -> None:
    # On timeout the configured signal is sent and the grace window is honored: a
    # child that traps SIGTERM runs its handler before any hard kill.
    marker = tmp_path / "got_term"
    code = (
        "import signal, sys, time\n"
        "def handler(*_):\n"
        f"    open({str(marker)!r}, 'w').write('x')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, handler)\n"
        "time.sleep(30)\n"
    )
    Command(PY, ["-c", code]).timeout(0.3).timeout_signal("term").timeout_grace(3.0).output()
    assert marker.is_file()  # the child received SIGTERM and ran its handler


# --- RunningProcess live introspection + profile ----------------------------


def test_running_process_live_getters() -> None:
    async def scenario() -> None:
        async with await Command(PY, ["-c", "import time; time.sleep(5)"]).astart() as proc:
            assert proc.pid is not None
            assert proc.owns_group is True  # standalone astart owns a private tree
            assert (proc.elapsed_seconds or 0.0) >= 0.0
            # No output captured yet — 0, or None if the counter isn't initialized.
            assert proc.stdout_line_count in (0, None)

    asyncio.run(scenario())


def test_profile_returns_runprofile() -> None:
    async def scenario() -> RunProfile:
        proc = await Command(PY, ["-c", "import time; time.sleep(0.1)"]).astart()
        return await proc.profile(0.02)

    rp = asyncio.run(scenario())
    assert isinstance(rp, RunProfile)
    assert rp.code == 0
    assert rp.duration_seconds >= 0.0
    assert rp.samples >= 1


def test_running_process_output_bytes() -> None:
    async def scenario() -> BytesResult:
        code = "import sys; sys.stdout.buffer.write(bytes([1, 2, 255]))"
        proc = await Command(PY, ["-c", code]).astart()
        return await proc.output_bytes()

    result = asyncio.run(scenario())
    assert result.stdout == bytes([1, 2, 255])


# --- batch ------------------------------------------------------------------


def test_output_all_returns_results_in_order() -> None:
    results = output_all(
        [Command(PY, ["-c", "print(1)"]), Command(PY, ["-c", "print(2)"])],
        concurrency=2,
    )
    assert all(isinstance(r, ProcessResult) for r in results)
    assert [r.stdout.strip() for r in results if isinstance(r, ProcessResult)] == ["1", "2"]


def test_output_all_puts_spawn_failure_in_its_slot() -> None:
    results = output_all([Command(PY, ["-c", "print(1)"]), Command(NO_SUCH)])
    ok, failed = results[0], results[1]
    assert isinstance(ok, ProcessResult)
    assert ok.stdout.strip() == "1"
    assert isinstance(failed, ProcessNotFound)
    assert isinstance(failed, ProcessError)


def test_output_all_bytes() -> None:
    code = "import sys; sys.stdout.buffer.write(b'\\x00\\x01')"
    results = output_all_bytes([Command(PY, ["-c", code])])
    first = results[0]
    assert isinstance(first, BytesResult)
    assert first.stdout == b"\x00\x01"


def test_aoutput_all() -> None:
    async def scenario() -> list[ProcessResult | ProcessError]:
        return await aoutput_all([Command(PY, ["-c", "print(9)"])])

    results = asyncio.run(scenario())
    first = results[0]
    assert isinstance(first, ProcessResult)
    assert first.stdout.strip() == "9"


def test_aoutput_all_bytes() -> None:
    async def scenario() -> list[BytesResult | ProcessError]:
        code = "import sys; sys.stdout.buffer.write(b'\\x02\\x03')"
        return await aoutput_all_bytes([Command(PY, ["-c", code])])

    results = asyncio.run(scenario())
    first = results[0]
    assert isinstance(first, BytesResult)
    assert first.stdout == b"\x02\x03"


# --- CliClient --------------------------------------------------------------


def test_cli_client_run_and_defaults() -> None:
    client = CliClient(PY, default_env={"PK_CLI": "yes"})
    assert client.run(["-c", "print('cli-ok')"]) == "cli-ok"
    assert client.run(["-c", "import os; print(os.environ['PK_CLI'])"]) == "yes"
    assert client.exit_code(["-c", "import sys; sys.exit(2)"]) == 2
    assert client.probe(["-c", "import sys; sys.exit(0)"]) is True


def test_cli_client_async() -> None:
    async def scenario() -> str:
        return await CliClient(PY).arun(["-c", "print('async-cli')"])

    assert asyncio.run(scenario()) == "async-cli"


def test_cli_client_remaining_verbs() -> None:
    # Cover the CliClient verbs not exercised above: output_bytes + the async
    # capture/predicate twins.
    client = CliClient(PY)
    raw = client.output_bytes(["-c", "import sys; sys.stdout.buffer.write(b'\\x00\\x01')"])
    assert raw.stdout == b"\x00\x01"

    async def scenario() -> None:
        assert (await client.aoutput(["-c", "print('a')"])).stdout.strip() == "a"
        assert (await client.aoutput_bytes(["-c", "print('b')"])).stdout.strip() == b"b"
        assert await client.aexit_code(["-c", "import sys; sys.exit(4)"]) == 4
        assert await client.aprobe(["-c", "pass"]) is True

    asyncio.run(scenario())


def test_cli_client_default_timeout_applies() -> None:
    client = CliClient(PY, default_timeout=0.2)
    result = client.output(["-c", "import time; time.sleep(5)"])
    assert result.timed_out


def test_cli_client_default_env_remove() -> None:
    import os

    os.environ["PK_CLI_RM"] = "present"
    try:
        client = CliClient(PY, default_env_remove=["PK_CLI_RM"])
        out = client.run(["-c", "import os; print(os.environ.get('PK_CLI_RM', 'GONE'))"])
        assert out == "GONE"
    finally:
        del os.environ["PK_CLI_RM"]


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


# --- RecordReplayRunner -----------------------------------------------------


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
