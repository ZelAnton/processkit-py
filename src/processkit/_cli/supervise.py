"""The ``supervise`` subcommand: keep a command alive through `Supervisor`,
implementing the exit-code contract documented in `processkit._cli`'s module
docstring.
"""

from __future__ import annotations

import argparse
import http.client
import signal
import socket
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
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
from processkit._cli.common import _apply_environment, _fail, _parse_environment
from processkit._cli.exit_codes import (
    EXIT_SIGNAL_BASE,
    EXIT_SUPERVISE_GAVE_UP,
    EXIT_SUPERVISE_INTERNAL_ERROR,
    EXIT_SUPERVISE_RESTARTS_EXHAUSTED,
    EXIT_TIMEOUT,
)


class _SupervisorKwargs(TypedDict, total=False):
    restart: Literal["always", "on_crash", "never"]
    max_restarts: int
    backoff_initial: float
    backoff_factor: float
    max_backoff: float
    jitter: bool
    health_check: Callable[[], bool]
    health_check_interval: float
    max_memory: int
    max_processes: int
    cpu_quota: float


def _parse_health_port(parser: argparse.ArgumentParser, endpoint: str) -> tuple[str, int]:
    if endpoint.startswith("["):
        closing = endpoint.find("]")
        if closing < 0 or endpoint[closing + 1 : closing + 2] != ":":
            parser.error("--health-port must be HOST:PORT (bracket IPv6 literals)")
        host = endpoint[1:closing]
        raw_port = endpoint[closing + 2 :]
    else:
        host, separator, raw_port = endpoint.rpartition(":")
        if not separator or ":" in host:
            parser.error("--health-port must be HOST:PORT (bracket IPv6 literals)")
    if not host:
        parser.error("--health-port host must not be empty")
    try:
        port = int(raw_port)
    except ValueError:
        parser.error("--health-port port must be an integer from 1 to 65535")
    if not 1 <= port <= 65535:
        parser.error("--health-port port must be an integer from 1 to 65535")
    return host, port


