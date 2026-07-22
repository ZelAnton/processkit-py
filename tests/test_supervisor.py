"""`Supervisor` — the keep-alive loop: restart policies, the stop predicate,
backoff validation, and the failure-storm guard.
"""

from __future__ import annotations

import asyncio
import pickle

import pytest

from processkit import (
    Command,
    ProcessError,
    ProcessNotFound,
    ProcessResult,
    SupervisionOutcome,
    Supervisor,
)
from processkit.testing import Reply, ScriptedRunner

from .conftest import NO_SUCH_PROGRAM, PY

# --- restart policies + stop predicate --------------------------------------


def test_supervisor_never_restarts_on_success() -> None:
    outcome = Supervisor(Command(PY, ["-c", "pass"]), restart="never").run()
    assert outcome.restarts == 0
    assert outcome.final_result.is_success


def test_supervisor_on_crash_clean_exit_reports_policy_satisfied() -> None:
    # `stopped == "policy_satisfied"` was previously never observed by any
    # test: `restart="on_crash"` decides NOT to restart a clean (non-crash)
    # exit, which is exactly the policy-satisfied outcome (distinct from
    # "predicate" and "restarts_exhausted", the only two values pinned so far).
    outcome = Supervisor(Command(PY, ["-c", "pass"]), restart="on_crash").run()
    assert outcome.restarts == 0
    assert outcome.stopped == "policy_satisfied"
    assert outcome.final_result.is_success


def test_supervisor_exhausts_restarts_on_crash() -> None:
    async def scenario() -> SupervisionOutcome:
        crash = Command(PY, ["-c", "import sys; sys.exit(1)"])
        sup = Supervisor(
            crash, restart="on_crash", max_restarts=2, backoff_initial=0.01, backoff_factor=1.0
        )
        return await sup.arun()

    outcome = asyncio.run(scenario())
    assert outcome.restarts == 2
    assert outcome.stopped == "restarts_exhausted"


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
    # `run()` consumes the supervisor: a second call raises the typed
    # `ProcessError` with its stable message (pinned so the frozen-Mutex rework
    # in T-100 keeps returning the same clean error, not a raw borrow error).
    sup = Supervisor(Command(PY, ["-c", "pass"]), restart="never")
    sup.run()
    with pytest.raises(ProcessError, match="already been run"):
        sup.run()


def test_supervisor_arun_is_once() -> None:
    # `arun()` is one-shot exactly like `run()`: awaiting once spends the
    # supervisor, and any later `arun()`/`run()` raises the same typed error.
    async def scenario() -> None:
        sup = Supervisor(Command(PY, ["-c", "pass"]), restart="never")
        await sup.arun()
        with pytest.raises(ProcessError, match="already been run"):
            await sup.arun()
        # A cross-verb second call (sync after async) is spent just the same.
        with pytest.raises(ProcessError, match="already been run"):
            sup.run()

    asyncio.run(scenario())


def test_sync_verb_in_stop_when_surfaces_clear_error() -> None:
    # Calling a synchronous verb from inside the supervisor's stop_when predicate
    # re-enters the tokio runtime; the reentrancy guard raises a clear
    # `ProcessError`. That error must now abort supervision and reach the caller
    # — no longer swallowed into "do not stop" (and merely reported to the
    # unraisable hook) while the loop kept restarting.
    with pytest.raises(ProcessError, match="async context"):
        Supervisor(
            Command(PY, ["-c", "import sys; sys.exit(1)"]),
            restart="always",
            max_restarts=1,
            jitter=False,
            backoff_initial=0.001,
            stop_when=lambda r: Command(PY, ["-c", "pass"]).probe(),  # a SYNC verb
        ).run()


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


def test_supervisor_stop_when_raising_predicate_propagates_and_stops() -> None:
    # A stop_when predicate that raises aborts supervision with that error instead
    # of being swallowed into "do not stop" and looping to max_restarts. It is
    # consulted once (after the first run) and stops there — no further restarts,
    # no background work.
    runs: list[int] = []

    def stop(_result: object) -> bool:
        runs.append(1)
        raise ValueError("predicate exploded")

    runner = ScriptedRunner()
    runner.fallback(Reply.ok("x"))
    with pytest.raises(ValueError, match="predicate exploded"):
        Supervisor(
            Command(NO_SUCH_PROGRAM),
            restart="always",
            # Safety net: a broken binding that swallowed the error would loop to
            # here (and fail the count assertion) rather than hang the suite.
            max_restarts=5,
            backoff_initial=0.001,
            backoff_factor=1.0,
            jitter=False,
            stop_when=stop,
            runner=runner,
        ).run()

    assert runs == [1], "predicate consulted once then stopped — no restart loop"


