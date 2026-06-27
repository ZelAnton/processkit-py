"""Shared pytest fixtures across the test suite.

Complements (does not duplicate) `_programs.py` (child-program snippets +
port helpers) and `_liveness.py` (process-liveness polling): this module
centralizes the spawn-grandchild -> pid-file -> teardown ritual (previously
copy-pasted ~12 times across 4 test files) and the canonical "this program
does not exist" names (previously 3 different ad hoc spellings scattered
across the suite).
"""

from __future__ import annotations

import pathlib
import sys

import pytest

from processkit import Command

from ._programs import SPAWN_GRANDCHILD

#: The interpreter under test, for building child `Command`s.
PY = sys.executable

#: The single canonical "no such program" name, reused wherever a test needs a
#: spawn to fail because the program does not exist (previously spelled
#: `"processkit-no-such-binary-xyzzy"`, `"processkit-definitely-no-such-program-xyz"`,
#: `"processkit-no-such-cli-tool"`, `"processkit-no-such-supervisor-program"`, ...
#: across different files — one name now, everywhere a *missing program* is
#: the point).
NO_SUCH_PROGRAM = "processkit-no-such-program-xyzzy"

#: Canonical "no such directory" name, for a `cwd()` that cannot resolve
#: (distinct from `NO_SUCH_PROGRAM` — a bad `cwd` is a `Spawn` failure, not a
#: missing-program one; see `test_exceptions.py`).
NO_SUCH_DIRECTORY = "processkit-no-such-directory-xyzzy"


@pytest.fixture
def pid_file(tmp_path: pathlib.Path) -> pathlib.Path:
    """Where a grandchild-spawning child (`spawn_grandchild_command`) writes
    its grandchild's PID, for `read_pid_when_ready`/`wait_dead` to poll."""
    return tmp_path / "grandchild.pid"


def spawn_grandchild_command(pid_file: pathlib.Path) -> Command:
    """A `Command` that spawns a detached grandchild, writes the grandchild's
    PID to `pid_file`, then sleeps — the standard whole-tree-teardown probe:
    start it under whatever container is being tested, wait for `pid_file`
    (`read_pid_when_ready`), then assert the grandchild dies with the
    container (`wait_dead`), proving containment reaches descendants, not
    just the direct child.
    """
    return Command(PY, ["-c", SPAWN_GRANDCHILD, str(pid_file)])
