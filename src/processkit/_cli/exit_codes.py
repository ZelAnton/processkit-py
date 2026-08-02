"""Shared exit-code constants for the ``python -m processkit`` CLI.

See `processkit._cli`'s module docstring for the full exit-code contract
these implement; kept in one module so `run`, `doctor`, and `supervise` can
all import from a single source of truth. Their subcommand-specific primary
and reserved ranges stay disjoint from each other and argparse's own
usage-error code `2` (K-027), while shared semantic codes are deliberately
reused: 124 for wall-clock timeout and 128+signal for signal termination.
"""

from __future__ import annotations

#: Shared by *every* subcommand, and produced by the entry point itself rather
#: than by any one of them: the command finished, but this process could not
#: deliver its own buffered stdout/stderr (`_flush_std_streams` in
#: `processkit._cli`) — a full or failing disk (`ENOSPC`/`EIO`), or a stream a
#: caller closed underneath it. Output this wrapper produced is gone, so the
#: code it would otherwise have exited with (the child's own code included) is
#: not reported: that code would claim a complete, faithfully-relayed run,
#: which is exactly what did not happen. A vanished *receiver*
#: (`BrokenPipeError`/`EPIPE`, e.g. ``... | head``) is deliberately **not**
#: this case — no exit code can deliver output to an end that is already gone.
#: One shared code rather than a per-subcommand one, and disjoint from all
#: three primary/reserved namespaces (K-027): `run`'s 123/125-127,
#: `supervise`'s 120-122 (which also reuses the shared timeout code 124 and
#: 128+signal convention), `doctor`'s 0/1/3/4, and argparse's 2 — so it means
#: exactly the same thing wherever it surfaces.
EXIT_OUTPUT_LOST = 119
#: `supervise` uses 120-122, deliberately disjoint from argparse's usage-error
#: code 2, `doctor`'s 0/1/3/4 verdicts, and `run`'s 125-127 reservation below
#: (it reuses the shared `EXIT_SIGNAL_BASE` + signal-number convention below
#: for a signal-killed final incarnation and for its own Ctrl+C handling,
#: and likewise reuses `EXIT_TIMEOUT` (124) for a final incarnation that
#: timed out, exactly like `run`, rather than reserving a separate code for
#: any of the three).
#: `supervise`: an internal error building or running its `Command` / `Supervisor`
#: (including `ProcessNotFound`, `PermissionDenied`, `ResourceLimit`, or `Unsupported`).
EXIT_SUPERVISE_INTERNAL_ERROR = 120
#: `supervise`: the restart policy wanted another attempt, but `max_restarts` was exhausted.
EXIT_SUPERVISE_RESTARTS_EXHAUSTED = 121
#: `supervise`: supervision stopped because a `give_up_when` predicate matched.
EXIT_SUPERVISE_GAVE_UP = 122
#: `run`: the run hit its `--idle-timeout` (produced no output line for that
#: many seconds and was killed). Deliberately a *distinct* code from
#: `EXIT_TIMEOUT` (124, wall-clock `--timeout`): the two timeout classes stay
#: tellable apart by exit code, mirroring the `IdleTimeout`-vs-`Timeout`
#: exception split. Sits just below `run`'s 124-127 GNU-`timeout` reservation —
#: 123 is not used by GNU `timeout` — and stays clear of argparse's `2`,
#: `doctor`'s 0/1/3/4, and `supervise`'s 120-122 (K-027: disjoint namespaces).
EXIT_IDLE_TIMEOUT = 123
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
