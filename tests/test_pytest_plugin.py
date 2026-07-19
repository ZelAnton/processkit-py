"""The `processkit.pytest_plugin` pytest11 plugin: fixture availability, the
record/replay cassette fixture (mode switch + round-trip), and the
`no_real_spawn` guard.

The plugin-behavior tests run an *inner* pytest session via the `pytester`
fixture (enabled in the repo-root `conftest.py`). Because processkit is installed
with its `pytest11` entry point, the plugin autoloads inside those inner sessions
too — no `-p` needed — which is itself part of what the availability tests prove.
The direct unit tests below exercise the pure helpers with no inner session.
"""

from __future__ import annotations

from typing import cast

import pytest

from processkit import pytest_plugin


class _FakeConfig:
    """A minimal `pytest.Config` stand-in for `_is_record_mode`: only its
    `getoption` (the CLI flag) and `getini` (the ini bool) are consulted."""

    def __init__(self, *, cli: bool, ini: bool) -> None:
        self._cli = cli
        self._ini = ini

    def getoption(self, name: str) -> bool:
        return self._cli

    def getini(self, name: str) -> bool:
        return self._ini


def _record_mode(*, cli: bool, ini: bool) -> bool:
    return pytest_plugin._is_record_mode(cast("pytest.Config", _FakeConfig(cli=cli, ini=ini)))


# --- helpers (no inner session) ---------------------------------------------


def test_cassette_name_is_deterministic() -> None:
    nodeid = "tests/test_x.py::test_y[param-1]"
    assert pytest_plugin._cassette_name(nodeid) == pytest_plugin._cassette_name(nodeid)


def test_cassette_name_is_filesystem_safe() -> None:
    name = pytest_plugin._cassette_name("tests/test_x.py::test_y[a/b::c]")
    assert name.endswith(".json")
    # No path separators, node-id `::`, or param brackets survive.
    assert "/" not in name
    assert "\\" not in name
    assert "::" not in name
    assert "[" not in name and "]" not in name
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
    assert set(name) <= allowed


def test_cassette_name_distinguishes_distinct_nodeids() -> None:
    assert pytest_plugin._cassette_name("m.py::t1") != pytest_plugin._cassette_name("m.py::t2")


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("test_y[a/b]", "test_y[a b]"),
        ("test_y[a_b]", "test_y[a/b]"),
        ("test_y[a::b]", "test_y[a/b]"),
    ],
    ids=("slash-versus-space", "underscore-versus-slash", "double-colon-versus-slash"),
)
def test_cassette_name_distinguishes_nodeids_with_the_same_safe_stem(left: str, right: str) -> None:
    assert pytest_plugin._UNSAFE_NAME.sub("_", left).strip("_") == (
        pytest_plugin._UNSAFE_NAME.sub("_", right).strip("_")
    )
    assert pytest_plugin._cassette_name(left) != pytest_plugin._cassette_name(right)


def test_record_mode_cli_flag_wins() -> None:
    # The CLI flag forces record mode regardless of the ini default.
    assert _record_mode(cli=True, ini=False) is True


def test_record_mode_ini_default_is_replay() -> None:
    assert _record_mode(cli=False, ini=False) is False


def test_record_mode_ini_true_records() -> None:
    assert _record_mode(cli=False, ini=True) is True


def test_record_mode_env_overrides_ini(monkeypatch: pytest.MonkeyPatch) -> None:
    # A set env var decides by truthiness, ahead of the ini (but behind the CLI).
    monkeypatch.setenv("PROCESSKIT_RECORD", "0")
    assert _record_mode(cli=False, ini=True) is False
    monkeypatch.setenv("PROCESSKIT_RECORD", "yes")
    assert _record_mode(cli=False, ini=False) is True


def test_record_mode_env_absent_falls_through_to_ini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROCESSKIT_RECORD", raising=False)
    assert _record_mode(cli=False, ini=True) is True


# --- fixture availability (inner session) -----------------------------------


def test_fixtures_are_available_and_are_process_runners(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        from processkit import Command, ProcessRunner
        from processkit.testing import RecordingRunner, ScriptedRunner


        def test_scripted(scripted_runner):
            assert isinstance(scripted_runner, ScriptedRunner)
            assert isinstance(scripted_runner, ProcessRunner)


        def test_recording_default_reply(recording_runner):
            assert isinstance(recording_runner, RecordingRunner)
            assert isinstance(recording_runner, ProcessRunner)
            # Documented default reply: a clean exit 0 with empty stdout.
            assert recording_runner.run(Command("anything")) == ""
            assert recording_runner.only_call().program == "anything"
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=2)


def test_plugin_autoloads_in_a_subprocess_session(pytester: pytest.Pytester) -> None:
    # A real subprocess session discovers the plugin purely through the installed
    # `pytest11` entry point (no `-p`, no conftest) — the strongest autoload proof.
    pytester.makepyfile(
        """
        def test_seam(record_replay_runner, scripted_runner, recording_runner):
            assert record_replay_runner is not None
        """
    )
    result = pytester.runpytest_subprocess("--processkit-record")
    result.assert_outcomes(passed=1)


# --- record/replay cassette fixture (inner session) -------------------------


