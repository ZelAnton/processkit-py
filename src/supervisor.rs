//! The `Supervisor` (restart/backoff) and its `SupervisionOutcome`.

use std::hash::{Hash, Hasher};
use std::sync::Arc;
use std::time::Duration;

use processkit::GiveUpAttempt;
use processkit::JobRunner;
use processkit::ProcessResult as PkProcessResult;
use processkit::ProcessRunner;
use processkit::RestartPolicy;
use processkit::StopReason;
use processkit::SupervisionOutcome;
use processkit::Supervisor as PkSupervisor;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::command::PyCommand;
use crate::convert::{build_output_buffer_policy, nonnegative_duration, positive_duration};
use crate::errors::{map_err_ref, ProcessError};
use crate::result::PyProcessResult;
use crate::runner::extract_runner;
use crate::runtime::{block_on, drive_async, reject_reentrant_runtime, require_event_loop};

/// Parse a restart policy name into a crate `RestartPolicy` — supervisor-only,
/// so it lives here rather than in the general `convert.rs` grab-bag.
fn parse_restart_policy(name: &str) -> PyResult<RestartPolicy> {
    match name.to_ascii_lowercase().as_str() {
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
/// non-bool predicate is treated as "do not stop" — but the error is surfaced
/// via the unraisable hook (stderr) rather than silently swallowed, so a buggy
/// predicate is visible instead of looping invisibly to `max_restarts`.
fn make_stop_predicate(
    callback: Py<PyAny>,
) -> impl Fn(&PkProcessResult<String>) -> bool + Send + Sync + 'static {
    move |result| {
        Python::attach(|py| {
            let py_result = match Py::new(
                py,
                PyProcessResult {
                    inner: result.clone(),
                },
            ) {
                Ok(py_result) => py_result,
                Err(err) => {
                    err.write_unraisable(py, None);
                    return false;
                }
            };
            match callback
                .call1(py, (py_result,))
                .and_then(|value| value.extract::<bool>(py))
            {
                Ok(stop) => stop,
                Err(err) => {
                    err.write_unraisable(py, Some(callback.bind(py)));
                    false
                }
            }
        })
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
/// the GIL via `Python::attach` before touching Python, exactly like
/// `make_stop_predicate`. The crate's classifier is infallible (`-> bool`), so a
/// raising or non-bool callback reads as "not permanent" — keep restarting, the
/// safe default that matches an unset classifier — but the error is surfaced via
/// the unraisable hook (stderr) rather than silently swallowed, so a buggy
/// classifier is visible instead of looping invisibly.
fn make_give_up_classifier(
    callback: Py<PyAny>,
) -> impl Fn(&GiveUpAttempt<'_>) -> bool + Send + Sync + 'static {
    move |attempt| {
        Python::attach(|py| {
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
                        Err(err) => {
                            err.write_unraisable(py, None);
                            return false;
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
                Err(err) => {
                    err.write_unraisable(py, Some(callback.bind(py)));
                    false
                }
            }
        })
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

    /// Pickle support: `final_result` is reconstructed via
    /// `result::scripted_process_result` (see that module's doc); `restarts`/
    /// `stopped`/`storm_pauses` are plain carried-through values.
    #[allow(clippy::type_complexity)]
    fn __reduce__<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<(
        Py<PyAny>,
        (
            String,
            String,
            String,
            Option<i32>,
            Option<i32>,
            bool,
            bool,
            u32,
            String,
            u32,
        ),
    )> {
        let factory = py.get_type::<Self>().getattr("_unpickle")?.unbind();
        Ok((
            factory,
            (
                self.final_result.program().to_string(),
                self.final_result.stdout().to_string(),
                self.final_result.stderr().to_string(),
                self.final_result.code(),
                self.final_result.signal(),
                self.final_result.timed_out(),
                self.final_result.is_success(),
                self.restarts,
                self.stopped.to_string(),
                self.storm_pauses,
            ),
        ))
    }

    /// `__reduce__`'s factory: a private (leading-underscore) staticmethod
    /// rather than a module-level function, so it rides along with the class
    /// in the stub/API-surface checks — see `result::PyProcessResult::_unpickle`.
    /// `final_result` is reconstructed via `result::scripted_process_result`
    /// (see that module's doc); `restarts`/`stopped`/`storm_pauses` are plain
    /// carried-through values.
    #[staticmethod]
    #[allow(clippy::too_many_arguments)]
    fn _unpickle(
        py: Python<'_>,
        program: String,
        stdout: String,
        stderr: String,
        code: Option<i32>,
        signal: Option<i32>,
        timed_out: bool,
        is_success: bool,
        restarts: u32,
        stopped: String,
        storm_pauses: u32,
    ) -> PyResult<Self> {
        let final_result = crate::result::scripted_process_result(
            py, program, stdout, stderr, code, signal, timed_out, is_success,
        )?;
        Ok(Self {
            final_result,
            restarts,
            stopped: static_stopped(&stopped),
            storm_pauses,
        })
    }
}

/// Map a `SupervisionOutcome.stopped` string back to the module's `&'static
/// str` vocabulary — the unpickling counterpart of `stop_reason_str`. An
/// unrecognized value (should not happen for a value pickled by this same
/// binding version) degrades to `"unknown"`, the same forward-compat fallback
/// `stop_reason_str` itself uses for a future crate `StopReason` variant.
fn static_stopped(value: &str) -> &'static str {
    match value {
        "policy_satisfied" => "policy_satisfied",
        "predicate" => "predicate",
        "restarts_exhausted" => "restarts_exhausted",
        "gave_up" => "gave_up",
        _ => "unknown",
    }
}

/// Keep a command alive: restart it per policy with backoff until a stop
/// condition is met. Configure with keyword arguments, then `run()` / `arun()`.
#[pyclass(name = "Supervisor", module = "processkit")]
pub(crate) struct PySupervisor {
    inner: Option<PkSupervisor<Arc<dyn ProcessRunner + Send + Sync>>>,
}

impl PySupervisor {
    fn take_supervisor(&mut self) -> PyResult<PkSupervisor<Arc<dyn ProcessRunner + Send + Sync>>> {
        self.inner
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
                None => Duration::from_millis(200),
            };
            let factor = backoff_factor.unwrap_or(2.0);
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
            supervisor = supervisor.stop_when(make_stop_predicate(callback));
        }
        // Permanent-failure classifier (off unless set): consulted for a crash
        // the policy would otherwise restart, ahead of `max_restarts` and the
        // storm guard. A `Crashed` verdict stops with `stopped == "gave_up"`; a
        // `Failed` (spawn) verdict has no result to report and surfaces the
        // classified error directly from `run()`.
        if let Some(callback) = give_up_when {
            supervisor = supervisor.give_up_when(make_give_up_classifier(callback));
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
            inner: Some(supervisor),
        })
    }

    /// Run supervision to completion (sync). Consumes the supervisor.
    fn run(&mut self, py: Python<'_>) -> PyResult<PySupervisionOutcome> {
        // Checked before taking: see the comment on `require_event_loop` in
        // running.rs for why the order matters (consume-then-fail).
        reject_reentrant_runtime()?;
        let supervisor = self.take_supervisor()?;
        block_on(py, supervisor.run()).map(|outcome| convert_supervision_outcome(&outcome))
    }

    /// Async counterpart of `run()`. Consumes the supervisor.
    fn arun<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        let supervisor = self.take_supervisor()?;
        drive_async(py, async move {
            supervisor
                .run()
                .await
                .map(|outcome| convert_supervision_outcome(&outcome))
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
