//! The captured-result value types: `ProcessResult`, `BytesResult`, `Outcome`,
//! `OutputEvent`, `Finished`, and `RunProfile`.

use processkit::Finished as PkFinished;
use processkit::Outcome as PkOutcome;
use processkit::OutputEvent as PkOutputEvent;
use processkit::ProcessResult as PkProcessResult;
use processkit::RunProfile as PkRunProfile;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// A resource-usage profile sampled across a run (from `RunningProcess.profile`).
#[pyclass(name = "RunProfile", frozen, module = "processkit")]
pub(crate) struct PyRunProfile {
    pub(crate) inner: PkRunProfile,
}

impl From<PkRunProfile> for PyRunProfile {
    fn from(inner: PkRunProfile) -> Self {
        Self { inner }
    }
}

#[pymethods]
impl PyRunProfile {
    /// The exit code, or `None` for a timeout / signal-kill. (Named `code` to
    /// match every other result type — `ProcessResult`, `Outcome`, ….)
    #[getter]
    fn code(&self) -> Option<i32> {
        self.inner.code()
    }

    /// Wall-clock time from start until the run finished, in seconds.
    #[getter]
    fn duration_seconds(&self) -> f64 {
        self.inner.duration.as_secs_f64()
    }

    /// Cumulative CPU time at the last sample, in seconds, if measurable.
    #[getter]
    fn cpu_time_seconds(&self) -> Option<f64> {
        self.inner.cpu_time.map(|d| d.as_secs_f64())
    }

    /// Peak resident memory observed across samples, in bytes, if measurable.
    #[getter]
    fn peak_memory_bytes(&self) -> Option<u64> {
        self.inner.peak_memory_bytes
    }

    /// How many sampling ticks ran.
    #[getter]
    fn samples(&self) -> usize {
        self.inner.samples
    }

    /// Average CPU cores used over the run (cpu_time / duration), if measurable.
    /// A value of `1.0` means one core fully saturated; `2.0`, two cores.
    #[getter]
    fn avg_cpu_cores(&self) -> Option<f64> {
        self.inner.avg_cpu_cores()
    }

    /// The signal that killed the run, if it was signal-killed; `None` otherwise.
    #[getter]
    fn signal(&self) -> Option<i32> {
        self.inner.signal()
    }

    /// Whether the run hit its timeout.
    #[getter]
    fn timed_out(&self) -> bool {
        self.inner.timed_out()
    }

    /// The full run outcome (`code` / `signal` / `timed_out`) — the same value a
    /// `wait()` would return. `profile()` computes it anyway, so it is a superset
    /// of `wait()`: telemetry **and** how the run actually ended.
    #[getter]
    fn outcome(&self) -> PyOutcome {
        PyOutcome::from(self.inner.outcome)
    }

    fn __repr__(&self) -> String {
        format!(
            "RunProfile(code={:?}, timed_out={}, duration_seconds={:.3}, peak_memory_bytes={:?}, samples={})",
            self.inner.code(),
            self.inner.timed_out(),
            self.inner.duration.as_secs_f64(),
            self.inner.peak_memory_bytes,
            self.inner.samples,
        )
    }
}

/// The captured result of a finished run. A non-zero exit, a timeout, and a
/// signal-kill are all *data* here — `output()` never raises on them.
#[pyclass(name = "ProcessResult", frozen, module = "processkit")]
pub(crate) struct PyProcessResult {
    pub(crate) inner: PkProcessResult<String>,
}

impl From<PkProcessResult<String>> for PyProcessResult {
    fn from(inner: PkProcessResult<String>) -> Self {
        Self { inner }
    }
}

#[pymethods]
impl PyProcessResult {
    #[getter]
    fn stdout(&self) -> &str {
        self.inner.stdout().as_str()
    }

    #[getter]
    fn stderr(&self) -> &str {
        self.inner.stderr()
    }

    /// The exit code, or `None` for a timeout / signal-kill (never a sentinel).
    #[getter]
    fn code(&self) -> Option<i32> {
        self.inner.code()
    }

    #[getter]
    fn is_success(&self) -> bool {
        self.inner.is_success()
    }

    #[getter]
    fn timed_out(&self) -> bool {
        self.inner.timed_out()
    }

    #[getter]
    fn signal(&self) -> Option<i32> {
        self.inner.signal()
    }

