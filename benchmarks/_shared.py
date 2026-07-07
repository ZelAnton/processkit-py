"""Small pieces shared by the benchmark modules — no test collection here."""

from __future__ import annotations

import sys

#: The interpreter under test, for building child `Command`s/`subprocess`
#: calls — same idea as `tests/conftest.py`'s `PY`, kept local so this
#: directory has no import-time dependency on the `tests/` package.
PY = sys.executable

#: A short-lived child that does no work (the pure per-call-overhead
#: baseline) — the same style as `tests/test_hardening.py`'s
#: `test_no_silly_per_call_overhead`.
NOOP_CODE = "pass"

#: A payload that also exercises stdout *capture* (not just spawn/exit),
#: identical across all three "spawn + capture" benchmarks below so the
#: comparison isolates per-call overhead rather than differing workloads.
CAPTURE_CODE = "import sys; sys.stdout.write('x' * 4096)"
