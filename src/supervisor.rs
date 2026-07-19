//! The `Supervisor` (restart/backoff) and its `SupervisionOutcome`.

use std::hash::{Hash, Hasher};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;

use processkit::GiveUpAttempt;
use processkit::JobRunner;
use processkit::ProcessResult as PkProcessResult;
use processkit::ProcessRunner;
use processkit::RestartPolicy;
use processkit::StopReason;
use processkit::SupervisionOutcome;
use processkit::Supervisor as PkSupervisor;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;

use crate::command::PyCommand;
use crate::convert::{
    build_output_buffer_policy, nonnegative_duration, normalize_named_preset, positive_duration,
};
use crate::errors::{map_err, map_err_ref, ProcessError};
use crate::result::PyProcessResult;
use crate::runner::{extract_runner, new_when_sink, scope_when, take_when_error};
use crate::runtime::{block_on, drive_async_py, reject_reentrant_runtime, require_event_loop};

const DEFAULT_BACKOFF_INITIAL: Duration = Duration::from_millis(200);
const DEFAULT_BACKOFF_FACTOR: f64 = 2.0;

/// A one-shot sink for the error a control-predicate (`stop_when` /
/// `give_up_when`) raised — or the `TypeError` a non-`bool` return produced.
///
/// The crate's predicate closures are infallible (`-> bool`), so a raising
/// predicate cannot abort supervision by itself. Instead the wrapper stashes the
/// error here and returns "stop"/"give up" so the loop halts on that iteration;
/// `run()`/`arun()` then reads this slot and re-raises the stashed error to the
/// caller instead of handing back the (now meaningless) outcome or the mapped
/// crate error. A fresh slot is created per `Supervisor` and shared between its
/// two predicate closures — and a `Supervisor` runs exactly once (`run`/`arun`
/// consume it), so two supervisions never share a slot and their errors cannot
/// cross, even when run concurrently.
type ErrorSlot = Arc<Mutex<Option<PyErr>>>;

/// Stash the first control-predicate error of a supervision run. First-error
/// wins: the loop halts on the first raise, so at most one write happens, but
/// keeping the earliest is the defensive choice regardless.
fn record_slot_error(slot: &ErrorSlot, err: PyErr) {
    let mut guard = slot.lock().unwrap_or_else(PoisonError::into_inner);
    if guard.is_none() {
        *guard = Some(err);
    }
}

/// Take the stashed control-predicate error, if any, once the run has ended.
fn take_slot_error(slot: &ErrorSlot) -> Option<PyErr> {
    slot.lock().unwrap_or_else(PoisonError::into_inner).take()
}

/// Parse a restart policy name into a crate `RestartPolicy` — supervisor-only,
/// so it lives here rather than in the general `convert.rs` grab-bag. Named
/// presets are ASCII-case-insensitive so this fixed vocabulary follows the same
/// contract as every other named preset parser.
fn parse_restart_policy(name: &str) -> PyResult<RestartPolicy> {
    let key = normalize_named_preset(name);
    match key.as_str() {
        "always" => Ok(RestartPolicy::Always),
        "never" => Ok(RestartPolicy::Never),
        "on_crash" | "on-crash" | "oncrash" => Ok(RestartPolicy::OnCrash),
        _ => Err(PyValueError::new_err(format!(
            "unknown restart policy {name:?}; use one of: always, never, on_crash"
        ))),
    }
}

/// Render a `StopReason` as a stable lowercase string — supervisor-only, see
/// `parse_restart_policy` above.
fn stop_reason_str(reason: StopReason) -> &'static str {
    match reason {
        StopReason::PolicySatisfied => "policy_satisfied",
        StopReason::Predicate => "predicate",
        StopReason::RestartsExhausted => "restarts_exhausted",
        StopReason::GaveUp => "gave_up",
        _ => "unknown",
    }
}

