"""processkit.testing — runner test doubles for code written against a runner.

Inject a real `Runner` (from the top-level `processkit`) in production and one of
these doubles in tests; all of them satisfy the `processkit.ProcessRunner`
protocol, so the code under test never knows the difference.

- `ScriptedRunner` — canned replies for argv prefixes (no real processes spawned).
- `RecordReplayRunner` — record real runs to a cassette, then replay them offline.
- `RecordingRunner` — reply with one canned `Reply` and record every call made.
- `DryRunRunner` — render each command to text and never spawn; the seam behind
  a tool's own `--dry-run`/`--echo` mode.
- `Reply` — the canned outcome a `ScriptedRunner` / `RecordingRunner` returns.
- `Invocation` — one call captured by a `RecordingRunner`, for assertions.
"""

from __future__ import annotations

from ._processkit import (
    DryRunRunner,
    Invocation,
    RecordingRunner,
    RecordReplayRunner,
    Reply,
    ScriptedRunner,
)

__all__ = [
    "DryRunRunner",
    "Invocation",
    "RecordReplayRunner",
    "RecordingRunner",
    "Reply",
    "ScriptedRunner",
]