def test_supervisor_stop_when_non_bool_predicate_propagates() -> None:
    # A non-bool return is as undecidable as a raise: it must surface a TypeError,
    # not be coerced to "do not stop".
    def stop(_result: object) -> bool:
        return "not a bool"  # type: ignore[return-value]

    runner = ScriptedRunner()
    runner.fallback(Reply.ok("x"))
    with pytest.raises(TypeError):
        Supervisor(
            Command(NO_SUCH_PROGRAM),
            restart="always",
            max_restarts=3,
            backoff_initial=0.001,
            backoff_factor=1.0,
            jitter=False,
            stop_when=stop,
            runner=runner,
        ).run()


def test_supervisor_arun_stop_when_raising_predicate_propagates() -> None:
    # The async supervision loop propagates a raising stop_when just like the sync
    # loop — the error is not confined to the unraisable hook.
    def stop(_result: object) -> bool:
        raise RuntimeError("async predicate bug")

    async def scenario() -> None:
        runner = ScriptedRunner()
        runner.fallback(Reply.ok("x"))
        await Supervisor(
            Command(NO_SUCH_PROGRAM),
            restart="always",
            max_restarts=3,
            backoff_initial=0.001,
            backoff_factor=1.0,
            jitter=False,
            stop_when=stop,
            runner=runner,
        ).arun()

    with pytest.raises(RuntimeError, match="async predicate bug"):
        asyncio.run(scenario())


def test_concurrent_supervisions_do_not_mix_predicate_errors() -> None:
    # Two-plus supervisions run concurrently, each with a stop_when that raises a
    # DISTINCT error. Each `arun()` must surface its OWN error, never a sibling's
    # — per-supervisor error slots keep concurrent runs isolated.
    async def one(tag: str) -> str:
        def stop(_result: object) -> bool:
            raise ValueError(tag)  # closes over this run's own tag

        runner = ScriptedRunner()
        runner.fallback(Reply.ok("x"))
        sup = Supervisor(
            Command(NO_SUCH_PROGRAM),
            restart="always",
            max_restarts=3,
            backoff_initial=0.001,
            backoff_factor=1.0,
            jitter=False,
            stop_when=stop,
            runner=runner,
        )
        try:
            await sup.arun()
        except ValueError as exc:
            return str(exc)
        return "no error"

    async def scenario() -> list[str]:
        return await asyncio.gather(*(one(f"sup-{i}") for i in range(8)))

    results = sorted(asyncio.run(scenario()))
    assert results == sorted(f"sup-{i}" for i in range(8))


# --- give_up_when (permanent-failure classifier) ----------------------------


def test_supervisor_give_up_when_stops_a_permanent_crash() -> None:
    # The headline behavior: a `give_up_when` classifier that recognizes a crash
    # as permanent stops supervision after the FIRST such crash with
    # `stopped == "gave_up"` (0 restarts), instead of an unbounded restart loop.
    # Driven through a ScriptedRunner — no real spawn.
    seen: list[object] = []

    def give_up(attempt: object) -> bool:
        seen.append(attempt)
        # A crashed run that produced a result is handed the `ProcessResult`.
        return isinstance(attempt, ProcessResult) and attempt.code == 13

    runner = ScriptedRunner()
    runner.fallback(Reply.fail(13, "boom"))
    outcome = Supervisor(
        Command(NO_SUCH_PROGRAM),
        restart="always",
        # Safety net: without give_up this stops here (not looping forever), so a
        # broken binding fails the assertions below instead of hanging the suite.
        max_restarts=5,
        backoff_initial=0.001,
        backoff_factor=1.0,
        jitter=False,
        give_up_when=give_up,
        runner=runner,
    ).run()

    assert outcome.stopped == "gave_up"
    assert outcome.restarts == 0  # gave up on the first crash — no restart loop
    assert outcome.final_result.code == 13
    # The classifier was consulted with the crashed run's `ProcessResult`.
    assert seen and isinstance(seen[0], ProcessResult)