/// Wrap a Python predicate `(ProcessResult) -> bool` as a `Supervisor.stop_when`
/// callback. The crate's predicate is infallible (`-> bool`), so a raising or
/// non-`bool` predicate cannot fail the loop directly. Instead the error is
/// **stashed in `slot`** and the wrapper returns `true` (stop) so the loop halts
/// on this iteration without launching another restart; `run()`/`arun()` then
/// re-raises the stashed error to the caller. This propagates a buggy predicate
/// to the code that owns the supervisor — a supervisor whose stop condition is
/// undecidable must not keep restarting on a guess — rather than swallowing it
/// into "do not stop" and looping invisibly to `max_restarts`.
fn make_stop_predicate(
    callback: Py<PyAny>,
    slot: ErrorSlot,
) -> impl Fn(&PkProcessResult<String>) -> bool + Send + Sync + 'static {
    move |result| {
        // `try_attach`, not `attach`: `stop_when` runs on a tokio supervision
        // worker not joined at `Py_Finalize` (the runtime is an immortal
        // singleton). A finalizing interpreter yields `None` -> "do not stop",
        // instead of the panic/crash a plain `attach` would cause at shutdown —
        // there is no live caller to re-raise to during finalization anyway. Same
        // finalization guard as `logging.rs`'s bridge.
        Python::try_attach(|py| {
            let py_result = match Py::new(
                py,
                PyProcessResult {
                    inner: result.clone(),
                },
            ) {
                Ok(py_result) => py_result,
                // Stash and stop: a bridge error (e.g. allocation failure building
                // the argument) is undecidable ground for continuing to restart.
                Err(err) => {
                    record_slot_error(&slot, err);
                    return true;
                }
            };
            match callback
                .call1(py, (py_result,))
                .and_then(|value| value.extract::<bool>(py))
            {
                Ok(stop) => stop,
                // A raise or a non-`bool` return: stash the error and stop so the
                // loop halts here; `run()`/`arun()` re-raises it to the caller.
                Err(err) => {
                    record_slot_error(&slot, err);
                    true
                }
            }
        })
        .unwrap_or(false)
    }
}

