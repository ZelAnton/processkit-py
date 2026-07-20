"""The ``run`` subcommand: spawn a child inside a kill-on-exit `ProcessGroup`
with inherited stdio, implementing the exit-code contract documented in
`processkit._cli`'s module docstring.
"""

from __future__ import annotations

import argparse
import signal
import sys

from processkit import (
    Command,
    PermissionDenied,
    ProcessError,
    ProcessGroup,
    ProcessNotFound,
    ResourceLimit,
    Unsupported,
)
from processkit._cli.exit_codes import (
    EXIT_INTERNAL_ERROR,
    EXIT_NOT_EXECUTABLE,
    EXIT_NOT_FOUND,
    EXIT_SIGNAL_BASE,
    EXIT_TIMEOUT,
)


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
    command = Command(program, rest).inherit_stdin().stdout("inherit").stderr("inherit")
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
