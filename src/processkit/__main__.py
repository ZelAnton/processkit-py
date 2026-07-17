"""``python -m processkit`` — run a shell command under processkit containment.

    python -m processkit run [OPTIONS] -- PROGRAM [ARG ...]

Everything after the literal ``--`` is the child's own argv, passed through
untouched (a second ``--`` in there is none of this wrapper's business — only
the *first* one is treated as the separator). The child is started inside a
`ProcessGroup` — a kill-on-exit container for the *whole* process tree, not
just the direct child — even for this single command, so a build tool's
grandchildren or a script's background jobs can never survive past this
process. Stdio is inherited straight through to the terminal
(`stdout("inherit")` / `stderr("inherit")`): the child's output streams live,
the same as running it directly, never buffered up and dumped at the end.

Exit code contract:

- Normal completion: this process exits with the **exact same code** as the
  child (`Outcome.code`, unchanged).
- ``--timeout`` expired: exit **124** (matching GNU coreutils ``timeout``),
  with a one-line message on stderr — never a traceback.
- The child could not be found: exit **127** (``ProcessNotFound``).
- The child was found but could not be executed (e.g. not executable / no
  permission): exit **126** (``PermissionDenied``).
- The child was killed by a signal (POSIX only): exit **128 + signal number**
  (the same convention a POSIX shell uses).
- ``python -m processkit`` itself was interrupted with Ctrl+C: exit
  **128 + SIGINT**.
- Any other internal/containment failure (see below): exit **125**.

Resource-limit availability (``--max-memory`` / ``--max-processes`` /
``--cpu-quota``): these need a real container — a Windows Job Object or a
Linux **cgroup-v2 root** — the same prerequisite `ProcessGroup` itself
documents. When the kernel refuses a requested cap (`ResourceLimit` /
`Unsupported` — typical in containers, systemd user sessions, non-root
cgroups, and always on macOS), this CLI does **not** hard-fail: it prints a
warning to stderr and re-runs the child in a plain, uncapped `ProcessGroup`
— "contained, but uncapped" — by analogy with
``examples/04_sandbox_resource_limits.py``. The child still gets the
no-orphan containment guarantee either way; only the specific numeric caps
are dropped. If *no* resource limit was requested and containment itself is
unavailable (should not happen on any supported platform), that is instead
treated as the exit-125 internal failure above — and so is the (also
shouldn't-happen) case where the requested cap was rejected *and* the plain,
uncapped fallback still fails: containment is unavailable outright, not
merely the specific cap.

    python -m processkit doctor

A read-only preflight diagnosis of the containment environment, for CI gates
and wrapper scripts that want to know "will my caps actually hold here"
*before* running any untrusted workload, instead of parsing a `run` warning
on stderr after the fact. Nothing is spawned: it only constructs (and
immediately drops) throwaway `ProcessGroup` instances to see what the kernel
grants. Prints the active mechanism (`ProcessGroup().mechanism`) and whether
resource limits (`--max-memory` / `--max-processes` / `--cpu-quota`) are
actually enforceable — the same platform gap `run` degrades around above
(containers, systemd user sessions, non-root cgroups, and always on macOS
lack the Windows Job Object / Linux cgroup-v2 root those caps need).

`doctor` probes each of the three resource-limit controllers
(``--max-memory`` / ``--max-processes`` / ``--cpu-quota``) **independently** —
on Linux cgroup-v2 these are separate controllers (``memory.max``,
``pids.max``, ``cpu.max``) that can be unavailable one without the others —
so "resource limits are available" means *all three* probed successfully,
not just the first one tried.

`doctor`'s exit code is machine-readable and lives in its own reserved range,
deliberately disjoint from `run`'s codes above (124/125/126/127/128+signal)
*and* from argparse's own usage-error code (`2` — the same code `run` itself
uses for a bad invocation, e.g. a missing `--`-terminated command): `doctor`
never returns `2` as a diagnostic verdict, so a caller can always read `2` as
"you called this wrong", unambiguous from any of the codes below:

- **0** — resource limits are available (containment *and* all three caps
  hold).
- **1** — containment is enforced, but at least one resource limit is not
  (the "contained, but uncapped" gap).
- **3** — containment itself is unavailable (should not happen on any
  supported platform).
- **4** — a probe raised an unexpected operational error (e.g. `OSError` /
  `PermissionError` reading cgroup state) rather than a definitive
  `ResourceLimit`/`Unsupported` answer — the environment's actual
  availability could not be determined, so this is deliberately distinct
  from both `1` and `3` rather than guessing which one it is.
"""

