//! The `Supervisor` (restart/backoff) and its `SupervisionOutcome`.

use std::sync::Arc;
use std::time::Duration;

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
use crate::convert::{nonnegative_duration, positive_duration};
use crate::errors::ProcessError;
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

    /// Why supervision stopped: `"policy_satisfied"`, `"predicate"`, or
    /// `"restarts_exhausted"`.
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
        storm_pause=None,
        failure_threshold=None,
        failure_decay=None,
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
        storm_pause: Option<f64>,
        failure_threshold: Option<f64>,
        failure_decay: Option<f64>,
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