def test_supervisor_give_up_when_ignores_an_unrecognized_crash() -> None:
    # The verdict is consulted per crash and a False answer is respected: an
    # unrecognized crash still restarts (here, to exhaustion) and never
    # spuriously reports "gave_up".
    def give_up(attempt: object) -> bool:
        return isinstance(attempt, ProcessResult) and attempt.code == 13

    runner = ScriptedRunner()
    runner.fallback(Reply.fail(1, "different"))  # code 1, not the classified 13
    outcome = Supervisor(
        Command(NO_SUCH_PROGRAM),
        restart="always",
        max_restarts=2,
        backoff_initial=0.001,
        backoff_factor=1.0,
        jitter=False,
        give_up_when=give_up,
        runner=runner,
    ).run()

    assert outcome.stopped == "restarts_exhausted"
    assert outcome.restarts == 2


def test_supervisor_give_up_when_classifies_a_failed_spawn() -> None:
    # The `Failed` arm: a launch that never produced a result (a missing binary
    # -> ENOENT) is handed the mapped `ProcessError` subclass, so
    # `isinstance(attempt, ProcessNotFound)` recognizes the unrecoverable case.
    # A launch-failure verdict has no result to report, so it surfaces the
    # classified error directly from run() (not `stopped == "gave_up"`), but it
    # still gives up on the first attempt instead of restarting forever.
    seen: list[object] = []

    def give_up(attempt: object) -> bool:
        seen.append(attempt)
        return isinstance(attempt, ProcessNotFound)

    with pytest.raises(ProcessNotFound):
        Supervisor(
            Command(NO_SUCH_PROGRAM),
            restart="always",
            max_restarts=3,  # safety net (see the crash test) — not reached here
            backoff_initial=0.001,
            backoff_factor=1.0,
            jitter=False,
            give_up_when=give_up,
        ).run()

    # Consulted exactly once, with the mapped exception -> gave up at the first
    # failure (no restart loop), not after climbing to `max_restarts`.
    assert len(seen) == 1
    assert isinstance(seen[0], ProcessNotFound)


def test_supervisor_give_up_when_raising_classifier_propagates_and_stops() -> None:
    # A classifier that raises must NOT silently keep restarting: it aborts
    # supervision with that error, consulted exactly once (on the first crash) —
    # no restart loop, mirroring `stop_when`'s own contract.
    seen: list[int] = []

    def boom(_attempt: object) -> bool:
        seen.append(1)
        raise RuntimeError("classifier bug")

    runner = ScriptedRunner()
    runner.fallback(Reply.fail(7, "crash"))
    with pytest.raises(RuntimeError, match="classifier bug"):
        Supervisor(
            Command(NO_SUCH_PROGRAM),
            restart="always",
            # Safety net (see the crash test): a broken binding would loop to here
            # rather than hang the suite.
            max_restarts=5,
            backoff_initial=0.001,
            backoff_factor=1.0,
            jitter=False,
            give_up_when=boom,
            runner=runner,
        ).run()

    assert seen == [1], "classifier consulted once then stopped — no restart loop"


def test_supervisor_give_up_when_non_bool_classifier_propagates() -> None:
    # A non-bool classifier verdict is undecidable ground for restarting — it must
    # surface a TypeError rather than read as "not permanent".
    def give_up(_attempt: object) -> bool:
        return 1  # type: ignore[return-value]

    runner = ScriptedRunner()
    runner.fallback(Reply.fail(7, "crash"))
    with pytest.raises(TypeError):
        Supervisor(
            Command(NO_SUCH_PROGRAM),
            restart="always",
            max_restarts=3,
            backoff_initial=0.001,
            backoff_factor=1.0,
            jitter=False,
            give_up_when=give_up,
            runner=runner,
        ).run()


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


def test_supervisor_jitter_true_smoke() -> None:
    # `jitter=True` is the crate default, but every other test in this file
    # sets `jitter=False` for deterministic timing — leaving the default path
    # itself never exercised. A tiny bound keeps this fast regardless of the
    # random jitter added to each backoff.
    outcome = Supervisor(
        Command(PY, ["-c", "import sys; sys.exit(1)"]),
        restart="on_crash",
        max_restarts=2,
        backoff_initial=0.01,
        backoff_factor=1.0,
        jitter=True,
    ).run()
    assert outcome.restarts == 2
    assert outcome.stopped == "restarts_exhausted"


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


# --- output cap (C7 batch A) --------------------------------------------------