/// Wrap a Python classifier as a `Supervisor.give_up_when` callback — the
/// permanent-failure verdict that stops the supervisor giving up instead of
/// restarting a crash forever.
///
/// Form decision (task T-021, Stage 1): a **Python callable**, not a string
/// preset like `Command.retry`'s `retry_if`. The crate's `give_up_when` takes a
/// boxed closure (`Fn(&GiveUpAttempt<'_>) -> bool`) — structurally the
/// `stop_when` predicate (already a Python callable here via
/// `make_stop_predicate`), not the `restart`/`retry_if` enum-like presets. A
/// preset works for `retry_if` because it ranges over a tiny fixed vocabulary of
/// universal `Error` accessors (`is_transient`/`is_timeout`); a *useful*
/// `GiveUpAttempt` verdict is inherently per-run — the exit code of a crashed
/// run, the specific kind of a spawn error — with no small universal preset
/// vocabulary. And the required `stopped == "gave_up"` outcome arises *only* for
/// a `Crashed` verdict, whose "permanent" test is result-specific and so not a
/// fixed preset at all.
///
/// The callback receives ONE argument mirroring the `GiveUpAttempt` sum type,
/// dispatched with `isinstance` (idiomatic Python for a sum type), reusing types
/// already public — no new surface:
///   - `Crashed(&ProcessResult)` -> the `ProcessResult` (the same object
///     `stop_when` receives): classify a crash by its result, e.g.
///     `attempt.code == 13`;
///   - `Failed(&Error)` -> the mapped `ProcessError` subclass instance (built via
///     `map_err_ref`, **passed, not raised**): classify a launch that never
///     produced a result, e.g. `isinstance(attempt, ProcessNotFound)` for a
///     missing binary.
///
/// GIL safety: the classifier runs on the tokio runtime thread, so it acquires
/// the GIL via `Python::try_attach` before touching Python, exactly like
/// `make_stop_predicate`. `try_attach` (not `attach`) returns `None` once the
/// interpreter is finalizing — that worker thread is not joined at `Py_Finalize`
/// — and the classifier then reads as "not permanent" (keep restarting) without
/// touching Python, rather than panicking/crashing at shutdown. The crate's
/// classifier is infallible (`-> bool`), so a raising or non-`bool` callback
/// cannot fail the loop directly; instead the error is **stashed in `slot`** and
/// the wrapper returns `true` (give up) so the loop halts on this iteration, and
/// `run()`/`arun()` re-raises it to the caller — a buggy classifier is surfaced
/// to the owning code rather than swallowed into "keep restarting" and looping
/// invisibly. (For a `Failed`/spawn verdict, `true` makes the crate return the
/// spawn error, which the run's error slot then shadows with the classifier's
/// own error.)
fn make_give_up_classifier(
    callback: Py<PyAny>,
    slot: ErrorSlot,
) -> impl Fn(&GiveUpAttempt<'_>) -> bool + Send + Sync + 'static {
    move |attempt| {
        // `try_attach`, not `attach`: the classifier runs on a tokio supervision
        // worker not joined at `Py_Finalize` (the runtime is an immortal
        // singleton). A finalizing interpreter yields `None` -> "not permanent" /
        // keep restarting, instead of the panic/crash a plain `attach` would
        // cause at shutdown — there is no live caller to re-raise to during
        // finalization anyway. Same finalization guard as `logging.rs`.
        Python::try_attach(|py| {
            // Build the Python-facing view of this attempt (see the doc above).
            let arg: Py<PyAny> = match attempt {
                GiveUpAttempt::Crashed(result) => {
                    match Py::new(
                        py,
                        PyProcessResult {
                            inner: (*result).clone(),
                        },
                    ) {
                        Ok(result) => result.into_any(),
                        // Stash and give up: a bridge error is undecidable ground
                        // for continuing to restart.
                        Err(err) => {
                            record_slot_error(&slot, err);
                            return true;
                        }
                    }
                }
                // A launch that never produced a result: hand the callback the
                // same typed exception the crate error maps to (built, not
                // raised), so it can `isinstance`-classify the failure mode.
                GiveUpAttempt::Failed(error) => map_err_ref(error).into_value(py).into_any(),
                // `GiveUpAttempt` is `#[non_exhaustive]`: a future "never ran"
                // kind we don't yet understand -> not permanent (keep
                // restarting), the safe default rather than a guess.
                _ => return false,
            };
            match callback
                .call1(py, (arg,))
                .and_then(|value| value.extract::<bool>(py))
            {
                Ok(give_up) => give_up,
                // A raise or a non-`bool` return: stash the error and halt so the
                // loop stops here; `run()`/`arun()` re-raises it to the caller.
                Err(err) => {
                    record_slot_error(&slot, err);
                    true
                }
            }
        })
        .unwrap_or(false)
    }
}

fn convert_supervision_outcome(outcome: &SupervisionOutcome) -> PySupervisionOutcome {
    PySupervisionOutcome {
        final_result: outcome.final_result.clone(),
        restarts: outcome.restarts,
        stopped: stop_reason_str(outcome.stopped),
        storm_pauses: outcome.storm_pauses,
    }
}

/// The result of `Supervisor.run()`.
#[pyclass(name = "SupervisionOutcome", frozen, module = "processkit")]
pub(crate) struct PySupervisionOutcome {
    final_result: PkProcessResult<String>,
    restarts: u32,
    stopped: &'static str,
    storm_pauses: u32,
}

#[pymethods]
impl PySupervisionOutcome {
    /// The `ProcessResult` of the final run.
    #[getter]
    fn final_result(&self) -> PyProcessResult {
        PyProcessResult {
            inner: self.final_result.clone(),
        }
    }

    /// How many times the command was restarted.
    #[getter]
    fn restarts(&self) -> u32 {
        self.restarts
    }

    /// Why supervision stopped: `"policy_satisfied"`, `"predicate"`,
    /// `"restarts_exhausted"`, or `"gave_up"` (a `give_up_when` classifier
    /// recognized a crash as permanent).
    #[getter]
    fn stopped(&self) -> &'static str {
        self.stopped
    }

    /// How many restart-storm pauses occurred.
    #[getter]
    fn storm_pauses(&self) -> u32 {
        self.storm_pauses
    }

    fn __repr__(&self) -> String {
        format!(
            "SupervisionOutcome(restarts={}, stopped={:?}, storm_pauses={})",
            self.restarts, self.stopped, self.storm_pauses,
        )
    }

    /// Value equality over every field (`final_result` via the crate's own
    /// `ProcessResult` `PartialEq`, plus `restarts`/`stopped`/`storm_pauses`) —
    /// not `object`'s identity comparison.
    fn __eq__(&self, other: &Self) -> bool {
        self.final_result == other.final_result
            && self.restarts == other.restarts
            && self.stopped == other.stopped
            && self.storm_pauses == other.storm_pauses
    }

    /// Consistent with `__eq__`; see `ProcessResult.__hash__` for why
    /// `final_result`'s hash uses a subset of its compared fields.
    fn __hash__(&self) -> u64 {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        self.final_result.program().hash(&mut hasher);
        self.final_result.stdout().hash(&mut hasher);
        self.final_result.stderr().hash(&mut hasher);
        self.final_result.code().hash(&mut hasher);
        self.final_result.signal().hash(&mut hasher);
        self.final_result.timed_out().hash(&mut hasher);
        self.restarts.hash(&mut hasher);
        self.stopped.hash(&mut hasher);
        self.storm_pauses.hash(&mut hasher);
        hasher.finish()
    }

    /// **Not** picklable: a `SupervisionOutcome`'s identity includes its
    /// `final_result` (a `ProcessResult`), and that type cannot be faithfully
    /// reconstructed from a pickle — the crate's `ProcessResult` `PartialEq`
    /// compares a configured `timeout` and accepted `ok_codes` that `processkit`
    /// exposes no accessor to read, so a round trip would compare unequal for
    /// any supervised command that set `.timeout(...)`/`.success_codes(...)`
    /// (see `result::PyProcessResult::__reduce__` and the `result` module doc).
    /// Refuse loudly rather than hand back a value that silently breaks the
    /// pickle invariant; read the fields you need
    /// (`final_result.stdout`/`.code`, `restarts`, `stopped`, `storm_pauses`),
    /// or pickle `final_result.outcome` (an `Outcome`, which round-trips
    /// exactly), before crossing a process boundary.
    fn __reduce__(&self) -> PyResult<()> {
        Err(PyTypeError::new_err(
            "SupervisionOutcome cannot be pickled: its identity includes final_result, a \
             ProcessResult that processkit cannot faithfully reconstruct from a pickle (its \
             timeout/success_codes have no accessor to read back), so a round trip would compare \
             unequal for a supervised command that set .timeout(...) or .success_codes(...); read \
             the fields you need (final_result.stdout/.code, restarts, stopped, storm_pauses), or \
             pickle final_result.outcome (an Outcome, which round-trips exactly), instead",
        ))
    }
}

