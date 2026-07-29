"""The ``run`` subcommand: spawn a child inside a kill-on-exit `ProcessGroup`.

Stdio is inherited by default; output-observing modes such as idle monitoring,
capture limits, and PTY relay use the binding's managed streams instead. Exit
codes follow the contract documented in `processkit._cli`'s module docstring.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import signal

from processkit import (
    Command,
    IdleTimeout,
    Outcome,
    PermissionDenied,
    ProcessError,
    ProcessGroup,
    ProcessNotFound,
    ResourceLimit,
    RunningProcess,
    RunProfile,
    Unsupported,
)
from processkit._cli.common import _apply_environment, _fail, _parse_environment
from processkit._cli.exit_codes import (
    EXIT_IDLE_TIMEOUT,
    EXIT_INTERNAL_ERROR,
    EXIT_NOT_EXECUTABLE,
    EXIT_NOT_FOUND,
    EXIT_SIGNAL_BASE,
    EXIT_TIMEOUT,
)
from processkit._cli.output import emit_stderr, emit_stdout
from processkit._cli.parser import PROFILE_STDERR_MARKER

#: Sampling period for ``--profile``'s `RunningProcess.profile()` call. Not
#: exposed as its own flag (see `PROFILE_STDERR_MARKER`'s docstring in
#: `_cli/parser.py` for why `--profile` stays a single flag): fine enough
#: granularity for the short-lived CI-step commands this wrapper targets,
#: without flooding a long-running one with samples.
_PROFILE_SAMPLE_INTERVAL_SECONDS = 0.1


async def _drive_streaming(proc: RunningProcess) -> Outcome:
    """Relay the child's managed output stream until the process exits.

    The binding's iterator enforces any configured idle timeout and fail-loud
    output limit while this pump is active. It also carries the merged PTY
    stream when PTY mode is configured. Raises `IdleTimeout` if the child goes
    silent past its window; other stream failures propagate as `ProcessError`.

    This is a *decoded, line-oriented* re-emit, not the raw byte passthrough
    ``run`` uses by default: idle monitoring rides the per-line output channel,
    so ``--idle-timeout`` pipes stdout/stderr and prints each `OutputEvent` line
    with a trailing newline. Fidelity therefore differs from inherited stdio
    (UTF-8 decode, per-line framing, no TTY on the child's streams) — the
    documented trade for a working idle-timeout, taken only when the flag is set.
    """
    events = proc.output_events()
    async for event in events:
        if event.is_stderr:
            emit_stderr(event.text)
        else:
            emit_stdout(event.text)
    finished = await proc.afinish()
    return finished.outcome


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
        emit_stderr(text)
        return None
    assert isinstance(target, str)  # the only other value argparse can produce here
    try:
        pathlib.Path(target).write_text(text + "\n", encoding="utf-8")
    except OSError as exc:
        _fail(f"could not write --profile output to {target!r}: {exc}")
        return EXIT_INTERNAL_ERROR
    return None


def _run(
    run_parser: argparse.ArgumentParser, args: argparse.Namespace, child_argv: list[str]
) -> int:
    if args.timeout_grace is not None and args.timeout is None:
        run_parser.error("--timeout-grace requires --timeout")
    # `--idle-timeout` streams and re-emits piped output (see `_drive_streaming`);
    # `--profile` consumes the handle with a sampling `profile()` wait. The two
    # need incompatible consuming verbs on the one handle, so reject the combo up
    # front rather than silently letting one win.
    if args.idle_timeout is not None and args.profile is not None:
        run_parser.error("--idle-timeout cannot be combined with --profile")
    if args.output_limit is not None and args.profile is not None:
        run_parser.error("--output-limit cannot be combined with --profile")
    if args.output_limit is not None and args.stdout_file is not None:
        run_parser.error("--output-limit cannot be combined with --stdout-file")
    if args.idle_timeout is not None and args.stdout_file is not None:
        run_parser.error("--idle-timeout cannot be combined with --stdout-file")
    if (args.pty_cols is not None or args.pty_rows is not None) and not args.pty:
        run_parser.error("--pty-cols/--pty-rows requires --pty")
    if (args.pty_cols is None) != (args.pty_rows is None):
        run_parser.error("--pty-cols and --pty-rows must be provided together")
    if args.pty and args.profile is not None:
        run_parser.error("--pty cannot be combined with --profile")
    if args.pty and (args.stdout_file is not None or args.stderr_file is not None):
        run_parser.error("--pty cannot be combined with --stdout-file/--stderr-file")

    env_pairs = _parse_environment(run_parser, args.env_file, args.env)

    program, *rest = child_argv
    idle_requested = args.idle_timeout is not None
    streaming_requested = idle_requested or args.output_limit is not None or args.pty
    command = Command(program, rest)
    if args.pty:
        command = command.pty(cols=args.pty_cols, rows=args.pty_rows)
    else:
        command = command.inherit_stdin()
    if streaming_requested:
        # Idle monitoring rides the per-line output channel, so keep stdout/stderr
        # piped (the Command default) — `_drive_streaming` re-emits each line — rather
        # than inheriting raw. The output-limit path uses the same pump so its
        # fail-loud captured-byte ceiling is actually enforced.
        if idle_requested:
            assert args.idle_timeout is not None
            command = command.idle_timeout(args.idle_timeout)
    else:
        command = command.stdout("inherit")
    if args.stdout_file is not None:
        command = command.stdout_file(args.stdout_file)
    if args.stderr_file is not None:
        command = command.stderr_file(args.stderr_file)
    elif not streaming_requested:
        command = command.stderr("inherit")
    if args.output_limit is not None:
        command = command.output_limit(max_bytes=args.output_limit, on_overflow="error")
    if args.create_no_window:
        command = command.create_no_window()
    if args.kill_on_parent_death:
        command = command.kill_on_parent_death()
    if args.priority is not None:
        command = command.priority(args.priority)
    if args.io_priority is not None:
        class_name, level = args.io_priority
        command = command.io_priority(class_name, level=level)
    # Environment builders compose in a fixed order at spawn regardless of
    # call order (docs/commands.md#environment-and-sandboxing), but this is
    # still the natural reading order: clear/allow-list the base environment
    # first, then layer explicit overrides and the working directory on top.
    command = _apply_environment(
        command,
        clear=args.env_clear,
        inherited=args.inherit_env,
        pairs=env_pairs,
        cwd=args.cwd,
    )
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
        except OSError as exc2:
            # The fallback may encounter an operational containment error of
            # its own; distinguish it from unsupported requested limits.
            _fail(f"could not initialize containment in this environment: {exc2}")
            return EXIT_INTERNAL_ERROR
        _fail(
            f"requested resource limits are not supported in this environment "
            f"({exc}); running contained, but uncapped."
        )
    except OSError as exc:
        # This is an operational containment failure (for example, reading
        # cgroup state), not a definitive answer that limits are unsupported.
        _fail(f"could not initialize containment in this environment: {exc}")
        return EXIT_INTERNAL_ERROR

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
            if streaming_requested:
                # Relay the PTY stream, or stream + enforce the idle-timeout /
                # output limit (see `_drive_streaming`). The surrounding `with group:`
                # still shuts the tree down on an early return or fail-loud overflow.
                profile = None
                try:
                    outcome = asyncio.run(_drive_streaming(proc))
                except IdleTimeout:
                    _fail(f"{program!r} was idle for {args.idle_timeout}s (no output line)")
                    return EXIT_IDLE_TIMEOUT
            elif profile_requested:
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
    except ProcessError as exc:
        # Managed streaming reports fail-loud output-limit and PTY failures
        # here; other binding failures remain defensive internal errors.
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
