"""The opt-in `tracing` -> Python `logging` bridge (`enable_logging`).

The underlying crate emits a per-run debug event (tagged target `"processkit"`);
`enable_logging()` installs a global subscriber that forwards each to a
`logging.getLogger("processkit")` record. Off until called; idempotent.
"""

from __future__ import annotations

import logging
import sys

import pytest

from processkit import Command, enable_logging

PY = sys.executable


def test_enable_logging_is_idempotent() -> None:
    # First call installs the process-global subscriber; later calls are no-ops.
    # Returns True while the bridge is active.
    assert enable_logging() is True
    assert enable_logging() is True


def test_enable_logging_forwards_runs_to_python_logging(caplog: pytest.LogCaptureFixture) -> None:
    enable_logging()
    # Pass a sentinel as argv: the events log program/pid/mechanism but never argv
    # or env (they routinely carry secrets), so the sentinel must NOT appear.
    sentinel = "secret-argv-sentinel"
    with caplog.at_level(logging.DEBUG, logger="processkit"):
        Command(PY, ["-c", "pass", sentinel]).run()

    records = [r for r in caplog.records if r.name == "processkit"]
    assert records, "expected a processkit log record from the run"
    # The crate's per-run event is `debug!("child spawned", program=..., pid=...)`.
    # Assert the level on that specific record, not on every forwarded record —
    # the crate may also emit its own documented WARNING-level edge events, and
    # `enable_logging()` is process-global for the rest of the session.
    spawned = [r for r in records if "spawned" in r.getMessage()]
    assert spawned, "expected a 'child spawned' record from the run"
    assert all(r.levelno == logging.DEBUG for r in spawned)
    # The argv sentinel we passed must be absent from every forwarded record.
    assert not any(sentinel in r.getMessage() for r in records)