/// Keep a command alive: restart it per policy with backoff until a stop
/// condition is met. Configure with keyword arguments, then `run()` / `arun()`.
// `frozen` so `run()`/`arun()` take `&self`: they release the GIL for the entire
// supervision loop (`block_on`/the awaited future), so an exclusive `&mut self`
// PyO3 borrow held across that window made any concurrent `&self` call from
// another thread — a second `run()`, or a `run()` re-entered from a
// `stop_when`/`give_up_when` callback thread — race PyO3's per-object borrow flag
// and surface a raw `RuntimeError("Already borrowed")` instead of the typed
// "already been run" `ProcessError`. The interior `Mutex<Option<...>>` serializes
// that access instead (the same T-052 fix as `RunningProcess`/`ProcessGroup`);
// the guard is always released (via `take_supervisor` below) *before* any
// `block_on`/await, so a consumed supervisor reads back cleanly as `None` and the
// supervision wait is never held under the lock.
#[pyclass(name = "Supervisor", module = "processkit", frozen)]
pub(crate) struct PySupervisor {
    // `None` after `run()`/`arun()` has taken ownership of the supervisor.
    inner: Mutex<Option<PkSupervisor<Arc<dyn ProcessRunner + Send + Sync>>>>,
    /// Shared by this supervisor's `stop_when`/`give_up_when` wrappers: a control
    /// predicate that raised (or returned non-`bool`) stashes its error here, and
    /// `run()`/`arun()` re-raises it after the loop halts. Per-instance, so
    /// concurrent supervisions never cross errors (see [`ErrorSlot`]).
    error_slot: ErrorSlot,
}

impl PySupervisor {
    /// Take the supervisor out for a consuming `run()`/`arun()`, erroring if it
    /// was already run. Like `RunningProcess::take_running`, the lock is released
    /// before this returns, so the subsequent `block_on`/await never holds it
    /// across the (GIL-released) supervision wait.
    fn take_supervisor(&self) -> PyResult<PkSupervisor<Arc<dyn ProcessRunner + Send + Sync>>> {
        self.inner
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .take()
            .ok_or_else(|| ProcessError::new_err("this Supervisor has already been run"))
    }
}

