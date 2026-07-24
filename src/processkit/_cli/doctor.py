"""The ``doctor`` subcommand: a read-only preflight probe of the containment
environment, implementing the exit-code contract documented in
`processkit._cli`'s module docstring.
"""

from __future__ import annotations

import json
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
_DOCTOR_CAVEAT = (
    "--max-memory/--max-processes/--cpu-quota need a Windows Job Object or a Linux "
    "cgroup-v2 root; the kernel typically refuses them inside containers, systemd user "
    "sessions, and non-root cgroups, and always on macOS "
    "(docs/cli.md#resource-limits-hard-cap-or-best-effort)."
)
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


def _doctor_json_payload(
    *,
    mechanism: str,
    verdict: str,
    exit_code: int,
    resource_limits: dict[str, bool],
    error_probe_failures: list[str] | None = None,
) -> dict[str, object]:
    """Assemble the stable, machine-readable ``doctor --json`` report.

    ``error_probe_failures`` is present only when an operational probe error
    prevents a definitive verdict. The resource-limit fields remain booleans
    in every result: ``False`` means the controller was not confirmed
    available, including when the containment-mechanism probe itself failed.
    """
    payload: dict[str, object] = {
        "mechanism": mechanism,
        "verdict": verdict,
        "exit_code": exit_code,
        "resource_limits": resource_limits,
        "caveat": _DOCTOR_CAVEAT,
    }
    if error_probe_failures is not None:
        payload["error_probe_failures"] = error_probe_failures
    return payload


def _emit_doctor_json(payload: dict[str, object]) -> None:
    """Write one complete ``doctor --json`` payload to stdout."""
    print(json.dumps(payload))


def _print_doctor_caveat() -> None:
    print(f"  note: {_DOCTOR_CAVEAT}")


def _doctor(json_output: bool = False) -> int:
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
    if not json_output:
        print("processkit doctor")
    try:
        plain_group = ProcessGroup()
    except (ResourceLimit, Unsupported) as exc:
        if json_output:
            _emit_doctor_json(
                _doctor_json_payload(
                    mechanism="unavailable",
                    verdict="UNAVAILABLE",
                    exit_code=EXIT_DOCTOR_NO_CONTAINMENT,
                    resource_limits={
                        "max_memory": False,
                        "max_processes": False,
                        "cpu_quota": False,
                    },
                )
            )
        else:
            print(f"  containment mechanism : unavailable ({exc})")
            print("  resource limits        : unavailable (no containment mechanism to test)")
            _print_doctor_caveat()
            print("  verdict: UNAVAILABLE - no containment mechanism in this environment (exit 3)")
        return EXIT_DOCTOR_NO_CONTAINMENT
    except OSError as exc:
        if json_output:
            _emit_doctor_json(
                _doctor_json_payload(
                    mechanism="unknown",
                    verdict="ERROR",
                    exit_code=EXIT_DOCTOR_PROBE_ERROR,
                    resource_limits={
                        "max_memory": False,
                        "max_processes": False,
                        "cpu_quota": False,
                    },
                    error_probe_failures=[f"containment mechanism ({exc})"],
                )
            )
        else:
            print(f"  containment mechanism : error probing ({exc})")
            print("  resource limits        : unknown (mechanism probe failed)")
            print("  verdict: ERROR - could not determine containment availability (exit 4)")
        return EXIT_DOCTOR_PROBE_ERROR

    mechanism = str(plain_group.mechanism)
    if not json_output:
        print(f"  containment mechanism : {mechanism}")
    del plain_group  # drop the throwaway probe before the (separate) limits probes

    # Probe each of the three resource-limit controllers independently: on
    # Linux cgroup-v2 they are separate controllers that can be unavailable
    # one without the others, so "available" must mean all three, not just
    # the first one tried.
    resource_limits = {
        "max_memory": True,
        "max_processes": True,
        "cpu_quota": True,
    }
    flag_to_resource_limit = {
        "--max-memory": "max_memory",
        "--max-processes": "max_processes",
        "--cpu-quota": "cpu_quota",
    }
    unavailable: list[str] = []
    probe_errors: list[str] = []
    for flag, construct in _DOCTOR_LIMIT_PROBES:
        try:
            construct()
        except (ResourceLimit, Unsupported) as exc:
            resource_limits[flag_to_resource_limit[flag]] = False
            unavailable.append(f"{flag} ({exc})")
        except OSError as exc:
            resource_limits[flag_to_resource_limit[flag]] = False
            probe_errors.append(f"{flag} ({exc})")

    if probe_errors:
        if json_output:
            _emit_doctor_json(
                _doctor_json_payload(
                    mechanism=mechanism,
                    verdict="ERROR",
                    exit_code=EXIT_DOCTOR_PROBE_ERROR,
                    resource_limits=resource_limits,
                    error_probe_failures=probe_errors,
                )
            )
        else:
            print(f"  resource limits        : error probing {'; '.join(probe_errors)}")
            if unavailable:
                print(f"  resource limits        : also unavailable {'; '.join(unavailable)}")
            _print_doctor_caveat()
            print("  verdict: ERROR - could not determine resource-limit availability (exit 4)")
        return EXIT_DOCTOR_PROBE_ERROR

    if unavailable:
        if json_output:
            _emit_doctor_json(
                _doctor_json_payload(
                    mechanism=mechanism,
                    verdict="DEGRADED",
                    exit_code=EXIT_DOCTOR_LIMITS_UNAVAILABLE,
                    resource_limits=resource_limits,
                )
            )
        else:
            print(f"  resource limits        : unavailable {'; '.join(unavailable)}")
            _print_doctor_caveat()
            print(
                "  verdict: DEGRADED - containment is enforced, but resource limits are not "
                "(exit 1)"
            )
        return EXIT_DOCTOR_LIMITS_UNAVAILABLE

    if json_output:
        _emit_doctor_json(
            _doctor_json_payload(
                mechanism=mechanism,
                verdict="OK",
                exit_code=EXIT_DOCTOR_OK,
                resource_limits=resource_limits,
            )
        )
    else:
        print("  resource limits        : available")
        print("  verdict: OK - containment and resource limits are both available (exit 0)")
    return EXIT_DOCTOR_OK