    #[getter]
    fn program(&self) -> &str {
        self.inner.program()
    }

    #[getter]
    fn duration_seconds(&self) -> f64 {
        self.inner.duration().as_secs_f64()
    }

    /// Whether captured output was truncated by an `output_limit(...)` cap.
    #[getter]
    fn truncated(&self) -> bool {
        self.inner.truncated()
    }

    /// stdout and stderr concatenated into one string (stdout first, then stderr).
    #[getter]
    fn combined(&self) -> String {
        self.inner.combined()
    }

    /// Raise the same exception a checking verb (`run`/`exit_code`/`probe`)
    /// would if this result's exit isn't in `success_codes` — for turning an
    /// already-captured `output()`/`output_bytes()` result into an error after
    /// the fact (some code paths need the data either way, others should fail
    /// loud only sometimes). Returns `self` unchanged on success, so it
    /// composes into a call chain: `cmd.output().ensure_success().stdout`.
    fn ensure_success(&self, py: Python<'_>) -> PyResult<Py<Self>> {
        let _ = self
            .inner
            .clone()
            .ensure_success()
            .map_err(crate::errors::map_err)?;
        Py::new(
            py,
            Self {
                inner: self.inner.clone(),
            },
        )
    }

    fn __repr__(&self) -> String {
        format!(
            "ProcessResult(program={:?}, code={:?}, success={})",
            self.inner.program(),
            self.inner.code(),
            self.inner.is_success(),
        )
    }
}

/// The captured result of a finished run with **raw bytes** stdout (produced by
/// `Command.output_bytes()`); stderr stays decoded text. As with `ProcessResult`,
/// a non-zero exit, a timeout, and a signal-kill are all *data* here.
#[pyclass(name = "BytesResult", frozen, module = "processkit")]
pub(crate) struct PyBytesResult {
    pub(crate) inner: PkProcessResult<Vec<u8>>,
}

impl From<PkProcessResult<Vec<u8>>> for PyBytesResult {
    fn from(inner: PkProcessResult<Vec<u8>>) -> Self {
        Self { inner }
    }
}

#[pymethods]
impl PyBytesResult {
    #[getter]
    fn stdout<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.inner.stdout().as_slice())
    }

    #[getter]
    fn stderr(&self) -> &str {
        self.inner.stderr()
    }

    /// The exit code, or `None` for a timeout / signal-kill.
    #[getter]
    fn code(&self) -> Option<i32> {
        self.inner.code()
    }

    #[getter]
    fn is_success(&self) -> bool {
        self.inner.is_success()
    }

    #[getter]
    fn timed_out(&self) -> bool {
        self.inner.timed_out()
    }

    #[getter]
    fn signal(&self) -> Option<i32> {
        self.inner.signal()
    }

    #[getter]
    fn program(&self) -> &str {
        self.inner.program()
    }

    #[getter]
    fn duration_seconds(&self) -> f64 {
        self.inner.duration().as_secs_f64()
    }

    /// Whether captured stderr was truncated by an `output_limit(...)` cap.
    /// (Raw stdout from `output_bytes()` is never line-capped — bound a flooding
    /// child with a `timeout` instead.)
    #[getter]
    fn truncated(&self) -> bool {
        self.inner.truncated()
    }

    /// Raise the same exception a checking verb would if this result's exit
    /// isn't in `success_codes` — see `ProcessResult.ensure_success()`. Returns
    /// `self` unchanged on success.
    fn ensure_success(&self, py: Python<'_>) -> PyResult<Py<Self>> {
        let _ = self
            .inner
            .clone()
            .ensure_success()
            .map_err(crate::errors::map_err)?;
        Py::new(
            py,
            Self {
                inner: self.inner.clone(),
            },
        )
    }

    fn __repr__(&self) -> String {
        format!(
            "BytesResult(program={:?}, code={:?}, success={}, stdout_len={})",
            self.inner.program(),
            self.inner.code(),
            self.inner.is_success(),
            self.inner.stdout().len(),
        )
    }
}

/// How a process ended: a clean exit code, a signal-kill, or a timeout.
#[pyclass(name = "Outcome", frozen, module = "processkit")]
pub(crate) struct PyOutcome {
    pub(crate) inner: PkOutcome,
}

