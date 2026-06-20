//! The async streaming/interactive handles: `RunningProcess` plus its
//! `ProcessStdin`, `StdoutLines`, and `OutputEvents`.

use std::sync::Arc;

use processkit::OutputEvents as PkOutputEvents;
use processkit::ProcessStdin as PkProcessStdin;
use processkit::RunningProcess as PkRunningProcess;
use processkit::StdoutLines as PkStdoutLines;
use processkit::StreamExt;
use pyo3::exceptions::{PyOSError, PyStopAsyncIteration};
use pyo3::prelude::*;
use tokio::sync::Mutex;

use crate::convert::{nonnegative_duration, positive_duration};
use crate::errors::{map_err, ProcessError};
use crate::result::{
    PyBytesResult, PyFinished, PyOutcome, PyOutputEvent, PyProcessResult, PyRunProfile,
};
use crate::runtime::{block_on_interruptible, rt};

/// Map a stdin I/O failure (a broken pipe, a closed child) onto `OSError`.
fn map_io_err(error: std::io::Error) -> PyErr {
    PyOSError::new_err(error.to_string())
}

/// A writable handle to a running process's stdin. Obtain it once via
/// `RunningProcess.take_stdin()`; all methods are awaitable.
#[pyclass(name = "ProcessStdin", module = "processkit")]
pub(crate) struct PyProcessStdin {
    // `None` after `close()` — writing then raises a clear error.
    inner: Arc<Mutex<Option<PkProcessStdin>>>,
}

#[pymethods]
impl PyProcessStdin {
    /// Write raw bytes to the child's stdin.
    fn write<'py>(&self, py: Python<'py>, data: Vec<u8>) -> PyResult<Bound<'py, PyAny>> {
        let stdin = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = stdin.lock().await;
            let writer = guard
                .as_mut()
                .ok_or_else(|| PyOSError::new_err("stdin is closed"))?;
            writer.write(&data).await.map_err(map_io_err)
        })
    }

    /// Write a line of text, appending a newline.
    fn write_line<'py>(&self, py: Python<'py>, line: String) -> PyResult<Bound<'py, PyAny>> {
        let stdin = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = stdin.lock().await;
            let writer = guard
                .as_mut()
                .ok_or_else(|| PyOSError::new_err("stdin is closed"))?;
            writer.write_line(&line).await.map_err(map_io_err)
        })
    }

    /// Flush buffered writes to the child.
    fn flush<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stdin = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = stdin.lock().await;
            let writer = guard
                .as_mut()
                .ok_or_else(|| PyOSError::new_err("stdin is closed"))?;
            writer.flush().await.map_err(map_io_err)
        })
    }

    /// Close stdin (sending EOF to the child). Idempotent.
    fn close<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stdin = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let writer = { stdin.lock().await.take() };
            match writer {
                Some(writer) => writer.finish().await.map_err(map_io_err),
                None => Ok(()),
            }
        })
    }
}

/// An async iterator over a process's stdout, line by line:
/// `async for line in proc.stdout_lines(): ...`.
#[pyclass(name = "StdoutLines", module = "processkit")]
pub(crate) struct PyStdoutLines {
    inner: Arc<Mutex<PkStdoutLines>>,
}

#[pymethods]
impl PyStdoutLines {
    fn __aiter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __anext__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stream = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match stream.lock().await.next().await {
                Some(line) => Ok(line),
                None => Err(PyStopAsyncIteration::new_err(())),
            }
        })
    }
}

/// An async iterator over stdout *and* stderr as interleaved `OutputEvent`s.
#[pyclass(name = "OutputEvents", module = "processkit")]
pub(crate) struct PyOutputEvents {
    inner: Arc<Mutex<PkOutputEvents>>,
}

#[pymethods]
impl PyOutputEvents {
    fn __aiter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __anext__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stream = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match stream.lock().await.next().await {
                Some(event) => Ok(PyOutputEvent::from_event(event)),
                None => Err(PyStopAsyncIteration::new_err(())),
            }
        })
    }
}

