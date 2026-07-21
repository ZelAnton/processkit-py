"""The ``run`` subcommand: spawn a child inside a kill-on-exit `ProcessGroup`
with inherited stdio, implementing the exit-code contract documented in
`processkit._cli`'s module docstring.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import signal
import sys

from processkit import (
    Command,
    PermissionDenied,
    ProcessError,
    ProcessGroup,
    ProcessNotFound,
    ResourceLimit,
    RunProfile,
    Unsupported,
)
from processkit._cli.exit_codes import (
    EXIT_INTERNAL_ERROR,
    EXIT_NOT_EXECUTABLE,
    EXIT_NOT_FOUND,
    EXIT_SIGNAL_BASE,
    EXIT_TIMEOUT,
)
from processkit._cli.parser import PROFILE_STDERR_MARKER

#: Sampling period for ``--profile``'s `RunningProcess.profile()` call. Not
#: exposed as its own flag (see `PROFILE_STDERR_MARKER`'s docstring in
#: `_cli/parser.py` for why `--profile` stays a single flag): fine enough
#: granularity for the short-lived CI-step commands this wrapper targets,
#: without flooding a long-running one with samples.
_PROFILE_SAMPLE_INTERVAL_SECONDS = 0.1


def _fail(message: str) -> None:
    print(f"processkit: {message}", file=sys.stderr)


def _profile_payload(profile: RunProfile) -> dict[str, object]:
    """The JSON-serializable shape emitted by ``--profile``: `RunProfile`'s own
    resource-usage fields, plus the run's outcome (`code`/`signal`/
    `timed_out`) so a caller does not need a second source for that. Fields
    that need a Windows Job Object / Linux cgroup-v2 the environment doesn't
    have serialize as JSON `null` (`RunProfile` already reports them as
    `None` in that case) rather than the command failing."""
    return {
        "duration_seconds": profile.duration_seconds,
        "cpu_time_seconds": profile.cpu_time_seconds,
        "peak_memory_bytes": profile.peak_memory_bytes,
        "avg_cpu_cores": profile.avg_cpu_cores,
        "samples": profile.samples,
        "code": profile.code,
        "signal": profile.signal,
        "timed_out": profile.timed_out,
    }


def _emit_profile(target: object, profile: RunProfile) -> int | None:
    """Emit `profile` as one line of JSON to stderr (``target is
    PROFILE_STDERR_MARKER``) or write it to the path `target` names. Called
    only after the child has already exited (`proc.profile(...)` blocks until
    then, like `proc.outcome()`), so this can never interleave with the
    child's own inherited stdio. Returns an exit code to abort with if
    writing to a file fails (never a raw traceback), `None` on success."""
    text = json.dumps(_profile_payload(profile))
    if target is PROFILE_STDERR_MARKER:
        print(text, file=sys.stderr)
        return None
    assert isinstance(target, str)  # the only other value argparse can produce here
    try:
        pathlib.Path(target).write_text(text + "\n", encoding="utf-8")
    except OSError as exc:
        _fail(f"could not write --profile output to {target!r}: {exc}")
        return EXIT_INTERNAL_ERROR
    return None


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
    if args.create_no_window:
        command = command.create_no_window()
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

    profile_requested = args.profile is not None
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
            if profile_requested:
                # profile() blocks until the child exits, exactly like
                # outcome() — it is a superset of it (RunProfile.outcome).
                profile = proc.profile(_PROFILE_SAMPLE_INTERVAL_SECONDS)
                outcome = profile.outcome
            else:
                profile = None
                outcome = proc.outcome()
    except KeyboardInterrupt:
        _fail("interrupted")
        return EXIT_SIGNAL_BASE + signal.SIGINT
    except ProcessError as exc:  # defensive: no known path raises here, but never a traceback
        _fail(f"{program!r} failed: {exc}")
        return EXIT_INTERNAL_ERROR

    if profile is not None:
        # Emitted once the child has fully exited (never interleaved with its
        # already-inherited, already-flushed stdio) and regardless of how the
        # run ended (normal exit, timeout, signal) — the caller gets the
        # profile whichever exit code follows below.
        profile_error_code = _emit_profile(args.profile, profile)
        if profile_error_code is not None:
            return profile_error_code

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