def test_supervisor_capture_max_lines_caps_final_result_output() -> None:
    code = "\n".join(f"print('line{i}')" for i in range(20))
    outcome = Supervisor(Command(PY, ["-c", code]), restart="never", capture_max_lines=2).run()
    assert outcome.final_result.truncated
    # drop_oldest (the default) keeps the most recent lines — the tail.
    assert "line19" in outcome.final_result.stdout
    assert "line0" not in outcome.final_result.stdout


def test_supervisor_capture_on_overflow_alone_requires_a_cap_size() -> None:
    # Mirrors Command.output_limit's own validation: setting any of the three
    # capture_* kwargs without a cap size is a clear misuse, not a silent no-op.
    with pytest.raises(ValueError, match="capture"):
        Supervisor(Command(PY, ["-c", "pass"]), capture_on_overflow="error")


def test_supervisor_capture_max_bytes_widens_or_bounds_capture() -> None:
    # A construction-time smoke test: max_bytes alone is accepted (no ValueError)
    # and the supervisor still runs to completion.
    outcome = Supervisor(
        Command(PY, ["-c", "print('x' * 100)"]), restart="never", capture_max_bytes=10
    ).run()
    assert outcome.final_result.truncated


# --- runner injection (C1) ---------------------------------------------------


def test_supervisor_accepts_injected_runner() -> None:
    # The command names a program that would fail to spawn for real
    # ("no-such-program"); with a ScriptedRunner injected, every incarnation is
    # driven through it instead of the real Runner — no real process runs, and
    # the scripted reply decides the outcome.
    runner = ScriptedRunner()
    runner.fallback(Reply.ok("supervised"))
    outcome = Supervisor(Command(NO_SUCH_PROGRAM), restart="never", runner=runner).run()
    assert outcome.final_result.is_success
    assert outcome.final_result.stdout == "supervised"


def test_supervisor_rejects_unsupported_runner_object() -> None:
    with pytest.raises(TypeError):
        Supervisor(Command(PY, ["-c", "pass"]), runner=object())  # type: ignore[arg-type]


# --- liveness health checks (T-143) -----------------------------------------


def test_supervisor_health_check_healthy_probe_never_force_kills() -> None:
    # A probe that always reports healthy never trips the liveness force-kill:
    # the child runs to its natural (clean) exit, `liveness_kills` stays 0, and
    # `stopped` is the ordinary policy outcome. Uses a real short-lived child so
    # the probe is genuinely consulted on its cadence (a scripted bulk reply would
    # resolve before the first interval); the wide sleep-vs-interval margin keeps
    # it robust, and an always-True probe can never trip regardless of timing.
    probes: list[int] = []

    def healthy() -> bool:
        probes.append(1)
        return True

    outcome = Supervisor(
        Command(PY, ["-c", "import time; time.sleep(0.2)"]),
        restart="never",
        health_check=healthy,
        health_check_interval=0.02,
    ).run()
    assert outcome.liveness_kills == 0
    assert outcome.stopped == "policy_satisfied"
    assert outcome.final_result.is_success
    assert probes, "the liveness probe was consulted at least once"


def test_supervisor_health_check_never_policy_reports_unhealthy() -> None:
    # A probe that fails its threshold of consecutive checks force-kills the wedged
    # incarnation. Under restart="never" that single force-killed run is the final
    # one, reported as `stopped == "unhealthy"` with `liveness_kills == 1` and no
    # restarts. The scripted `pending` reply never exits on its own, so the
    # liveness timer is what ends the incarnation — exactly the wedged-but-alive
    # case health checks exist for.
    runner = ScriptedRunner()
    runner.fallback(Reply.pending())

    def unhealthy() -> bool:
        return False

    outcome = Supervisor(
        Command(NO_SUCH_PROGRAM),
        restart="never",
        health_check=unhealthy,
        health_check_interval=0.02,
        health_check_failures=1,
        runner=runner,
    ).run()
    assert outcome.stopped == "unhealthy"
    assert outcome.liveness_kills == 1
    assert outcome.restarts == 0
    # The final synthetic result is a non-success signal kill (we killed it).
    assert not outcome.final_result.is_success