/// A handle to a started process: stream its output, write to its stdin, and
/// await its completion. The consuming methods (`wait`, `finish`, `output`,
/// `shutdown`) leave the handle spent; using it afterwards raises. Usable as a
/// context manager (`with` / `async with`): exiting the block tears the process
/// down — a hard kill of the whole private tree for a standalone handle.
#[pyclass(name = "RunningProcess", module = "processkit")]
pub(crate) struct PyRunningProcess {
    // `None` after a consuming method has taken ownership of the process.
    pub(crate) inner: Option<PkRunningProcess>,
}

impl PyRunningProcess {
    fn running_mut(&mut self) -> PyResult<&mut PkRunningProcess> {
        self.inner
            .as_mut()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))
    }

    fn take_running(&mut self) -> PyResult<PkRunningProcess> {
        self.inner
            .take()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))
    }
}

#[pymethods]
impl PyRunningProcess {
    /// The OS process id, or `None` once the handle has been consumed/reaped.
    #[getter]
    fn pid(&self) -> Option<u32> {
        self.inner.as_ref().and_then(|running| running.pid())
    }

    /// Seconds elapsed since the process started, or `None` once consumed.
    #[getter]
    fn elapsed_seconds(&self) -> Option<f64> {
        self.inner.as_ref().map(|r| r.elapsed().as_secs_f64())
    }

    /// Cumulative CPU time so far in seconds, if measurable (`None` otherwise).
    #[getter]
    fn cpu_time_seconds(&self) -> Option<f64> {
        self.inner
            .as_ref()
            .and_then(|r| r.cpu_time())
            .map(|d| d.as_secs_f64())
    }

    /// Peak resident memory so far in bytes, if measurable (`None` otherwise).
    #[getter]
    fn peak_memory_bytes(&self) -> Option<u64> {
        self.inner.as_ref().and_then(|r| r.peak_memory_bytes())
    }

    /// Number of stdout lines captured so far (`None` once consumed).
    #[getter]
    fn stdout_line_count(&self) -> Option<usize> {
        self.inner.as_ref().map(|r| r.stdout_line_count())
    }

    /// Number of stderr lines captured so far (`None` once consumed).
    #[getter]
    fn stderr_line_count(&self) -> Option<usize> {
        self.inner.as_ref().map(|r| r.stderr_line_count())
    }

    /// Whether this handle owns a private tree — i.e. dropping it (or exiting its
    /// context manager) hard-kills the whole tree. `False` for a handle started
    /// inside a shared `ProcessGroup`; `None` once consumed.
    #[getter]
    fn owns_group(&self) -> Option<bool> {
        self.inner.as_ref().map(|r| r.kills_tree_on_drop())
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    /// Context-manager exit: tear the process down deterministically — a hard
    /// kill of the whole private tree for a standalone `start()`/`astart()`
    /// handle, or just this child for one started inside a `ProcessGroup`. A
    /// no-op if a consuming method (`wait`/`finish`/`output`/`shutdown`) already
    /// took the handle. Never suppresses an exception raised inside the block.
    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __exit__(
        &mut self,
        py: Python<'_>,
        _exc_type: Option<Bound<'_, PyAny>>,
        _exc_value: Option<Bound<'_, PyAny>>,
        _traceback: Option<Bound<'_, PyAny>>,
    ) -> PyResult<bool> {
        if let Some(mut running) = self.inner.take() {
            // Order is load-bearing: `start_kill` before `wait`. Killing first
            // guarantees `wait` reaps promptly even when stdin was handed out via
            // `take_stdin()` (the handle no longer owns the pipe to auto-close on
            // a `keep_stdin_open` child). `start_kill`/`wait` only touch the
            // direct child; the *whole private tree* is reaped when `wait`
            // consumes `running` and drops its owned process group, whose `Drop`
            // is kernel kill-on-close. So moving `running` into `wait` is not
            // redundant.
            block_on_interruptible(py, async move {
                running.start_kill()?;
                running.wait().await?;
                Ok::<(), processkit::Error>(())
            })?
            .map_err(map_err)?;
        }
        Ok(false)
    }

    fn __aenter__<'py>(slf: Py<Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        pyo3_async_runtimes::tokio::future_into_py(py, async move { Ok(slf) })
    }

