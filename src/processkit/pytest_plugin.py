"""processkit.pytest_plugin — pytest fixtures for the processkit testing seam.

Autoloaded in every pytest session where **processkit** is installed, via the
``pytest11`` entry point declared in ``pyproject.toml`` (``[project.entry-points.
pytest11]``) — there is nothing to wire into ``conftest.py``. The module is
import-safe (only cheap imports at module scope, no side effects or spawns), so
being autoloaded costs nothing until a fixture or the guard is actually used.

The fixtures return the ``processkit.testing`` doubles ready to inject, so a test
spawns no real process — each satisfies the ``processkit.ProcessRunner`` protocol,
the seam your code is written against:

- ``scripted_runner`` — a fresh :class:`~processkit.testing.ScriptedRunner`; teach
  it canned replies with ``.on()`` / ``.fallback()`` / ``.when()``.
- ``recording_runner`` — a :class:`~processkit.testing.RecordingRunner` spy that
  replies ``Reply.ok("")`` (a clean exit 0 with empty stdout — the neutral
  default) to every call and records each one for later assertions.
- ``record_replay_runner`` — a :class:`~processkit.testing.RecordReplayRunner`
  bound to a per-test cassette, in *replay* mode by default and *record* mode when
  recording is switched on (see below).

Record/replay mode is chosen the way vcr-like tools do it — a switch, off
(replay) by default so CI never spawns by accident. In precedence order:

- ``--processkit-record`` (CLI flag) forces record mode; otherwise
- the ``PROCESSKIT_RECORD`` environment variable, when set, decides by its
  truthiness (``1``/``true``/``yes``/``on`` → record); otherwise
- the ``processkit_record`` ini option (a bool) decides; defaulting to replay.

The cassette file lives under the test's ``tmp_path`` by default, or under the
``processkit_cassette_dir`` ini directory when set (a relative path resolves
against the rootdir) — point that at a committed fixtures directory to keep
cassettes. Its file name is derived deterministically from the test's node id. In
record mode the cassette is captured against real processes and saved to disk on
teardown; in replay mode it is served offline, never spawning.

Guard: mark a test ``@pytest.mark.no_real_spawn`` and any *real* process spawn
through ``Command`` / ``Pipeline`` / ``Runner`` / ``ProcessGroup`` inside it fails
loudly (via ``pytest.fail``, which no ``except`` in the code under test can
swallow), so a forgotten double can't quietly hit the OS. Injected doubles keep
working — only the real spawn primitives are blocked. Give the injection-point
APIs (``CliClient``, ``output_all``/…, ``Supervisor``) a test-double ``runner=``
in a guarded test; their default real-runner path spawns entirely inside the Rust
extension, with no Python seam for the guard to intercept. The marker is
registered in ``pytest_configure`` so it passes ``--strict-markers``.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
from typing import TYPE_CHECKING, NoReturn

import pytest

from ._processkit import Command, Pipeline, ProcessGroup, Runner
from .testing import RecordingRunner, RecordReplayRunner, Reply, ScriptedRunner

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

# Public knobs. Names are deliberately prefixed (``processkit_*`` /
# ``PROCESSKIT_*`` / ``--processkit-*``) because an autoloaded pytest11 plugin
# shares the global option/ini/marker namespaces with every consumer.
_RECORD_CLI_DEST = "processkit_record"
_RECORD_INI = "processkit_record"
_CASSETTE_DIR_INI = "processkit_cassette_dir"
_RECORD_ENV = "PROCESSKIT_RECORD"
_NO_SPAWN_MARKER = "no_real_spawn"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Node ids ("tests/test_x.py::test_y[param]") map to filesystem-safe cassette
# file names by collapsing every run of unsafe characters to one underscore and
# appending a digest of the original node id. The digest keeps distinct node ids
# distinct even when their safe stems collide.
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_CASSETTE_NAME_HASH_LENGTH = 12


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the record switch (CLI flag) and the record / cassette-dir ini
    options — the vcr-style knobs the ``record_replay_runner`` fixture reads."""
    group = parser.getgroup("processkit", "processkit testing-seam fixtures")
    group.addoption(
        "--processkit-record",
        action="store_true",
        default=False,
        dest=_RECORD_CLI_DEST,
        help=(
            "Record record/replay cassettes against real processes instead of "
            "replaying them offline (default: replay)."
        ),
    )
    parser.addini(
        _RECORD_INI,
        help="Record record/replay cassettes instead of replaying them (bool).",
        type="bool",
        default=False,
    )
    parser.addini(
        _CASSETTE_DIR_INI,
        help=(
            "Directory holding record/replay cassettes (relative paths resolve "
            "against the rootdir). Defaults to the test's tmp_path."
        ),
        default="",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``no_real_spawn`` marker so it passes ``--strict-markers``."""
    config.addinivalue_line(
        "markers",
        f"{_NO_SPAWN_MARKER}: fail loudly if the test spawns a real process through "
        "processkit's Command/Pipeline/Runner/ProcessGroup instead of an injected "
        "test double.",
    )


# --- runner fixtures --------------------------------------------------------


@pytest.fixture
def scripted_runner() -> ScriptedRunner:
    """A fresh :class:`~processkit.testing.ScriptedRunner` — teach it canned
    replies (``.on(prefix, reply)`` / ``.when(predicate, reply)`` /
    ``.fallback(reply)``) and inject it wherever your code takes a
    ``ProcessRunner``. No real process is ever spawned."""
    return ScriptedRunner()


@pytest.fixture
def recording_runner() -> RecordingRunner:
    """A :class:`~processkit.testing.RecordingRunner` spy that replies
    ``Reply.ok("")`` — a clean exit 0 with empty stdout, the neutral default — to
    every command and records each call. Inspect what your code ran with
    ``.calls()`` / ``.only_call()``. Wrap a different double or a custom reply
    yourself via ``RecordingRunner.new(...)`` / ``.replying(...)`` when the
    default reply doesn't fit."""
    return RecordingRunner.replying(Reply.ok(""))


def _is_record_mode(config: pytest.Config) -> bool:
    """Resolve the record ↔ replay switch: CLI flag, then env var, then ini."""
    if config.getoption(_RECORD_CLI_DEST):
        return True
    env = os.environ.get(_RECORD_ENV)
    if env is not None:
        return env.strip().lower() in _TRUTHY
    return bool(config.getini(_RECORD_INI))


def _cassette_dir(config: pytest.Config, tmp_path: pathlib.Path) -> pathlib.Path:
    """The cassette directory: the ``processkit_cassette_dir`` ini value (resolved
    against the rootdir when relative), or ``tmp_path`` when unset."""
    configured = str(config.getini(_CASSETTE_DIR_INI)).strip()
    if not configured:
        return tmp_path
    directory = pathlib.Path(configured)
    if not directory.is_absolute():
        directory = pathlib.Path(config.rootpath) / directory
    return directory


def _cassette_name(nodeid: str) -> str:
    """A filesystem-safe cassette file name deterministically derived from a test
    node id (``tests/test_x.py::test_y[param]`` →
    ``tests_test_x.py_test_y_param-<hash>.json``)."""
    safe = _UNSAFE_NAME.sub("_", nodeid).strip("_")
    digest = hashlib.sha256(nodeid.encode("utf-8")).hexdigest()[:_CASSETTE_NAME_HASH_LENGTH]
    return f"{safe or 'cassette'}-{digest}.json"


@pytest.fixture
def record_replay_runner(
    request: pytest.FixtureRequest, tmp_path: pathlib.Path
) -> Iterator[RecordReplayRunner]:
    """A :class:`~processkit.testing.RecordReplayRunner` bound to this test's
    cassette. In replay mode (the default) it serves the recorded run offline —
    no spawn; in record mode (see the module docstring's switch) it captures real
    runs and saves the cassette to disk on teardown. The cassette path is
    ``<processkit_cassette_dir or tmp_path>/<safe-node-id>-<hash>.json``."""
    config = request.config
    cassette = _cassette_dir(config, tmp_path) / _cassette_name(request.node.nodeid)
    if _is_record_mode(config):
        cassette.parent.mkdir(parents=True, exist_ok=True)
        runner = RecordReplayRunner.record(str(cassette))
        yield runner
        runner.save()
    else:
        if not cassette.is_file():
            pytest.fail(
                f"record_replay_runner: no cassette found at {cassette}. "
                "Record it first by running with one of: the --processkit-record "
                f"CLI flag, the {_RECORD_ENV}=1 environment variable, or the "
                f"{_RECORD_INI} ini option set to true."
            )
        yield RecordReplayRunner.replay(str(cassette))


# --- the "no real spawn" guard ----------------------------------------------

# The real-spawn primitives whose run verbs always hit the OS (unlike the
# injection-point APIs, which run an injected double when given one). Every
# instance resolves these verbs through its type at call time, so replacing them
# on the type object catches a spawn even through a reference captured before the
# guard ran (`from processkit import Command`). PyO3 forbids subclassing or
# per-instance override of these @final classes, but type-attribute assignment is
# allowed — the reliable interception point.
_SPAWN_VERBS: tuple[tuple[type, tuple[str, ...]], ...] = (
    (
        Command,
        (
            "output",
            "output_bytes",
            "run",
            "exit_code",
            "probe",
            "start",
            "aoutput",
            "aoutput_bytes",
            "arun",
            "aexit_code",
            "aprobe",
            "astart",
        ),
    ),
    (
        Pipeline,
        (
            "output",
            "output_bytes",
            "run",
            "exit_code",
            "probe",
            "aoutput",
            "aoutput_bytes",
            "arun",
            "aexit_code",
            "aprobe",
        ),
    ),
    (
        Runner,
        (
            "output",
            "output_bytes",
            "run",
            "exit_code",
            "probe",
            "start",
            "aoutput",
            "aoutput_bytes",
            "arun",
            "aexit_code",
            "aprobe",
            "astart",
        ),
    ),
    (
        ProcessGroup,
        (
            "output",
            "output_bytes",
            "run",
            "exit_code",
            "probe",
            "start",
            "aoutput",
            "aoutput_bytes",
            "arun",
            "aexit_code",
            "aprobe",
            "astart",
        ),
    ),
)


def _make_blocker(cls_name: str, verb: str) -> Callable[..., NoReturn]:
    """A drop-in method that fails the test loudly instead of spawning."""

    def _blocked(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail(
            f"processkit: real process spawn blocked by @pytest.mark.{_NO_SPAWN_MARKER} — "
            f"{cls_name}.{verb}() would spawn a real process. Inject a test double "
            "(scripted_runner / recording_runner / record_replay_runner) instead.",
            pytrace=False,
        )

    return _blocked


@pytest.fixture(autouse=True)
def _processkit_no_real_spawn(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Autouse guard: for a test marked ``no_real_spawn``, replace the real-spawn
    run verbs on ``Command`` / ``Pipeline`` / ``Runner`` / ``ProcessGroup`` with a
    loud ``pytest.fail``. A no-op (and essentially free) for every other test.
    ``monkeypatch`` restores the originals at teardown."""
    if request.node.get_closest_marker(_NO_SPAWN_MARKER) is None:
        return
    for cls, verbs in _SPAWN_VERBS:
        for verb in verbs:
            monkeypatch.setattr(cls, verb, _make_blocker(cls.__name__, verb), raising=True)