def _health_probe(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> Callable[[], bool] | None:
    if args.health_port is None and args.health_http is None:
        if args.health_interval is not None or args.health_timeout is not None:
            parser.error("--health-interval/--health-timeout requires a health probe")
        return None

    timeout = 1.0 if args.health_timeout is None else args.health_timeout
    if args.health_port is not None:
        host, port = _parse_health_port(parser, args.health_port)

        def probe_port() -> bool:
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return True
            except (OSError, ValueError):
                return False

        return probe_port

    url = args.health_http
    assert isinstance(url, str)
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        parser.error("--health-http must be a valid absolute HTTP(S) URL")
    if parsed.scheme not in {"http", "https"} or not hostname:
        parser.error("--health-http must be an absolute http:// or https:// URL")

    def probe_http() -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                status = response.status
                return isinstance(status, int) and 200 <= status < 300
        except (OSError, ValueError, http.client.HTTPException):
            return False

    return probe_http


def _supervise(
    supervise_parser: argparse.ArgumentParser, args: argparse.Namespace, child_argv: list[str]
) -> int:
    """Run ``child_argv`` under `Supervisor` and map its outcome to CLI codes."""
    if args.backoff_factor is not None and args.backoff_factor < 1:
        supervise_parser.error("--backoff-factor must be at least 1")
    if args.idle_timeout is not None:
        # The flag exists for parity with `run` (see parser.py), but idle-timeout
        # is enforced only on the binding's streaming iterator — and each
        # supervised incarnation runs through Supervisor's one-shot verbs
        # (`output_string()` / `start().finish()`), which processkit 2.3.x gives
        # no idle-timeout hook. Rejecting it loudly (a usage error, exit 2) is the
        # honest handling until upstream Supervisor support lands — never a
        # silently-ignored flag. `Command.idle_timeout()`'s own docstring records
        # the same one-shot/Supervisor gap.
        supervise_parser.error(
            "--idle-timeout is not yet supported under supervise: each incarnation "
            "runs through Supervisor's one-shot verbs, for which processkit 2.3.x "
            "exposes no idle-timeout hook (idle monitoring rides the streaming "
            "output channel Supervisor does not drive). Use `run --idle-timeout` "
            "for a single command."
        )

    health_probe = _health_probe(supervise_parser, args)

    env_pairs = _parse_environment(supervise_parser, args.env_file, args.env)
    program, *rest = child_argv

    try:
        # Stdin is inherited exactly like `run`. Stdout/stderr can't be: `Supervisor`
        # requires a piped stdout to capture each incarnation's result (to evaluate
        # the restart policy and populate `final_result`) — a non-piped stdout
        # errors every incarnation. Stay piped (the `Command` default) and tee every
        # decoded line straight through to this process's own inherited stdout/
        # stderr instead, so output still streams live to the calling terminal.
        command = Command(program, rest).inherit_stdin()
        if sys.stdout is not None:
            command = command.stdout_tee(sys.stdout)
        if sys.stderr is not None:
            command = command.stderr_tee(sys.stderr)
        if args.timeout is not None:
            command = command.timeout(args.timeout)
        if args.create_no_window:
            command = command.create_no_window()
        if args.cpu_affinity is not None:
            command = command.cpu_affinity(args.cpu_affinity)
        # Keep the command configuration order identical to `run`: establish
        # the environment base first, then apply explicit overrides and cwd.
        command = _apply_environment(
            command,
            clear=args.env_clear,
            inherited=args.inherit_env,
            pairs=env_pairs,
            cwd=args.cwd,
        )

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
        if args.max_memory is not None:
            supervisor_kwargs["max_memory"] = args.max_memory
        if args.max_processes is not None:
            supervisor_kwargs["max_processes"] = args.max_processes
        if args.cpu_quota is not None:
            supervisor_kwargs["cpu_quota"] = args.cpu_quota
        if health_probe is not None:
            supervisor_kwargs["health_check"] = health_probe
            supervisor_kwargs["health_check_interval"] = (
                5.0 if args.health_interval is None else args.health_interval
            )

        try:
            outcome = Supervisor(command, **supervisor_kwargs).run()
        except (ResourceLimit, Unsupported) as exc:
            limits_requested = (
                args.max_memory is not None
                or args.max_processes is not None
                or args.cpu_quota is not None
            )
            if not limits_requested:
                raise
            _fail(
                f"requested resource limits are not supported in this environment "
                f"({exc}); supervising contained, but uncapped."
            )
            supervisor_kwargs.pop("max_memory", None)
            supervisor_kwargs.pop("max_processes", None)
            supervisor_kwargs.pop("cpu_quota", None)
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

    if outcome.stopped in {"policy_satisfied", "predicate", "unhealthy"}:
        result = outcome.final_result
        if result.timed_out:
            _fail(f"{program!r} timed out after {args.timeout}s")
            return EXIT_TIMEOUT
        # A signal-killed last incarnation has no `.code` (mirrors `_run`'s own
        # `128 + signal` handling) — report the signal, not a generic internal
        # error, so this stays distinguishable from a genuine internal failure.
        if result.signal is not None:
            _fail(f"{program!r} was killed by signal {result.signal}")
            return EXIT_SIGNAL_BASE + result.signal
        if result.code is None:
            if outcome.stopped == "unhealthy":
                _fail(f"{program!r} failed its health check")
                return EXIT_SUPERVISE_INTERNAL_ERROR
            _fail(f"{program!r} produced no exit code")
            return EXIT_SUPERVISE_INTERNAL_ERROR
        return result.code
    if outcome.stopped == "restarts_exhausted":
        return EXIT_SUPERVISE_RESTARTS_EXHAUSTED
    if outcome.stopped == "gave_up":
        return EXIT_SUPERVISE_GAVE_UP

    _fail(f"{program!r} produced an unknown supervision outcome")
    return EXIT_SUPERVISE_INTERNAL_ERROR
