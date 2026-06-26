//! The `Supervisor` (restart/backoff) and its `SupervisionOutcome`.

use std::time::Duration;

use processkit::JobRunner;
use processkit::ProcessResult as PkProcessResult;
use processkit::SupervisionOutcome;
use processkit::Supervisor as PkSupervisor;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::command::PyCommand;
use crate::convert::{parse_restart_policy, positive_duration, stop_reason_str};
use crate::errors::{map_err, ProcessError};
use crate::result::PyProcessResult;
use crate::runtime::block_on_interruptible;

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
    inner: Option<PkSupervisor<JobRunner>>,
}

impl PySupervisor {
    fn take_supervisor(&mut self) -> PyResult<PkSupervisor<JobRunner>> {
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
        Ok(Self {
            inner: Some(supervisor),
        })
    }

    /// Run supervision to completion (sync). Consumes the supervisor.
    fn run(&mut self, py: Python<'_>) -> PyResult<PySupervisionOutcome> {
        let supervisor = self.take_supervisor()?;
        let outcome = block_on_interruptible(py, supervisor.run())?.map_err(map_err)?;
        Ok(convert_supervision_outcome(&outcome))
    }

    /// Async counterpart of `run()`. Consumes the supervisor.
    fn arun<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let supervisor = self.take_supervisor()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match supervisor.run().await {
                Ok(outcome) => Ok(convert_supervision_outcome(&outcome)),
                Err(err) => Err(map_err(err)),
            }
        })
    }
}