#[pymethods]
impl PySupervisor {
    #[new]
    #[pyo3(signature = (
        command,
        *,
        restart=None,
        max_restarts=None,
        backoff_initial=None,
        backoff_factor=None,
        max_backoff=None,
        jitter=None,
        stop_when=None,
        give_up_when=None,
        storm_pause=None,
        failure_threshold=None,
        failure_decay=None,
        capture_max_bytes=None,
        capture_max_lines=None,
        capture_on_overflow=None,
        runner=None,
    ))]
    #[allow(clippy::too_many_arguments)] // a keyword-only builder constructor
    fn new(
        command: &PyCommand,
        restart: Option<&str>,
        max_restarts: Option<u32>,
        backoff_initial: Option<f64>,
        backoff_factor: Option<f64>,
        max_backoff: Option<f64>,
        jitter: Option<bool>,
        stop_when: Option<Py<PyAny>>,
        give_up_when: Option<Py<PyAny>>,
        storm_pause: Option<f64>,
        failure_threshold: Option<f64>,
        failure_decay: Option<f64>,
        capture_max_bytes: Option<usize>,
        capture_max_lines: Option<usize>,
        capture_on_overflow: Option<&str>,
        runner: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        // One error sink for this supervisor's control predicates, read back by
        // `run`/`arun` after the loop halts. Created even when no predicate is
        // set (harmless: it stays empty) to keep the field unconditional.
        let error_slot: ErrorSlot = Arc::new(Mutex::new(None));
        let mut supervisor = PkSupervisor::new(command.inner.clone());
        if let Some(policy) = restart {
            supervisor = supervisor.restart(parse_restart_policy(policy)?);
        }
        if let Some(n) = max_restarts {
            supervisor = supervisor.max_restarts(n);
        }
        // `backoff_initial` and `backoff_factor` are independent knobs: setting
        // EITHER applies a custom backoff curve, with the unspecified side falling
        // back to the crate default (0.2 s base, 2.0 factor) rather than being
        // silently dropped.
        if backoff_initial.is_some() || backoff_factor.is_some() {
            let initial = match backoff_initial {
                Some(seconds) => positive_duration(seconds, "backoff_initial")?,
                None => DEFAULT_BACKOFF_INITIAL,
            };
            let factor = backoff_factor.unwrap_or(DEFAULT_BACKOFF_FACTOR);
            if !factor.is_finite() || factor < 1.0 {
                return Err(PyValueError::new_err(
                    "backoff_factor must be a finite number >= 1.0",
                ));
            }
            supervisor = supervisor.backoff(initial, factor);
        }
        if let Some(seconds) = max_backoff {
            supervisor = supervisor.max_backoff(positive_duration(seconds, "max_backoff")?);
        }
        if let Some(enabled) = jitter {
            supervisor = supervisor.jitter(enabled);
        }
        if let Some(callback) = stop_when {
            supervisor = supervisor.stop_when(make_stop_predicate(callback, error_slot.clone()));
        }
        // Permanent-failure classifier (off unless set): consulted for a crash
        // the policy would otherwise restart, ahead of `max_restarts` and the
        // storm guard. A `Crashed` verdict stops with `stopped == "gave_up"`; a
        // `Failed` (spawn) verdict has no result to report and surfaces the
        // classified error directly from `run()`.
        if let Some(callback) = give_up_when {
            supervisor =
                supervisor.give_up_when(make_give_up_classifier(callback, error_slot.clone()));
        }
        // Failure-storm guard (off unless `storm_pause` is set): once the decaying
        // failure score crosses `failure_threshold`, the supervisor takes one
        // collective `storm_pause` instead of hammering restarts — and counts it in
        // `SupervisionOutcome.storm_pauses`.
        if let Some(seconds) = storm_pause {
            supervisor = supervisor.storm_pause(positive_duration(seconds, "storm_pause")?);
        }
        if let Some(threshold) = failure_threshold {
            if !threshold.is_finite() || threshold <= 0.0 {
                return Err(PyValueError::new_err(
                    "failure_threshold must be a finite, positive number",
                ));
            }
            supervisor = supervisor.failure_threshold(threshold);
        }
        if let Some(seconds) = failure_decay {
            // `nonnegative_duration`: a zero half-life is a valid config (keeps no
            // history — every failure scores exactly 1.0).
            supervisor = supervisor.failure_decay(nonnegative_duration(seconds, "failure_decay")?);
        }
        // Bound (or widen) the output captured from each incarnation — opt-in:
        // the crate's own default is already a sensible bounded tail (a
        // long-lived supervised process is often chatty), so this only applies
        // when the caller sets at least one of the cap sizes.
        //
        // processkit 2.1.0's `output_bytes` byte-cap behavior change does NOT
        // reach here (T-015): a `Supervisor` has no `output_bytes` verb — every
        // incarnation is captured line-based into a `ProcessResult<String>`
        // (`SupervisionOutcome.final_result`), never raw bytes. So
        // `capture_max_bytes`/`capture_max_lines` govern that line-captured
        // output only; there is no raw-stdout path for the new byte ceiling to
        // newly bound, and `final_result.truncated` keeps its existing meaning.
        if capture_max_bytes.is_some()
            || capture_max_lines.is_some()
            || capture_on_overflow.is_some()
        {
            let policy = build_output_buffer_policy(
                capture_max_bytes,
                capture_max_lines,
                capture_on_overflow.unwrap_or("drop_oldest"),
                "capture",
            )?;
            supervisor = supervisor.capture(policy);
        }
        // `Supervisor::new` only exists for `Supervisor<JobRunner>`; every builder
        // call above is generic over `R` and works unchanged on that concrete
        // type. `with_runner` is the one type-changing step, applied last so it
        // always lands on this binding's field type
        // (`Supervisor<Arc<dyn ProcessRunner + Send + Sync>>`) — the real
        // `JobRunner` by default, or whatever `extract_runner` resolves an
        // injected `runner=` to.
        let runner: Arc<dyn ProcessRunner + Send + Sync> = match runner {
            Some(obj) => extract_runner(obj)?,
            None => Arc::new(JobRunner::new()),
        };
        let supervisor = supervisor.with_runner(runner);
        Ok(Self {
            inner: Mutex::new(Some(supervisor)),
            error_slot,
        })
    }

    /// Run supervision to completion (sync). Consumes the supervisor.
    fn run(&self, py: Python<'_>) -> PyResult<PySupervisionOutcome> {
        // Checked before taking: see the comment on `require_event_loop` in
        // running.rs for why the order matters (consume-then-fail).
        reject_reentrant_runtime()?;
        let supervisor = self.take_supervisor()?;
        // Scope the whole supervision loop under a fresh `when`-predicate error
        // sink (see `runner.rs`): an injected `ScriptedRunner` whose `when`
        // predicate raises then aborts supervision with that error instead of
        // silently masking it behind a fallback reply and (possibly) looping on.
        // The loop drives the runner inline on THIS task (`supervisor.run()`'s
        // `self.runner.output_string(...).await`, no `tokio::spawn`), so a single
        // scope reaches every incarnation's predicate.
        let when_sink = new_when_sink();
        let result = block_on(py, scope_when(when_sink.clone(), supervisor.run()));
        // Precedence: the runner's `when`-predicate error is the earliest, most
        // fundamental defect — it undermines the very reply a control predicate
        // then examined — so it wins over a `stop_when`/`give_up_when` error,
        // which in turn beats the (now meaningless) outcome or mapped crate error.
        if let Some(err) = take_when_error(&when_sink) {
            return Err(err);
        }
        // A control predicate (`stop_when`/`give_up_when`) that raised or returned
        // a non-`bool` halted the loop and stashed its error — re-raise that to the
        // caller in preference to the (now meaningless) outcome or the mapped crate
        // error the wrapper's "stop"/"give up" verdict produced.
        if let Some(err) = take_slot_error(&self.error_slot) {
            return Err(err);
        }
        result.map(|outcome| convert_supervision_outcome(&outcome))
    }

    /// Async counterpart of `run()`. Consumes the supervisor.
    ///
    /// Like every `a`-prefixed verb, this returns a lazy awaitable: supervision
    /// does not start until the awaitable is first `await`ed (see the bridge's
    /// lifecycle contract in `runtime.rs`). So an `arun()` that is never awaited
    /// — even an unbounded `restart="always"` one — starts nothing and, when
    /// dropped, releases the supervisor and every `Py<PyAny>` callback it
    /// captured (`stop_when`/`give_up_when`, and anything they close over)
    /// instead of pinning them for the life of the interpreter. Still give an
    /// awaited `restart="always"` a `max_restarts=` or `stop_when=` so
    /// supervision has a defined end rather than restarting forever.
    fn arun<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        // Cloned before the supervisor is taken, so the awaited future can read the
        // control-predicate error slot back after the loop halts (see `run`).
        let error_slot = self.error_slot.clone();
        // Fresh `when`-predicate error sink scoped around the awaited supervision
        // loop, mirroring the sync `run` (same precedence: runner `when` error, then
        // control-predicate error, then the outcome/mapped crate error).
        let when_sink = new_when_sink();
        let supervisor = self.take_supervisor()?;
        drive_async_py(py, async move {
            let result = scope_when(when_sink.clone(), supervisor.run()).await;
            if let Some(err) = take_when_error(&when_sink) {
                return Err(err);
            }
            if let Some(err) = take_slot_error(&error_slot) {
                return Err(err);
            }
            result
                .map(|outcome| convert_supervision_outcome(&outcome))
                .map_err(map_err)
        })
    }
}