from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Callable, Sequence

from processkit import (
    Command,
    PermissionDenied,
    ProcessError,
    ProcessGroup,
    ProcessNotFound,
    ResourceLimit,
    Unsupported,
)

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

#: Deliberately tiny probe values for `doctor`'s three independent
#: resource-limit checks — small enough to be a meaningful "would a real cap
#: be granted at all" test, but nothing is ever started in any probed group,
#: so the actual numbers never matter.
_DOCTOR_PROBE_MAX_MEMORY = 1024 * 1024
_DOCTOR_PROBE_MAX_PROCESSES = 1
_DOCTOR_PROBE_CPU_QUOTA = 0.1
#: Each entry is ``(flag name, constructor)``; probed independently because
#: on Linux cgroup-v2 these map to separate controllers (``memory.max`` /
#: ``pids.max`` / ``cpu.max``) that can be unavailable one without the
#: others (see R-1 in review history). Plain no-arg callables (rather than a
#: shared ``ProcessGroup(**{kwarg: value})``) keep each call's keyword typed
#: precisely for the type checker.
_DOCTOR_LIMIT_PROBES: tuple[tuple[str, Callable[[], ProcessGroup]], ...] = (
    ("--max-memory", lambda: ProcessGroup(max_memory=_DOCTOR_PROBE_MAX_MEMORY)),
    ("--max-processes", lambda: ProcessGroup(max_processes=_DOCTOR_PROBE_MAX_PROCESSES)),
    ("--cpu-quota", lambda: ProcessGroup(cpu_quota=_DOCTOR_PROBE_CPU_QUOTA)),
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value!r}")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not (parsed > 0):  # rejects <= 0 and NaN alike
        raise argparse.ArgumentTypeError(f"must be a positive number, got {value!r}")
    return parsed


def _build_parser() -> tuple[
    argparse.ArgumentParser, argparse.ArgumentParser, argparse.ArgumentParser
]:
    """The top-level parser plus the ``run`` and ``doctor`` subparsers
    (returned separately so a validation error found only after parsing —
    e.g. ``--timeout-grace`` without ``--timeout``, or a trailing command
    after ``doctor`` — can still report against the right subcommand's usage
    line via `argparse.ArgumentParser.error`, without reaching into
    `argparse`'s private `_subparsers` bookkeeping to look it back up)."""
    parser = argparse.ArgumentParser(
        prog="python -m processkit",
        description="Run a command under processkit's kernel-backed no-orphan containment.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    run_parser = subparsers.add_parser(
        "run",
        help="Run a command inside a ProcessGroup container",
        description=(
            "Run PROGRAM [ARG ...] inside a kill-on-exit ProcessGroup, with stdio "
            "inherited so its output streams live to this terminal."
        ),
        epilog="Example: python -m processkit run --timeout 30 -- pytest -x",
    )
    run_parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help="Kill the whole child tree if the run is still going after SECONDS.",
    )
    run_parser.add_argument(
        "--timeout-grace",
        dest="timeout_grace",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help=(
            "On --timeout expiry, signal first and wait up to SECONDS before the "
            "hard kill (requires --timeout)."
        ),
    )
    run_parser.add_argument(
        "--max-memory",
        dest="max_memory",
        type=_positive_int,
        default=None,
        metavar="BYTES",
        help="Cap the whole child tree's memory, in bytes (needs a real container).",
    )
    run_parser.add_argument(
        "--max-processes",
        dest="max_processes",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Cap the number of processes in the tree (needs a real container).",
    )
    run_parser.add_argument(
        "--cpu-quota",
        dest="cpu_quota",
        type=_positive_float,
        default=None,
        metavar="FLOAT",
        help=(
            "Cap CPU as a fraction of a single core (0.5 = half a core, 2.0 = two "
            "cores; needs a real container)."
        ),
    )
    run_parser.add_argument(
        "--env-clear",
        dest="env_clear",
        action="store_true",
        help="Start the child with an empty environment (Command.env_clear()).",
    )
    run_parser.add_argument(
        "--inherit-env",
        dest="inherit_env",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Allow-list a parent environment variable through to the child "
            "(Command.inherit_env(...); implies --env-clear). Repeatable."
        ),
    )
    run_parser.add_argument(
        "--env",
        dest="env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Set/override a child environment variable (Command.env(...)). Repeatable.",
    )
    run_parser.add_argument(
        "--cwd",
        dest="cwd",
        default=None,
        metavar="DIR",
        help="Run the child with DIR as its working directory (Command.cwd(...)).",
    )
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Diagnose the containment environment without running anything",
        description=(
            "Report the active containment mechanism and whether resource limits "
            "(--max-memory/--max-processes/--cpu-quota) are actually available here, "
            "before running any untrusted workload. Read-only: nothing is spawned."
        ),
        epilog="Example: python -m processkit doctor",
    )
    return parser, run_parser, doctor_parser


