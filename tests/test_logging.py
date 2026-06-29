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
    assert any("spawned" in r.getMessage() for r in records)
    assert all(r.levelno == logging.DEBUG for r in records)
    # The argv sentinel we passed must be absent from every forwarded record.
    assert not any(sentinel in r.getMessage() for r in records)