impl From<PkOutcome> for PyOutcome {
    fn from(inner: PkOutcome) -> Self {
        Self { inner }
    }
}

#[pymethods]
impl PyOutcome {
    /// The exit code, or `None` for a signal-kill / timeout.
    #[getter]
    fn code(&self) -> Option<i32> {
        self.inner.code()
    }

    /// The terminating signal number (Unix), or `None`.
    #[getter]
    fn signal(&self) -> Option<i32> {
        self.inner.signal()
    }

    #[getter]
    fn timed_out(&self) -> bool {
        self.inner.timed_out()
    }

    /// Whether the process exited with code `0`. Named `exited_zero` (not
    /// `is_success`) because an `Outcome` carries no `success_codes` context — for
    /// the command's own success verdict use `ProcessResult.is_success`, or test
    /// `code` against your accepted set.
    #[getter]
    fn exited_zero(&self) -> bool {
        self.inner.code() == Some(0)
    }

    fn __repr__(&self) -> String {
        format!(
            "Outcome(code={:?}, signal={:?}, timed_out={})",
            self.inner.code(),
            self.inner.signal(),
            self.inner.timed_out(),
        )
    }
}

/// One captured line and the stream it came from (`stdout` or `stderr`).
#[pyclass(name = "OutputEvent", frozen, module = "processkit")]
pub(crate) struct PyOutputEvent {
    is_stderr: bool,
    text: String,
}

impl PyOutputEvent {
    pub(crate) fn from_event(event: PkOutputEvent) -> Self {
        match event {
            PkOutputEvent::Stdout(line) => Self {
                is_stderr: false,
                text: line.into_text(),
            },
            PkOutputEvent::Stderr(line) => Self {
                is_stderr: true,
                text: line.into_text(),
            },
            // `OutputEvent` is `#[non_exhaustive]`; degrade gracefully.
            other => Self {
                is_stderr: false,
                text: other.text().unwrap_or_default().to_string(),
            },
        }
    }
}

#[pymethods]
impl PyOutputEvent {
    /// `"stdout"` or `"stderr"`.
    #[getter]
    fn stream(&self) -> &'static str {
        if self.is_stderr {
            "stderr"
        } else {
            "stdout"
        }
    }

    #[getter]
    fn is_stderr(&self) -> bool {
        self.is_stderr
    }

    #[getter]
    fn text(&self) -> &str {
        &self.text
    }

    fn __repr__(&self) -> String {
        format!(
            "OutputEvent(stream={:?}, text={:?})",
            self.stream(),
            self.text
        )
    }
}

/// The result of `RunningProcess.finish()`: the outcome plus captured stderr,
/// without buffering stdout (which you consumed by streaming).
#[pyclass(name = "Finished", frozen, module = "processkit")]
pub(crate) struct PyFinished {
    pub(crate) outcome: PkOutcome,
    pub(crate) stderr: String,
}

impl From<PkFinished> for PyFinished {
    fn from(finished: PkFinished) -> Self {
        Self {
            outcome: finished.outcome,
            stderr: finished.stderr,
        }
    }
}

#[pymethods]
impl PyFinished {
    #[getter]
    fn outcome(&self) -> PyOutcome {
        PyOutcome {
            inner: self.outcome,
        }
    }

    #[getter]
    fn stderr(&self) -> &str {
        &self.stderr
    }

    #[getter]
    fn code(&self) -> Option<i32> {
        self.outcome.code()
    }

    /// Whether the process exited with code `0` (see `Outcome.exited_zero`).
    #[getter]
    fn exited_zero(&self) -> bool {
        self.outcome.code() == Some(0)
    }

    fn __repr__(&self) -> String {
        format!(
            "Finished(code={:?}, timed_out={})",
            self.outcome.code(),
            self.outcome.timed_out(),
        )
    }
}

/// Register this module's pyclasses (`ProcessResult`, `BytesResult`,
/// `RunProfile`, `Outcome`, `OutputEvent`, `Finished`) on `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyProcessResult>()?;
    m.add_class::<PyBytesResult>()?;
    m.add_class::<PyRunProfile>()?;
    m.add_class::<PyOutcome>()?;
    m.add_class::<PyOutputEvent>()?;
    m.add_class::<PyFinished>()?;
    Ok(())
}
