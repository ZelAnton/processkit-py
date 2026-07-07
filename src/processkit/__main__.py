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
treated as the exit-125 internal failure above.
"""

from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Sequence

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


def _build_parser() -> tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    """The top-level parser plus the ``run`` subparser (returned separately so
    a validation error found only after parsing — e.g. ``--timeout-grace``
    without ``--timeout`` — can still report against the `run` usage line via
    `argparse.ArgumentParser.error`, without reaching into `argparse`'s
    private `_subparsers` bookkeeping to look it back up)."""
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
    return parser, run_parser


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


def _run(
    run_parser: argparse.ArgumentParser, args: argparse.Namespace, child_argv: list[str]
) -> int:
    if args.timeout_grace is not None and args.timeout is None:
        run_parser.error("--timeout-grace requires --timeout")

    program, *rest = child_argv
    command = Command(program, rest).stdout("inherit").stderr("inherit")
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
        _fail(
            f"requested resource limits are not supported in this environment "
            f"({exc}); running contained, but uncapped."
        )
        group = ProcessGroup()

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


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    own_argv, child_argv = _split_child_argv(raw_argv)

    parser, run_parser = _build_parser()
    args = parser.parse_args(own_argv)

    # "run" is the only subparser registered above, and `required=True` means
    # `parse_args` itself already rejected anything else.
    if not child_argv:
        parser.error("run: missing command to execute after '--'")
    return _run(run_parser, args, child_argv)


if __name__ == "__main__":
    sys.exit(main())