    /// Async counterpart of `__exit__`.
    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __aexit__<'py>(
        &mut self,
        py: Python<'py>,
        _exc_type: Option<Bound<'py, PyAny>>,
        _exc_value: Option<Bound<'py, PyAny>>,
        _traceback: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let running = self.inner.take();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            if let Some(mut running) = running {
                running.start_kill().map_err(map_err)?;
                running.wait().await.map_err(map_err)?;
            }
            Ok(false)
        })
    }

    /// An async iterator over stdout, line by line:
    /// `async for line in proc.stdout_lines(): ...`.
    fn stdout_lines(&mut self) -> PyResult<PyStdoutLines> {
        // Setting up the stream spawns a pump task, so it must run inside the
        // tokio runtime context.
        let _guard = rt().enter();
        let lines = self.running_mut()?.stdout_lines().map_err(map_err)?;
        Ok(PyStdoutLines {
            inner: Arc::new(Mutex::new(lines)),
        })
    }

    /// An async iterator over stdout and stderr as interleaved `OutputEvent`s.
    fn output_events(&mut self) -> PyResult<PyOutputEvents> {
        let _guard = rt().enter();
        let events = self.running_mut()?.output_events().map_err(map_err)?;
        Ok(PyOutputEvents {
            inner: Arc::new(Mutex::new(events)),
        })
    }

    /// Take the writable stdin handle. Returns `None` if stdin was not piped or
    /// has already been taken.
    fn take_stdin(&mut self) -> PyResult<Option<PyProcessStdin>> {
        Ok(self
            .running_mut()?
            .take_stdin()
            .map(|stdin| PyProcessStdin {
                inner: Arc::new(Mutex::new(Some(stdin))),
            }))
    }

    /// Begin tearing the tree down without waiting. (Dropping the handle, or the
    /// owning group, also kills it; this just starts it early.)
    fn start_kill(&mut self) -> PyResult<()> {
        let _guard = rt().enter();
        self.running_mut()?.start_kill().map_err(map_err)
    }

    /// Await exit and return the `Outcome`. Consumes the handle.
    fn wait<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let running = self.take_running()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match running.wait().await {
                Ok(outcome) => Ok(PyOutcome { inner: outcome }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    /// Await exit and return `Finished` (outcome + captured stderr) without
    /// buffering stdout — use this after streaming stdout. Consumes the handle.
    fn finish<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let running = self.take_running()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match running.finish().await {
                Ok(finished) => Ok(PyFinished {
                    outcome: finished.outcome,
                    stderr: finished.stderr,
                }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    /// Await exit and capture the full `ProcessResult`. Consumes the handle.
    fn output<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let running = self.take_running()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match running.output_string().await {
                Ok(inner) => Ok(PyProcessResult { inner }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    /// Await exit and capture the full raw-bytes `BytesResult`. Consumes the handle.
    fn output_bytes<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let running = self.take_running()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match running.output_bytes().await {
                Ok(inner) => Ok(PyBytesResult { inner }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    /// Await exit while sampling resource usage every `every_seconds`, returning a
    /// `RunProfile`. Consumes the handle.
    fn profile<'py>(&mut self, py: Python<'py>, every_seconds: f64) -> PyResult<Bound<'py, PyAny>> {
        let every = positive_duration(every_seconds, "every_seconds")?;
        let running = self.take_running()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match running.profile(every).await {
                Ok(profile) => Ok(PyRunProfile { inner: profile }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    /// Gracefully tear down (signal, wait up to `grace_seconds`, then kill) and
    /// return the `Outcome`. Consumes the handle.
    fn shutdown<'py>(
        &mut self,
        py: Python<'py>,
        grace_seconds: f64,
    ) -> PyResult<Bound<'py, PyAny>> {
        let grace = nonnegative_duration(grace_seconds, "grace_seconds")?;
        let running = self.take_running()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match running.shutdown(grace).await {
                Ok(outcome) => Ok(PyOutcome { inner: outcome }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    fn __repr__(&self) -> String {
        match &self.inner {
            Some(running) => format!("RunningProcess(pid={:?})", running.pid()),
            None => "RunningProcess(consumed)".to_string(),
        }
    }
}