def _split_child_argv(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split ``argv`` on the first literal ``--``: everything before it is this
    wrapper's own flags (handed to `argparse`), everything after is the
    child's argv, untouched — including any further ``--`` in there."""
    argv = list(argv)
    if "--" not in argv:
        return argv, []
    index = argv.index("--")
    return argv[:index], argv[index + 1 :]


def _fail(message: str) -> None:
    print(f"processkit: {message}", file=sys.stderr)


def _parse_env_flags(
    run_parser: argparse.ArgumentParser, raw_pairs: list[str]
) -> list[tuple[str, str]]:
    """Parse repeated ``--env KEY=VALUE`` values, reporting a missing ``=`` as
    a usage error (via `run_parser.error`, which itself exits) rather than
    letting it surface as an unhandled `ValueError`/traceback."""
    pairs: list[tuple[str, str]] = []
    for raw in raw_pairs:
        if "=" not in raw:
            run_parser.error(f"--env {raw!r}: expected KEY=VALUE")
        key, _, value = raw.partition("=")
        pairs.append((key, value))
    return pairs


def _run(
    run_parser: argparse.ArgumentParser, args: argparse.Namespace, child_argv: list[str]
) -> int:
    if args.timeout_grace is not None and args.timeout is None:
        run_parser.error("--timeout-grace requires --timeout")

    env_pairs = _parse_env_flags(run_parser, args.env)

    program, *rest = child_argv
    command = Command(program, rest).stdout("inherit").stderr("inherit")
    # Environment builders compose in a fixed order at spawn regardless of
    # call order (docs/commands.md#environment-and-sandboxing), but this is
    # still the natural reading order: clear/allow-list the base environment
    # first, then layer explicit overrides and the working directory on top.
    if args.env_clear:
        command = command.env_clear()
    if args.inherit_env:
        command = command.inherit_env(args.inherit_env)
    for key, value in env_pairs:
        command = command.env(key, value)
    if args.cwd is not None:
        command = command.cwd(args.cwd)
    if args.timeout is not None:
        command = command.timeout(args.timeout)
        if args.timeout_grace is not None:
            command = command.timeout_grace(args.timeout_grace)

    limits_requested = (
        args.max_memory is not None or args.max_processes is not None or args.cpu_quota is not None
    )
    try:
        group = ProcessGroup(
            max_memory=args.max_memory,
            max_processes=args.max_processes,
            cpu_quota=args.cpu_quota,
        )
    except (ResourceLimit, Unsupported) as exc:
        if not limits_requested:
            _fail(f"containment is unavailable in this environment: {exc}")
            return EXIT_INTERNAL_ERROR
        try:
            group = ProcessGroup()
        except (ResourceLimit, Unsupported) as exc2:
            # Containment itself is unavailable (not merely the requested
            # limit) — report that, not the now-moot "running uncapped"
            # message, and never let it propagate as a traceback.
            _fail(f"containment is unavailable in this environment: {exc2}")
            return EXIT_INTERNAL_ERROR
        _fail(
            f"requested resource limits are not supported in this environment "
            f"({exc}); running contained, but uncapped."
        )

    try:
        with group:
            try:
                proc = group.start(command)
            except (ProcessNotFound, PermissionDenied, ResourceLimit, Unsupported) as exc:
                if isinstance(exc, ProcessNotFound):
                    _fail(f"{program!r}: command not found")
                    return EXIT_NOT_FOUND
                if isinstance(exc, PermissionDenied):
                    _fail(f"{program!r}: permission denied")
                    return EXIT_NOT_EXECUTABLE
                _fail(f"could not start {program!r}: {exc}")
                return EXIT_INTERNAL_ERROR
            outcome = proc.outcome()
    except KeyboardInterrupt:
        _fail("interrupted")
        return EXIT_SIGNAL_BASE + signal.SIGINT
    except ProcessError as exc:  # defensive: no known path raises here, but never a traceback
        _fail(f"{program!r} failed: {exc}")
        return EXIT_INTERNAL_ERROR

    if outcome.timed_out:
        _fail(f"{program!r} timed out after {args.timeout}s")
        return EXIT_TIMEOUT
    if outcome.signal is not None:
        _fail(f"{program!r} was killed by signal {outcome.signal}")
        return EXIT_SIGNAL_BASE + outcome.signal
    if outcome.code is None:
        _fail(f"{program!r} produced no exit code")
        return EXIT_INTERNAL_ERROR
    return outcome.code


def _print_doctor_caveat() -> None:
    print(
        "  note: --max-memory/--max-processes/--cpu-quota need a Windows Job "
        "Object or a Linux cgroup-v2 root; the kernel typically refuses them "
        "inside containers, systemd user sessions, and non-root cgroups, and "
        "always on macOS (docs/cli.md#resource-limits-hard-cap-or-best-effort)."
    )


def _doctor() -> int:
    """Read-only preflight probe: never spawns anything, only constructs (and
    immediately drops) throwaway `ProcessGroup` instances to see what the
    kernel actually grants in this environment. See the module docstring for
    the exit-code contract this implements.

    Unexpected operational errors (`OSError`/`PermissionError` — e.g. failing
    to read cgroup state) are caught and reported distinctly from a
    definitive `ResourceLimit`/`Unsupported` answer (exit
    `EXIT_DOCTOR_PROBE_ERROR`, never a traceback); a truly unexpected
    programming error (anything else) is deliberately left to propagate as a
    traceback rather than being misreported as one of the diagnostic
    verdicts above."""
    print("processkit doctor")
    try:
        plain_group = ProcessGroup()
    except (ResourceLimit, Unsupported) as exc:
        print(f"  containment mechanism : unavailable ({exc})")
        print("  resource limits        : unavailable (no containment mechanism to test)")
        _print_doctor_caveat()
        print("  verdict: UNAVAILABLE - no containment mechanism in this environment (exit 3)")
        return EXIT_DOCTOR_NO_CONTAINMENT
    except OSError as exc:
        print(f"  containment mechanism : error probing ({exc})")
        print("  resource limits        : unknown (mechanism probe failed)")
        print(
            "  verdict: ERROR - could not determine containment availability "
            "(exit 4)"
        )
        return EXIT_DOCTOR_PROBE_ERROR

    mechanism = plain_group.mechanism
    print(f"  containment mechanism : {mechanism}")
    del plain_group  # drop the throwaway probe before the (separate) limits probes

    # Probe each of the three resource-limit controllers independently: on
    # Linux cgroup-v2 they are separate controllers that can be unavailable
    # one without the others, so "available" must mean all three, not just
    # the first one tried.
    unavailable: list[str] = []
    probe_errors: list[str] = []
    for flag, construct in _DOCTOR_LIMIT_PROBES:
        try:
            construct()
        except (ResourceLimit, Unsupported) as exc:
            unavailable.append(f"{flag} ({exc})")
        except OSError as exc:
            probe_errors.append(f"{flag} ({exc})")

    if probe_errors:
        print(f"  resource limits        : error probing {'; '.join(probe_errors)}")
        if unavailable:
            print(f"  resource limits        : also unavailable {'; '.join(unavailable)}")
        _print_doctor_caveat()
        print(
            "  verdict: ERROR - could not determine resource-limit availability "
            "(exit 4)"
        )
        return EXIT_DOCTOR_PROBE_ERROR

    if unavailable:
        print(f"  resource limits        : unavailable {'; '.join(unavailable)}")
        _print_doctor_caveat()
        print("  verdict: DEGRADED - containment is enforced, but resource limits are not (exit 1)")
        return EXIT_DOCTOR_LIMITS_UNAVAILABLE

    print("  resource limits        : available")
    print("  verdict: OK - containment and resource limits are both available (exit 0)")
    return EXIT_DOCTOR_OK


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    own_argv, child_argv = _split_child_argv(raw_argv)

    parser, run_parser, doctor_parser = _build_parser()
    args = parser.parse_args(own_argv)

    if args.subcommand == "doctor":
        if child_argv:
            doctor_parser.error("doctor: does not take a trailing command (no '--' needed)")
        return _doctor()

    # "run" is the only other subparser registered above, and `required=True`
    # means `parse_args` itself already rejected anything else — so `run` is
    # guaranteed parsed by now, and this late validation error reports
    # against the `run` usage line, not the top-level one.
    if not child_argv:
        run_parser.error("run: missing command to execute after '--'")
    return _run(run_parser, args, child_argv)


if __name__ == "__main__":
    sys.exit(main())
