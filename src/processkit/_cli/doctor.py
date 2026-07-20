"""The ``doctor`` subcommand: a read-only preflight probe of the containment
environment, implementing the exit-code contract documented in
`processkit._cli`'s module docstring.
"""

from __future__ import annotations

from collections.abc import Callable

from processkit import ProcessGroup, ResourceLimit, Unsupported
from processkit._cli.exit_codes import (
    EXIT_DOCTOR_LIMITS_UNAVAILABLE,
    EXIT_DOCTOR_NO_CONTAINMENT,
    EXIT_DOCTOR_OK,
    EXIT_DOCTOR_PROBE_ERROR,
)

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
    kernel actually grants in this environment. See `processkit._cli`'s
    module docstring for the exit-code contract this implements.

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
        print("  verdict: ERROR - could not determine containment availability (exit 4)")
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
        print("  verdict: ERROR - could not determine resource-limit availability (exit 4)")
        return EXIT_DOCTOR_PROBE_ERROR

    if unavailable:
        print(f"  resource limits        : unavailable {'; '.join(unavailable)}")
        _print_doctor_caveat()
        print("  verdict: DEGRADED - containment is enforced, but resource limits are not (exit 1)")
        return EXIT_DOCTOR_LIMITS_UNAVAILABLE

    print("  resource limits        : available")
    print("  verdict: OK - containment and resource limits are both available (exit 0)")
    return EXIT_DOCTOR_OK
