"""`Supervisor` — the keep-alive loop: restart policies, the stop predicate,
backoff validation, and the failure-storm guard.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from processkit import Command, ProcessError, Supervisor
from processkit.testing import Reply, ScriptedRunner

PY = sys.executable


# --- restart policies + stop predicate --------------------------------------


def test_supervisor_never_restarts_on_success() -> None:
    outcome = Supervisor(Command(PY, ["-c", "pass"]), restart="never").run()
    assert outcome.restarts == 0
    assert outcome.final_result.is_success


def test_supervisor_exhausts_restarts_on_crash() -> None:
    async def scenario() -> object:
        crash = Command(PY, ["-c", "import sys; sys.exit(1)"])
        sup = Supervisor(
            crash, restart="on_crash", max_restarts=2, backoff_initial=0.01, backoff_factor=1.0
        )
        return await sup.arun()

    outcome = asyncio.run(scenario())
    assert outcome.restarts == 2  # type: ignore[attr-defined]
    assert outcome.stopped == "restarts_exhausted"  # type: ignore[attr-defined]


def test_supervisor_stop_when_predicate() -> None:
    calls: list[int] = []

    def stop(result: object) -> bool:
        calls.append(1)
        return True  # stop after the first run

    outcome = Supervisor(Command(PY, ["-c", "print('x')"]), restart="always", stop_when=stop).run()
    assert outcome.stopped == "predicate"
    assert outcome.restarts == 0
    assert calls  # the predicate was actually invoked


def test_supervisor_run_is_once() -> None:
    sup = Supervisor(Command(PY, ["-c", "pass"]), restart="never")
    sup.run()
    with pytest.raises(ProcessError):
        sup.run()


def test_sync_verb_in_stop_when_surfaces_clear_error() -> None:
    # Calling a synchronous verb from inside the supervisor's stop_when predicate
    # used to re-enter the tokio runtime and PANIC ("Cannot start a runtime from
    # within a runtime"); the panic was swallowed into "do not stop", so the
    # predicate silently never fired. It must now surface a clear `ProcessError`.
    captured: list[BaseException] = []

    def hook(unraisable: object) -> None:
        exc = getattr(unraisable, "exc_value", None)
        if isinstance(exc, BaseException):
            captured.append(exc)

    old_hook = sys.unraisablehook
    sys.unraisablehook = hook
    try:
        Supervisor(
            Command(PY, ["-c", "import sys; sys.exit(1)"]),
            restart="always",
            max_restarts=1,
            jitter=False,
            backoff_initial=0.001,
            stop_when=lambda r: Command(PY, ["-c", "pass"]).probe(),  # a SYNC verb
        ).run()
    finally:
        sys.unraisablehook = old_hook

    assert captured, "the predicate's error should reach the unraisable hook"
    assert all(isinstance(e, ProcessError) for e in captured), (
        f"expected ProcessError, got {[type(e).__name__ for e in captured]}"
    )
    assert "async context" in str(captured[0]), str(captured[0])


def test_reentrant_run_call_leaves_the_target_supervisor_usable() -> None:
    # A sync verb called reentrantly (here, another Supervisor's `run()` called
    # from inside a stop_when predicate running on the tokio runtime) must have
    # its reentrant-runtime check run BEFORE the target is taken out of self —
    # otherwise the failed call would still spend the handle for nothing.
    target = Supervisor(Command(PY, ["-c", "print('x')"]), restart="never")

    def reentrant_stop(_result: object) -> bool:
        with pytest.raises(ProcessError):
            target.run()  # re-enters the runtime: must raise, not spend `target`
        return True

    driver = Supervisor(
        Command(PY, ["-c", "print('y')"]),
        restart="always",
        stop_when=reentrant_stop,
    )
    outcome = driver.run()
    assert outcome.stopped == "predicate"
    # `target` must still be usable after the failed reentrant call.
    assert target.run().final_result.is_success


# --- backoff validation -----------------------------------------------------


def test_backoff_factor_validated_without_backoff_initial() -> None:
    # backoff_factor used to be silently ignored unless backoff_initial was also
    # passed. It is now applied/validated independently, so an out-of-range factor
    # raises even on its own.
    with pytest.raises(ValueError):
        Supervisor(Command(PY, ["-c", "pass"]), backoff_factor=0.5)


def test_backoff_factor_alone_is_accepted() -> None:
    outcome = Supervisor(Command(PY, ["-c", "pass"]), restart="never", backoff_factor=3.0).run()
    assert outcome.final_result.is_success


def test_max_backoff_kwarg_accepted_and_validated() -> None:
    # `max_backoff` has no other call site — pin its name against the stub (mypy)
    # and the Rust binding (a rename would raise TypeError, not ValueError) plus its
    # positive-duration check.
    outcome = Supervisor(Command(PY, ["-c", "pass"]), restart="never", max_backoff=30.0).run()
    assert outcome.final_result.is_success
    with pytest.raises(ValueError):
        Supervisor(Command(PY, ["-c", "pass"]), max_backoff=0.0)


# --- failure-storm guard ----------------------------------------------------


def test_supervisor_storm_pause_enables_guard() -> None:
    # With the failure-storm guard enabled (storm_pause set) + a low threshold, a
    # rapidly crash-looping command takes collective storm pauses (the field is no
    # longer permanently 0).
    out = Supervisor(
        Command(PY, ["-c", "import sys; sys.exit(1)"]),
        restart="always",
        max_restarts=30,
        backoff_initial=0.001,
        backoff_factor=1.0,
        jitter=False,
        storm_pause=0.01,
        failure_threshold=1.5,
        failure_decay=100.0,
    ).run()
    assert out.storm_pauses >= 1


def test_supervisor_storm_knobs_validate() -> None:
    base = Command(PY, ["-c", "pass"])
    with pytest.raises(ValueError):
        Supervisor(base, storm_pause=-1.0)
    with pytest.raises(ValueError):
        Supervisor(base, failure_threshold=0.0)
    with pytest.raises(ValueError):
        Supervisor(base, failure_decay=-1.0)


def test_supervisor_zero_failure_decay_is_accepted() -> None:
    # A zero half-life is a valid crate config (no history; every failure scores
    # 1.0) — the binding must not reject it.
    Supervisor(Command(PY, ["-c", "pass"]), restart="never", storm_pause=0.01, failure_decay=0.0)


# --- runner injection (C1) ---------------------------------------------------


def test_supervisor_accepts_injected_runner() -> None:
    # The command names a program that would fail to spawn for real
    # ("no-such-program"); with a ScriptedRunner injected, every incarnation is
    # driven through it instead of the real Runner — no real process runs, and
    # the scripted reply decides the outcome.
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("supervised"))
    outcome = Supervisor(
        Command("processkit-no-such-supervisor-program"), restart="never", runner=runner
    ).run()
    assert outcome.final_result.is_success
    assert outcome.final_result.stdout == "supervised"


def test_supervisor_rejects_unsupported_runner_object() -> None:
    with pytest.raises(TypeError):
        Supervisor(Command(PY, ["-c", "pass"]), runner=object())  # type: ignore[arg-type]
