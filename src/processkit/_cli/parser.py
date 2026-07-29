"""argparse construction for the ``python -m processkit`` CLI, plus the
``--``-separator split between this wrapper's own flags and the child's argv.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

#: Sentinel `const=` for ``--profile``'s optional `FILE` argument (`nargs="?"`):
#: distinguishes "flag absent" (`args.profile is None`, the default) from
#: "flag given with no value" (`args.profile is PROFILE_STDERR_MARKER`, print
#: to stderr) from "flag given with a value" (`args.profile` is that path
#: string). A single ``--profile [FILE]`` flag was chosen over a `--profile` +
#: `--profile-out FILE` pair: it is one flag to document/complete instead of
#: two that must be used together, mirrors the "optional value" idiom
#: `nargs="?"` already gives argparse for free, and there is no scenario where
#: a caller wants "collect a profile" and "where to put it" to vary
#: independently of each other.
PROFILE_STDERR_MARKER = object()


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


def _io_priority(value: str) -> tuple[str, int | None]:
    class_name, separator, raw_level = value.partition(":")
    if class_name == "idle":
        if separator:
            raise argparse.ArgumentTypeError("idle I/O priority does not take a level")
        return class_name, None
    if class_name not in {"best_effort", "real_time"} or not separator:
        raise argparse.ArgumentTypeError("must be idle, best_effort:LEVEL, or real_time:LEVEL")
    try:
        level = int(raw_level)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "I/O priority level must be an integer from 0 to 7"
        ) from exc
    if not 0 <= level <= 7:
        raise argparse.ArgumentTypeError("I/O priority level must be an integer from 0 to 7")
    return class_name, level


def _cpu_affinity(value: str) -> list[int]:
    raw_cpus = value.split(",")
    if not value or any(not raw for raw in raw_cpus):
        raise argparse.ArgumentTypeError("must be a comma-separated list of CPU indices")
    try:
        cpus = [int(raw) for raw in raw_cpus]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("CPU indices must be non-negative integers") from exc
    if any(cpu < 0 for cpu in cpus):
        raise argparse.ArgumentTypeError("CPU indices must be non-negative integers")
    return cpus


def _build_parser() -> tuple[
    argparse.ArgumentParser,
    argparse.ArgumentParser,
    argparse.ArgumentParser,
    argparse.ArgumentParser,
]:
    """The top-level parser plus the ``run``, ``doctor``, and ``supervise`` subparsers
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
        "--idle-timeout",
        dest="idle_timeout",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help=(
            "Kill the child if it produces no output line for SECONDS "
            "(Command.idle_timeout(...)) — for a tool that hangs silently while a "
            "healthy long job keeps printing. Exit code 123, distinct from "
            "--timeout's 124. Requires capturing output line-by-line, so with this "
            "flag the child's stdout/stderr are piped and re-emitted (decoded "
            "text, one line at a time) instead of inherited raw; incompatible with "
            "--profile."
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
        "--env-file",
        dest="env_file",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "Load KEY=VALUE entries from PATH; blank lines and # comments are ignored. "
            "Repeatable; later files win, and --env overrides every file."
        ),
    )
    run_parser.add_argument(
        "--cwd",
        dest="cwd",
        default=None,
        metavar="DIR",
        help="Run the child with DIR as its working directory (Command.cwd(...)).",
    )
    run_parser.add_argument(
        "--profile",
        dest="profile",
        nargs="?",
        const=PROFILE_STDERR_MARKER,
        default=None,
        metavar="FILE",
        help=(
            "After the child exits, emit a machine-readable JSON resource profile "
            "(RunningProcess.profile(): duration_seconds/cpu_time_seconds/"
            "peak_memory_bytes/avg_cpu_cores/samples, plus code/signal/timed_out) "
            "— to stderr if FILE is omitted, or written to FILE otherwise. Never "
            "interleaved with the child's own inherited stdio. Fields needing a "
            "Windows Job Object or Linux cgroup-v2 are null where unavailable."
        ),
    )
    run_parser.add_argument(
        "--create-no-window",
        dest="create_no_window",
        action="store_true",
        help=(
            "Do not create a console window for the child (Command.create_no_window()). "
            "No-op outside Windows, same as the underlying binding method."
        ),
    )
    run_parser.add_argument(
        "--output-limit",
        dest="output_limit",
        type=_positive_int,
        default=None,
        metavar="BYTES",
        help=(
            "Cap captured stdout/stderr at BYTES and fail if the child exceeds it. "
            "Output is piped and re-emitted line-by-line."
        ),
    )
    run_parser.add_argument(
        "--stdout-file",
        dest="stdout_file",
        default=None,
        metavar="PATH",
        help="Redirect the child's stdout directly to PATH (create or truncate).",
    )
    run_parser.add_argument(
        "--stderr-file",
        dest="stderr_file",
        default=None,
        metavar="PATH",
        help="Redirect the child's stderr directly to PATH (create or truncate).",
    )
    run_parser.add_argument(
        "--kill-on-parent-death",
        dest="kill_on_parent_death",
        action="store_true",
        help="Request the platform's best-effort abrupt-parent-death cleanup.",
    )
    run_parser.add_argument(
        "--priority",
        choices=("idle", "below_normal", "normal", "above_normal", "high"),
        default=None,
        help="Set the child's CPU scheduling priority preset.",
    )
    run_parser.add_argument(
        "--io-priority",
        dest="io_priority",
        type=_io_priority,
        default=None,
        metavar="CLASS[:LEVEL]",
        help="Set Linux I/O priority: idle, best_effort:0..7, or real_time:0..7.",
    )
    run_parser.add_argument(
        "--cpu-affinity",
        dest="cpu_affinity",
        type=_cpu_affinity,
        default=None,
        metavar="CPU[,CPU...]",
        help="Restrict the child tree to logical CPU indices (Linux/Windows).",
    )
    run_parser.add_argument(
        "--pty",
        action="store_true",
        help="Run the child under a pseudo-terminal and emit its merged terminal stream.",
    )
    run_parser.add_argument(
        "--pty-cols",
        dest="pty_cols",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Initial pseudo-terminal width (requires --pty and --pty-rows).",
    )
    run_parser.add_argument(
        "--pty-rows",
        dest="pty_rows",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Initial pseudo-terminal height (requires --pty and --pty-cols).",
    )
    supervise_parser = subparsers.add_parser(
        "supervise",
        help="Keep a command alive with restart policy and backoff",
        description=(
            "Run PROGRAM [ARG ...] under Supervisor, restarting it according to the "
            "selected policy with optional bounded exponential backoff."
        ),
        epilog="Example: python -m processkit supervise --restart always -- ./server",
    )
    supervise_parser.add_argument(
        "--restart",
        choices=("always", "on_crash", "never"),
        default=None,
        help="Restart policy (Supervisor(restart=...)).",
    )
    supervise_parser.add_argument(
        "--max-restarts",
        dest="max_restarts",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Stop supervising after N restarts (Supervisor(max_restarts=...)).",
    )
    supervise_parser.add_argument(
        "--backoff-initial",
        dest="backoff_initial",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help="Initial delay before a restart (Supervisor(backoff_initial=...)).",
    )
    supervise_parser.add_argument(
        "--backoff-factor",
        dest="backoff_factor",
        type=_positive_float,
        default=None,
        metavar="FLOAT",
        help="Multiplier for successive restart delays; must be at least 1.",
    )
    supervise_parser.add_argument(
        "--max-backoff",
        dest="max_backoff",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help="Maximum delay before a restart (Supervisor(max_backoff=...)).",
    )
    supervise_parser.add_argument(
        "--no-jitter",
        dest="no_jitter",
        action="store_true",
        help="Disable random jitter in restart delays (enabled by default).",
    )
    supervise_parser.add_argument(
        "--idle-timeout",
        dest="idle_timeout",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help=(
            "Accepted for parity with `run`, but NOT yet enforceable under "
            "supervise: each incarnation runs through Supervisor's one-shot "
            "verbs, and processkit 2.3.x exposes no idle-timeout hook there "
            "(idle monitoring rides the streaming output channel, which "
            "Supervisor does not drive). Passing it is a usage error until "
            "upstream support lands; use `run --idle-timeout` for a single "
            "command."
        ),
    )
    supervise_parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help="Kill each incarnation if it is still running after SECONDS.",
    )
    supervise_parser.add_argument(
        "--max-memory",
        dest="max_memory",
        type=_positive_int,
        default=None,
        metavar="BYTES",
        help="Cap each incarnation's whole process tree memory, in bytes.",
    )
    supervise_parser.add_argument(
        "--max-processes",
        dest="max_processes",
        type=_positive_int,
        default=None,
        metavar="N",
        help="Cap each incarnation's process-tree size.",
    )
    supervise_parser.add_argument(
        "--cpu-quota",
        dest="cpu_quota",
        type=_positive_float,
        default=None,
        metavar="FLOAT",
        help="Cap each incarnation's CPU usage as a fraction of one core.",
    )
    supervise_parser.add_argument(
        "--cpu-affinity",
        dest="cpu_affinity",
        type=_cpu_affinity,
        default=None,
        metavar="CPU[,CPU...]",
        help="Restrict each incarnation to logical CPU indices (Linux/Windows).",
    )
    supervise_parser.add_argument(
        "--create-no-window",
        dest="create_no_window",
        action="store_true",
        help="Do not create a console window for each incarnation (Windows).",
    )
    health_group = supervise_parser.add_mutually_exclusive_group()
    health_group.add_argument(
        "--health-port",
        dest="health_port",
        default=None,
        metavar="HOST:PORT",
        help="Treat a successful TCP connection to HOST:PORT as healthy.",
    )
    health_group.add_argument(
        "--health-http",
        dest="health_http",
        default=None,
        metavar="URL",
        help="Treat an HTTP(S) 2xx response from URL as healthy.",
    )
    supervise_parser.add_argument(
        "--health-interval",
        dest="health_interval",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help="Probe cadence (default: 5 seconds; requires a health probe).",
    )
    supervise_parser.add_argument(
        "--health-timeout",
        dest="health_timeout",
        type=_positive_float,
        default=None,
        metavar="SECONDS",
        help="Timeout for one health probe (default: 1 second; requires a health probe).",
    )
    supervise_parser.add_argument(
        "--env-clear",
        dest="env_clear",
        action="store_true",
        help="Start the child with an empty environment (Command.env_clear()).",
    )
    supervise_parser.add_argument(
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
    supervise_parser.add_argument(
        "--env",
        dest="env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Set/override a child environment variable (Command.env(...)). Repeatable.",
    )
    supervise_parser.add_argument(
        "--env-file",
        dest="env_file",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "Load KEY=VALUE entries from PATH; blank lines and # comments are ignored. "
            "Repeatable; later files win, and --env overrides every file."
        ),
    )
    supervise_parser.add_argument(
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
    doctor_parser.add_argument(
        "--json",
        dest="json",
        action="store_true",
        help="Emit the containment verdict as one machine-readable JSON object on stdout.",
    )
    return parser, run_parser, doctor_parser, supervise_parser


def _split_child_argv(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split ``argv`` on the first literal ``--``: everything before it is this
    wrapper's own flags (handed to `argparse`), everything after is the
    child's argv, untouched — including any further ``--`` in there."""
    argv = list(argv)
    if "--" not in argv:
        return argv, []
    index = argv.index("--")
    return argv[:index], argv[index + 1 :]
