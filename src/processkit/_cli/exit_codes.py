"""Shared exit-code constants for the ``python -m processkit`` CLI.

See `processkit._cli`'s module docstring for the full exit-code contract
these implement; kept in one module so `run` and `doctor` (independent exit-
code namespaces that must stay disjoint from each other and from argparse's
own usage-error code `2`) can both import from a single source of truth.
"""

from __future__ import annotations

#: GNU-`timeout`-compatible: the run hit its `--timeout` deadline.
EXIT_TIMEOUT = 124
#: An internal / containment failure that isn't one of the more specific codes
#: below (e.g. a rejected resource limit, or containment unavailable at all).
EXIT_INTERNAL_ERROR = 125
#: The program was found but could not be executed (`PermissionDenied`).
EXIT_NOT_EXECUTABLE = 126
#: The program could not be found (`ProcessNotFound`).
EXIT_NOT_FOUND = 127
#: Added to a signal number for a signal-killed child, or to `SIGINT` when
#: this wrapper itself is interrupted — the same convention a POSIX shell uses.
EXIT_SIGNAL_BASE = 128

#: `doctor`: containment mechanism *and* all three resource limits are
#: available.
EXIT_DOCTOR_OK = 0
#: `doctor`: containment is enforced, but at least one of `--max-memory` /
#: `--max-processes` / `--cpu-quota` is not — the same "contained, but
#: uncapped" gap `run` degrades around. Deliberately distinct from `run`'s
#: reserved codes above (124-127, 128+signal): `doctor` has its own
#: exit-code namespace, not a shared one.
EXIT_DOCTOR_LIMITS_UNAVAILABLE = 1
#: Deliberately *not* assigned to a `doctor` verdict: this is argparse's own
#: usage-error code (shared with `run`'s usage errors, e.g. a missing `--`
#: command). Reserving it here — rather than reusing it for a diagnostic
#: outcome as an earlier revision did — keeps "you called this wrong"
#: unambiguous from any real diagnostic result (see R-2 in review history).
EXIT_DOCTOR_USAGE_ERROR = 2
#: `doctor`: containment itself is unavailable in this environment (should
#: not happen on any supported platform).
EXIT_DOCTOR_NO_CONTAINMENT = 3
#: `doctor`: a probe (containment mechanism or an individual resource limit)
#: raised an unexpected operational error (`OSError`/`PermissionError`, e.g.
#: failing to read cgroup state) rather than a definitive
#: `ResourceLimit`/`Unsupported` answer. This is not a reliable diagnostic
#: result — the true availability could not be determined — so it is
#: deliberately its own code, distinct from both the "unavailable" verdicts
#: above and from an unhandled traceback.
EXIT_DOCTOR_PROBE_ERROR = 4
