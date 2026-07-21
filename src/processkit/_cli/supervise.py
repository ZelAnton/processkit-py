"""The ``supervise`` subcommand: keep a command alive through `Supervisor`,
implementing the exit-code contract documented in `processkit._cli`'s module
docstring.
"""

from __future__ import annotations

import argparse
import signal
import sys
from typing import Literal, TypedDict

from processkit import (
    Command,
    PermissionDenied,
    ProcessError,
    ProcessNotFound,
    ResourceLimit,
    Supervisor,
    Unsupported,
)
from processkit._cli.exit_codes import (
    EXIT_SIGNAL_BASE,
    EXIT_SUPERVISE_GAVE_UP,
    EXIT_SUPERVISE_INTERNAL_ERROR,
    EXIT_SUPERVISE_RESTARTS_EXHAUSTED,
)
from processkit._cli.run import _fail, _parse_env_flags


class _SupervisorKwargs(TypedDict, total=False):
    restart: Literal["always", "on_crash", "never"]
    max_restarts: int
    backoff_initial: float
    backoff_factor: float
    max_backoff: float
    jitter: bool


def _supervise(
    supervise_parser: argparse.ArgumentParser, args: argparse.Namespace, child_argv: list[str]
) -> int:
    """Run ``child_argv`` under `Supervisor` and map its outcome to CLI codes."""
    if args.backoff_factor is not None and args.backoff_factor < 1:
        supervise_parser.error("--backoff-factor must be at least 1")

    env_pairs = _parse_env_flags(supervise_parser, args.env)
    program, *rest = child_argv

    try:
        # Stdin is inherited exactly like `run`. Stdout/stderr can't be: `Supervisor`
        # requires a piped stdout to capture each incarnation's result (to evaluate
        # the restart policy and populate `final_result`) — a non-piped stdout
        # errors every incarnation. Stay piped (the `Command` default) and tee every
        # decoded line straight through to this process's own inherited stdout/
        # stderr instead, so output still streams live to the calling terminal.
        command = (
            Command(program, rest).inherit_stdin().stdout_tee(sys.stdout).stderr_tee(sys.stderr)
        )
        # Keep the command configuration order identical to `run`: establish
        # the environment base first, then apply explicit overrides and cwd.
        if args.env_clear:
            command = command.env_clear()
        if args.inherit_env:
            command = command.inherit_env(args.inherit_env)
        for key, value in env_pairs:
            command = command.env(key, value)
        if args.cwd is not None:
            command = command.cwd(args.cwd)

        supervisor_kwargs: _SupervisorKwargs = {}
        if args.restart is not None:
            supervisor_kwargs["restart"] = args.restart
        if args.max_restarts is not None:
            supervisor_kwargs["max_restarts"] = args.max_restarts
        if args.backoff_initial is not None:
            supervisor_kwargs["backoff_initial"] = args.backoff_initial
        if args.backoff_factor is not None:
            supervisor_kwargs["backoff_factor"] = args.backoff_factor
        if args.max_backoff is not None:
            supervisor_kwargs["max_backoff"] = args.max_backoff
        if args.no_jitter:
            supervisor_kwargs["jitter"] = False

        outcome = Supervisor(command, **supervisor_kwargs).run()
    except (ProcessNotFound, PermissionDenied, ResourceLimit, Unsupported) as exc:
        _fail(f"could not supervise {program!r}: {exc}")
        return EXIT_SUPERVISE_INTERNAL_ERROR
    except KeyboardInterrupt:
        _fail("interrupted")
        return EXIT_SIGNAL_BASE + signal.SIGINT
    except ProcessError as exc:
        _fail(f"{program!r} failed: {exc}")
        return EXIT_SUPERVISE_INTERNAL_ERROR

    if outcome.stopped in {"policy_satisfied", "predicate"}:
        result = outcome.final_result
        # A signal-killed last incarnation has no `.code` (mirrors `_run`'s own
        # `128 + signal` handling) — report the signal, not a generic internal
        # error, so this stays distinguishable from a genuine internal failure.
        if result.signal is not None:
            _fail(f"{program!r} was killed by signal {result.signal}")
            return EXIT_SIGNAL_BASE + result.signal
        if result.code is None:
            _fail(f"{program!r} produced no exit code")
            return EXIT_SUPERVISE_INTERNAL_ERROR
        return result.code
    if outcome.stopped == "restarts_exhausted":
        return EXIT_SUPERVISE_RESTARTS_EXHAUSTED
    if outcome.stopped == "gave_up":
        return EXIT_SUPERVISE_GAVE_UP

    _fail(f"{program!r} produced an unknown supervision outcome")
    return EXIT_SUPERVISE_INTERNAL_ERROR
