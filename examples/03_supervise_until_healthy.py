"""Keep restarting a flaky worker until it comes up healthy.

The supervision pattern for the agent / long-lived-service niche. A worker that
fails a couple of times before succeeding is restarted with exponential backoff,
and a ``stop_when`` predicate ends the loop the moment a run succeeds. The
restart policy, the backoff schedule, and the stop condition are all declarative
— no hand-rolled retry loop.

Run it:  python examples/03_supervise_until_healthy.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from processkit import Command, Supervisor

# A worker that fails its first two runs, then succeeds. It uses a file as an
# attempt counter that persists across restarts — standing in for a service that
# needs a dependency (a port, a migration, a mount) to become ready first.
_WORKER = """
import os, sys
path = sys.argv[1]
attempt = (int(open(path).read()) if os.path.exists(path) else 0) + 1
open(path, "w").write(str(attempt))
print(f"worker attempt {attempt}", flush=True)
sys.exit(0 if attempt >= 3 else 1)
"""


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        counter = Path(tmp) / "attempts"

        outcome = Supervisor(
            Command(sys.executable, ["-c", _WORKER, str(counter)]),
            # Restart after every run; the predicate below decides when we are
            # actually done (use "on_crash" to restart only on a non-zero exit).
            restart="always",
            max_restarts=5,
            # Small delays so the example finishes quickly; scale these up for a
            # real service (e.g. 0.5 / 2.0 / 30.0).
            backoff_initial=0.05,
            backoff_factor=2.0,
            max_backoff=1.0,
            stop_when=lambda result: result.is_success,
        ).run()  # or: await ...arun()

    print(f"restarts   : {outcome.restarts}")  # 2 — it failed twice first
    print(f"stopped by : {outcome.stopped}")  # 'predicate' — our stop_when fired
    print(f"final code : {outcome.final_result.code}")
    print("healthy" if outcome.final_result.is_success else "gave up")


if __name__ == "__main__":
    main()