def test_supervisor_health_check_unhealthy_via_arun() -> None:
    # The async supervision path surfaces a liveness kill identically to the sync
    # loop (same outcome, same counters).
    async def scenario() -> SupervisionOutcome:
        runner = ScriptedRunner()
        runner.fallback(Reply.pending())
        sup = Supervisor(
            Command(NO_SUCH_PROGRAM),
            restart="never",
            health_check=lambda: False,
            health_check_interval=0.02,
            health_check_failures=1,
            runner=runner,
        )
        return await sup.arun()

    outcome = asyncio.run(scenario())
    assert outcome.stopped == "unhealthy"
    assert outcome.liveness_kills == 1
    assert outcome.restarts == 0


def test_supervisor_health_check_counts_as_crash_under_a_restart_policy() -> None:
    # Under a restart-wanting policy a failed liveness check is treated exactly
    # like a crash: it flows through backoff/`max_restarts`, incrementing
    # `restarts`, and `liveness_kills` grows once per force-kill. Here three wedged
    # incarnations (initial + 2 restarts) exhaust `max_restarts=2`, so
    # `stopped == "restarts_exhausted"`, `restarts == 2`, `liveness_kills == 3`.
    runner = ScriptedRunner()
    runner.fallback(Reply.pending())

    outcome = Supervisor(
        Command(NO_SUCH_PROGRAM),
        restart="on_crash",
        max_restarts=2,
        backoff_initial=0.001,
        backoff_factor=1.0,
        jitter=False,
        health_check=lambda: False,
        health_check_interval=0.02,
        health_check_failures=1,
        runner=runner,
    ).run()
    assert outcome.stopped == "restarts_exhausted"
    assert outcome.restarts == 2
    assert outcome.liveness_kills == 3


def test_supervisor_health_check_requires_interval() -> None:
    # `health_check` and `health_check_interval` are a required pair (the crate
    # takes probe + cadence together): a probe without an interval is a misuse,
    # not a silent default.
    with pytest.raises(ValueError, match="health_check requires health_check_interval"):
        Supervisor(Command(PY, ["-c", "pass"]), health_check=lambda: True)


def test_supervisor_health_check_interval_requires_a_probe() -> None:
    # The reverse: an interval with no probe has nothing to schedule — reject it
    # rather than silently ignore it.
    with pytest.raises(
        ValueError, match="health_check_interval has no effect without health_check"
    ):
        Supervisor(Command(PY, ["-c", "pass"]), health_check_interval=0.02)


def test_supervisor_health_check_interval_must_be_positive() -> None:
    # `health_check_interval` goes through the shared positive-duration check.
    with pytest.raises(ValueError):
        Supervisor(
            Command(PY, ["-c", "pass"]), health_check=lambda: True, health_check_interval=0.0
        )


def test_supervisor_health_check_failures_without_a_probe_is_a_noop() -> None:
    # `health_check_failures` alone (no `health_check`) is an inert no-op — the
    # crate ignores the threshold without a probe — matching `storm_pause`'s own
    # companion-knob permissiveness. Construction succeeds and supervision runs.
    outcome = Supervisor(
        Command(PY, ["-c", "pass"]), restart="never", health_check_failures=3
    ).run()
    assert outcome.final_result.is_success
    assert outcome.liveness_kills == 0


def test_supervisor_health_check_raising_probe_propagates() -> None:
    # A probe that raises cannot answer "healthy": it is treated as unhealthy (so
    # the failure streak advances and the wedged run is force-killed) AND its error
    # is surfaced to the caller from run(), rather than swallowed into a spurious
    # liveness kill — mirroring stop_when/give_up_when's own contract. Under
    # restart="never" the single force-kill halts the loop and run() re-raises.
    runner = ScriptedRunner()
    runner.fallback(Reply.pending())

    def boom() -> bool:
        raise ValueError("probe exploded")

    with pytest.raises(ValueError, match="probe exploded"):
        Supervisor(
            Command(NO_SUCH_PROGRAM),
            restart="never",
            health_check=boom,
            health_check_interval=0.02,
            health_check_failures=1,
            runner=runner,
        ).run()


def test_supervisor_health_check_non_bool_probe_propagates() -> None:
    # A non-bool probe return is as undecidable as a raise: surface a TypeError
    # rather than coercing it to a health verdict.
    runner = ScriptedRunner()
    runner.fallback(Reply.pending())

    def probe() -> bool:
        return "healthy"  # type: ignore[return-value]

    with pytest.raises(TypeError):
        Supervisor(
            Command(NO_SUCH_PROGRAM),
            restart="never",
            health_check=probe,
            health_check_interval=0.02,
            health_check_failures=1,
            runner=runner,
        ).run()