def test_cassette_records_then_replays_without_respawn(pytester: pytest.Pytester) -> None:
    # A committed cassette dir (ini) makes the file outlive the per-test tmp_path,
    # so the record run and the later replay run share one cassette.
    pytester.makefile(".ini", pytest="[pytest]\nprocesskit_cassette_dir = cassettes\n")
    pytester.makepyfile(
        """
        import pathlib
        import sys

        from processkit import Command

        # Non-deterministic output: if replay returns the *recorded* value, nothing
        # was respawned (a real re-run would print a different random number).
        CMD = Command(sys.executable, ["-c", "import random; print(random.random())"])
        RECORDED = pathlib.Path(__file__).parent / "recorded.txt"


        def test_roundtrip(record_replay_runner):
            out = record_replay_runner.run(CMD)
            if RECORDED.exists():
                assert out == RECORDED.read_text()  # replay: served from the cassette
            else:
                RECORDED.write_text(out)            # record: capture the value
        """
    )
    # First: record mode saves the cassette to the configured dir.
    recorded = pytester.runpytest("--processkit-record")
    recorded.assert_outcomes(passed=1)
    saved = list(pytester.path.glob("cassettes/*.json"))
    assert saved, "record mode should have written a cassette under the configured dir"

    # Then: replay mode (the default) serves it offline — no respawn.
    replayed = pytester.runpytest()
    replayed.assert_outcomes(passed=1)


def test_default_mode_is_replay_so_a_missing_cassette_errors(pytester: pytest.Pytester) -> None:
    # With no switch and a fresh tmp_path cassette dir, the fixture builds a
    # *replay* runner over a nonexistent cassette — a setup error, not a spawn.
    pytester.makepyfile(
        """
        def test_needs_a_cassette(record_replay_runner):
            pass
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(errors=1)


def test_missing_cassette_error_names_path_and_record_switches(
    pytester: pytest.Pytester,
) -> None:
    # The setup failure must be self-service: it names the exact expected
    # cassette path and at least one way to switch into record mode.
    pytester.makepyfile(
        """
        def test_needs_a_cassette(record_replay_runner):
            pass
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(errors=1)
    output = str(result.stdout)
    assert "no cassette found at" in output
    assert "test_needs_a_cassette" in output
    assert ".json" in output
    assert "--processkit-record" in output
    assert "PROCESSKIT_RECORD" in output
    assert "processkit_record" in output


def test_cli_flag_selects_record_mode(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(_RECORDS_A_REAL_RUN)
    result = pytester.runpytest("--processkit-record")
    result.assert_outcomes(passed=1)


def test_env_var_selects_record_mode(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROCESSKIT_RECORD", "1")
    pytester.makepyfile(_RECORDS_A_REAL_RUN)
    result = pytester.runpytest()  # no CLI flag: the env var drives record mode
    result.assert_outcomes(passed=1)


def test_ini_option_selects_record_mode(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PROCESSKIT_RECORD", raising=False)
    pytester.makefile(".ini", pytest="[pytest]\nprocesskit_record = true\n")
    pytester.makepyfile(_RECORDS_A_REAL_RUN)
    result = pytester.runpytest()  # no CLI flag, no env: the ini drives record mode
    result.assert_outcomes(passed=1)


# Inner test that only *passes* in record mode (a real run is captured); in the
# default replay mode the fixture errors on the missing cassette instead.
_RECORDS_A_REAL_RUN = """
    import sys

    from processkit import Command


    def test_records(record_replay_runner):
        out = record_replay_runner.run(Command(sys.executable, ["-c", "print('recorded')"]))
        assert out == "recorded"
    """


# --- the no_real_spawn guard (inner session) --------------------------------


def test_guard_blocks_real_spawn_primitives(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import sys

        import pytest

        from processkit import Command, Runner


        @pytest.mark.no_real_spawn
        def test_command_output_blocked():
            Command(sys.executable, ["-c", "print(1)"]).output()


        @pytest.mark.no_real_spawn
        def test_runner_run_blocked():
            Runner().run(Command(sys.executable, ["-c", "print(1)"]))
        """
    )
    # `--strict-markers` also proves the marker is registered (an unknown marker
    # would error out here instead of running).
    result = pytester.runpytest("--strict-markers")
    result.assert_outcomes(failed=2)
    result.stdout.fnmatch_lines(["*real process spawn blocked*"])


def test_guard_allows_injected_doubles_and_is_inactive_unmarked(
    pytester: pytest.Pytester,
) -> None:
    pytester.makepyfile(
        """
        import sys

        import pytest

        from processkit import Command
        from processkit.testing import Reply


        @pytest.mark.no_real_spawn
        def test_double_still_works(scripted_runner):
            # An injected double is untouched by the guard — no real spawn happens.
            scripted_runner.fallback(Reply.ok("safe"))
            assert scripted_runner.run(Command("anything")) == "safe"


        def test_unmarked_may_spawn():
            # Without the marker the guard is inactive; a real run works normally.
            assert Command(sys.executable, ["-c", "print('hi')"]).run() == "hi"
        """
    )
    result = pytester.runpytest("--strict-markers")
    result.assert_outcomes(passed=2)


def test_guard_is_restored_after_the_marked_test(pytester: pytest.Pytester) -> None:
    # The patched verbs must be undone at teardown, so a later test spawns freely.
    pytester.makepyfile(
        """
        import sys

        import pytest

        from processkit import Command


        @pytest.mark.no_real_spawn
        def test_blocked():
            Command(sys.executable, ["-c", "print(1)"]).output()


        def test_spawn_works_again():
            assert Command(sys.executable, ["-c", "print('ok')"]).run() == "ok"
        """
    )
    result = pytester.runpytest("--strict-markers")
    result.assert_outcomes(failed=1, passed=1)