/// Register this module's pyclasses (`Supervisor`, `SupervisionOutcome`) on
/// `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySupervisor>()?;
    m.add_class::<PySupervisionOutcome>()?;
    Ok(())
}

// Rust-level unit tests for the pure helpers above. See `docs/internals.md`'s
// testing section for the intended split between this module and `tests/`.
#[cfg(test)]
mod tests {
    use super::*;

    // --- parse_restart_policy ------------------------------------------------

    #[test]
    fn parse_restart_policy_accepts_every_supported_name() {
        let cases = [
            ("always", RestartPolicy::Always),
            ("never", RestartPolicy::Never),
            ("on_crash", RestartPolicy::OnCrash),
            ("on-crash", RestartPolicy::OnCrash),
            ("oncrash", RestartPolicy::OnCrash),
        ];
        for (name, expected) in cases {
            assert_eq!(parse_restart_policy(name).unwrap(), expected, "{name}");
        }
    }

    #[test]
    fn parse_restart_policy_remains_case_insensitive() {
        assert_eq!(
            parse_restart_policy("ALWAYS").unwrap(),
            RestartPolicy::Always
        );
        assert_eq!(
            parse_restart_policy("On_Crash").unwrap(),
            RestartPolicy::OnCrash
        );
        assert_eq!(
            parse_restart_policy("ON-CRASH").unwrap(),
            RestartPolicy::OnCrash
        );
    }

