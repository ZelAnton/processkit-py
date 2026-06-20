//! The captured-result value types: `ProcessResult`, `BytesResult`, `Outcome`,
//! `OutputEvent`, `Finished`, and `RunProfile`.

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

#[pymethods]
impl PyRunProfile {
    /// The exit code, or `None` for a timeout / signal-kill.
    #[getter]
    fn exit_code(&self) -> Option<i32> {
        self.inner.exit_code
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
    #[getter]
    fn avg_cpu(&self) -> Option<f64> {
        self.inner.avg_cpu()
    }

    fn __repr__(&self) -> String {
        format!(
            "RunProfile(exit_code={:?}, duration_seconds={:.3}, peak_memory_bytes={:?}, samples={})",
            self.inner.exit_code,
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

    /// stdout and stderr interleaved into one string (stdout first).
    fn combined(&self) -> String {
        self.inner.combined()
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

    #[getter]
    fn is_success(&self) -> bool {
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

    #[getter]
    fn is_success(&self) -> bool {
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