# --- value semantics: __eq__/__hash__/pickle (T-041) -------------------------


def test_supervision_outcome_eq_and_hash_compare_by_value() -> None:
    a = Supervisor(Command(PY, ["-c", "pass"]), restart="never").run()
    b = Supervisor(Command(PY, ["-c", "pass"]), restart="never").run()
    assert a is not b
    assert a == b
    assert hash(a) == hash(b)


def test_supervision_outcome_repr_includes_liveness_kills() -> None:
    # The liveness-kill counter is part of the outcome's value identity, so it
    # appears in the repr alongside restarts/stopped/storm_pauses (0 without a
    # health check).
    outcome = Supervisor(Command(PY, ["-c", "pass"]), restart="never").run()
    assert outcome.liveness_kills == 0
    assert "liveness_kills=0" in repr(outcome)


def test_supervision_outcome_not_equal_when_a_field_differs() -> None:
    clean = Supervisor(Command(PY, ["-c", "pass"]), restart="never").run()
    crashed = Supervisor(Command(PY, ["-c", "import sys; sys.exit(1)"]), restart="never").run()
    assert clean != crashed
    assert clean != 5


def test_supervision_outcome_pickle_raises_type_error() -> None:
    # SupervisionOutcome is NOT picklable (T-079): its identity includes
    # `final_result` (a ProcessResult), which cannot be faithfully reconstructed
    # from a pickle — the crate's ProcessResult comparison also spans the hidden
    # timeout/success_codes that have no accessor to read back. Refuse loudly
    # rather than hand back a value that silently breaks the round-trip. To cross
    # a process boundary, read the fields you need or pickle
    # `final_result.outcome` (an Outcome, which round-trips exactly).
    outcome = Supervisor(Command(PY, ["-c", "pass"]), restart="never").run()
    with pytest.raises(TypeError, match="SupervisionOutcome cannot be pickled"):
        pickle.dumps(outcome)

    # The picklable escape hatch: the final run's Outcome summary round-trips.
    restored = pickle.loads(pickle.dumps(outcome.final_result.outcome))
    assert restored == outcome.final_result.outcome
    assert restored.exited_zero


# --- injected-runner when() predicate errors abort supervision (T-104) --------


def test_supervisor_when_raising_predicate_aborts_run() -> None:
    # Regression (T-104): a Supervisor driving an injected ScriptedRunner whose
    # when() predicate raises used to swallow the error into the unraisable hook,
    # read the predicate as "no match", and quietly return a fallback-driven
    # outcome. It must now abort supervision with that error, surfaced from run().
    # restart="never" keeps the loop to a single incarnation so the error surfaces
    # promptly (a bounded loop surfaces it once it halts).
    def boom(cmd: Command) -> bool:
        raise ValueError("supervisor predicate exploded")

    runner = ScriptedRunner()
    runner.when(boom, Reply.ok("matched"))
    runner.fallback(Reply.ok("fallback"))
    sup = Supervisor(Command(NO_SUCH_PROGRAM), restart="never", runner=runner)

    with pytest.raises(ValueError, match="supervisor predicate exploded"):
        sup.run()


def test_supervisor_awhen_raising_predicate_aborts_run() -> None:
    # The async supervision path (arun) propagates a raising when() predicate too
    # (T-104), with the same precedence as the sync run.
    def boom(cmd: Command) -> bool:
        raise ValueError("async supervisor predicate exploded")

    async def scenario() -> SupervisionOutcome:
        runner = ScriptedRunner()
        runner.when(boom, Reply.ok("matched"))
        runner.fallback(Reply.ok("fallback"))
        sup = Supervisor(Command(NO_SUCH_PROGRAM), restart="never", runner=runner)
        return await sup.arun()

    with pytest.raises(ValueError, match="async supervisor predicate exploded"):
        asyncio.run(scenario())


def test_supervisor_when_non_bool_predicate_aborts_run() -> None:
    # A non-bool return is as undecidable as a raise: surface a TypeError rather
    # than reading it as "no match" and looping/returning a fallback outcome.
    def predicate(cmd: Command) -> bool:
        return "yes"  # type: ignore[return-value]

    runner = ScriptedRunner()
    runner.when(predicate, Reply.ok("matched"))
    runner.fallback(Reply.ok("fallback"))
    sup = Supervisor(Command(NO_SUCH_PROGRAM), restart="never", runner=runner)

    with pytest.raises(TypeError):
        sup.run()