    #[test]
    fn parse_restart_policy_rejects_unknown_name() {
        assert!(parse_restart_policy("sometimes").is_err());
    }

    // `PySupervisor::new` uses these constants when one backoff option is omitted.
    // Keep them aligned with the crate defaults so a processkit upgrade cannot silently
    // desynchronize the binding's partial-backoff behavior.
    #[test]
    fn binding_partial_backoff_defaults_match_processkit_defaults() {
        let debug = format!(
            "{:?}",
            PkSupervisor::new(processkit::Command::new("ignored"))
        );

        assert!(
            debug.contains(&format!("backoff_base: {:?}", DEFAULT_BACKOFF_INITIAL)),
            "processkit Supervisor default backoff_base must match binding default {DEFAULT_BACKOFF_INITIAL:?}; Debug output was: {debug}"
        );
        assert!(
            debug.contains(&format!("backoff_factor: {DEFAULT_BACKOFF_FACTOR:?}")),
            "processkit Supervisor default backoff_factor must match binding default {DEFAULT_BACKOFF_FACTOR:?}; Debug output was: {debug}"
        );
    }

    // --- stop_reason_str -------------------------------------------------

    #[test]
    fn stop_reason_str_covers_every_variant() {
        let cases = [
            (StopReason::PolicySatisfied, "policy_satisfied"),
            (StopReason::Predicate, "predicate"),
            (StopReason::RestartsExhausted, "restarts_exhausted"),
            (StopReason::GaveUp, "gave_up"),
        ];
        for (reason, expected) in cases {
            assert_eq!(stop_reason_str(reason), expected, "{reason:?}");
        }
    }
}
