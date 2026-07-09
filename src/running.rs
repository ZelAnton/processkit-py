//! The async streaming/interactive handles: `RunningProcess` plus its
//! `ProcessStdin`, `StdoutLines`, and `OutputEvents`.

use std::sync::{Arc, Mutex as StdMutex, MutexGuard as StdMutexGuard, PoisonError};

use processkit::prelude::StreamExt;
use processkit::OutputEvents as PkOutputEvents;
use processkit::ProcessStdin as PkProcessStdin;
use processkit::RunningProcess as PkRunningProcess;
use processkit::StdoutLines as PkStdoutLines;
use pyo3::exceptions::{PyOSError, PyStopAsyncIteration, PyValueError};
use pyo3::prelude::*;
use tokio::sync::Mutex;

use crate::convert::{nonnegative_duration, positive_duration};
use crate::errors::{map_err, ProcessError};
use crate::result::{
    PyBytesResult, PyFinished, PyOutcome, PyOutputEvent, PyProcessResult, PyRunProfile,
};
use crate::runtime::{block_on, drive_async, reject_reentrant_runtime, require_event_loop, rt};

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
            writer.write(&data).await.map_err(PyErr::from)
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
            writer.write_line(&line).await.map_err(PyErr::from)
        })
    }

    /// Send a single control byte to the child's stdin.
    fn send_control<'py>(
        &self,
        py: Python<'py>,
        control: String,
    ) -> PyResult<Bound<'py, PyAny>> {
        let mut chars = control.chars();
        let c = chars.next().ok_or_else(|| {
            PyValueError::new_err("send_control() requires exactly one control character")
        })?;
        if chars.next().is_some() {
            return Err(PyValueError::new_err(
                "send_control() requires exactly one control character",
            ));
        }

        let stdin = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let mut guard = stdin.lock().await;
            let writer = guard
                .as_mut()
                .ok_or_else(|| PyOSError::new_err("stdin is closed"))?;
            writer.send_control(c).await.map_err(|err| {
                if err.kind() == std::io::ErrorKind::InvalidInput {
                    PyValueError::new_err(err.to_string())
                } else {
                    PyErr::from(err)
                }
            })
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
            writer.flush().await.map_err(PyErr::from)
        })
    }

    /// Close stdin (sending EOF to the child). Idempotent.
    fn close<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stdin = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let writer = { stdin.lock().await.take() };
            match writer {
                Some(writer) => writer.finish().await.map_err(PyErr::from),
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
/// wait for its completion. The consuming verbs (`outcome`/`aoutcome`,
/// `finish`/`afinish`, `output`/`aoutput`, `output_bytes`/`aoutput_bytes`,
/// `profile`/`aprofile`, `shutdown`/`ashutdown`) each come in a sync/async
/// pair like everywhere else in this library — leave the handle spent after
/// either is called; using it afterwards raises. Usable as a context manager
/// (`with` / `async with`): exiting the block tears the process down — a hard
/// kill of the whole private tree for a standalone handle.
// `frozen` so every method takes `&self`: the consuming verbs used to take an
// exclusive `&mut self` PyO3 borrow and hold it across `block_on`/`drive_async`
// (i.e. across the whole wait, GIL released), so a concurrent `&self` call from
// another thread — even a plain getter or `__repr__` — raced the borrow flag
// and surfaced a raw `RuntimeError("Already borrowed")` instead of a typed
// `ProcessError`. The interior `Mutex<Option<...>>` serializes the access
// instead; the guard is always released (via the owned-returning helpers below)
// *before* any `block_on`/await, so a consumed handle reads back cleanly as
// `None` and the wait window is never held under the lock. The streaming
// handles (`ProcessStdin`/`StdoutLines`/`OutputEvents`) keep their own
// `tokio::sync::Mutex` for their async-held stream state — unchanged.
#[pyclass(name = "RunningProcess", module = "processkit", frozen)]
pub(crate) struct PyRunningProcess {
    // `None` after a consuming method has taken ownership of the process.
    pub(crate) inner: StdMutex<Option<PkRunningProcess>>,
}

impl From<PkRunningProcess> for PyRunningProcess {
    fn from(running: PkRunningProcess) -> Self {
        Self {
            inner: StdMutex::new(Some(running)),
        }
    }
}

impl PyRunningProcess {
    /// Lock the inner slot, recovering from a (never-expected) poisoned mutex
    /// rather than panicking across the FFI boundary — the guarded sections only
    /// read/`as_mut`/`take` the handle and never panic, so poisoning cannot
    /// actually happen.
    fn lock(&self) -> StdMutexGuard<'_, Option<PkRunningProcess>> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Take the process out, returning `None` if the handle was already
    /// consumed. The lock is released before this returns, so a teardown never
    /// holds it across the subsequent `block_on`/await.
    fn take(&self) -> Option<PkRunningProcess> {
        self.lock().take()
    }

    /// Take the process out for a consuming verb, erroring if already consumed.
    /// Like `take`, releases the lock before returning.
    fn take_running(&self) -> PyResult<PkRunningProcess> {
        self.take()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))
    }
}

/// Shared teardown for both `__exit__` and `__aexit__`: a hard kill of the
/// direct child, then wait for it to be reaped.
///
/// Order is load-bearing: `start_kill` before `wait`. Killing first guarantees
/// `wait` reaps promptly even when stdin was handed out via `take_stdin()`
/// (the handle no longer owns the pipe to auto-close on a `keep_stdin_open`
/// child). `start_kill`/`wait` only touch the direct child; the *whole
/// private tree* is reaped when `wait` consumes `running` and drops its owned
/// process group, whose `Drop` is kernel kill-on-close. So moving `running`
/// into `wait` is not redundant.
async fn kill_and_reap(mut running: PkRunningProcess) -> processkit::Result<()> {
    running.start_kill()?;
    running.wait().await?;
    Ok(())
}

#[pymethods]
impl PyRunningProcess {
    /// The OS process id, or `None` once the handle has been consumed/reaped.
    #[getter]
    fn pid(&self) -> Option<u32> {
        self.lock().as_ref().and_then(|running| running.pid())
    }

    /// Seconds elapsed since the process started, or `None` once consumed.
    #[getter]
    fn elapsed_seconds(&self) -> Option<f64> {
        self.lock().as_ref().map(|r| r.elapsed().as_secs_f64())
    }

    /// Cumulative CPU time so far in seconds, if measurable (`None` otherwise).
    #[getter]
    fn cpu_time_seconds(&self) -> Option<f64> {
        self.lock()
            .as_ref()
            .and_then(|r| r.cpu_time())
            .map(|d| d.as_secs_f64())
    }

    /// Peak resident memory so far in bytes, if measurable (`None` otherwise).
    #[getter]
    fn peak_memory_bytes(&self) -> Option<u64> {
        self.lock().as_ref().and_then(|r| r.peak_memory_bytes())
    }

    /// Number of stdout lines captured so far (`None` once consumed).
    #[getter]
    fn stdout_line_count(&self) -> Option<usize> {
        self.lock().as_ref().map(|r| r.stdout_line_count())
    }

    /// Number of stderr lines captured so far (`None` once consumed).
    #[getter]
    fn stderr_line_count(&self) -> Option<usize> {
        self.lock().as_ref().map(|r| r.stderr_line_count())
    }

    /// Whether this handle owns a private tree — i.e. dropping it (or exiting its
    /// context manager) hard-kills the whole tree. `False` for a handle started
    /// inside a shared `ProcessGroup`; `None` once consumed.
    #[getter]
    fn owns_group(&self) -> Option<bool> {
        self.lock().as_ref().map(|r| r.kills_tree_on_drop())
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    /// Context-manager exit: tear the process down deterministically — a hard
    /// kill of the whole private tree for a standalone `start()`/`astart()`
    /// handle, or just this child for one started inside a `ProcessGroup`. A
    /// no-op if a consuming verb (`outcome`/`finish`/`output`/`output_bytes`/
    /// `profile`/`shutdown`, or their `a`-prefixed twins) already took the
    /// handle. Never suppresses an exception raised inside the block.
    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __exit__(
        &self,
        py: Python<'_>,
        _exc_type: Option<Bound<'_, PyAny>>,
        _exc_value: Option<Bound<'_, PyAny>>,
        _traceback: Option<Bound<'_, PyAny>>,
    ) -> PyResult<bool> {
        // Check before taking: a reentrant-runtime error from `block_on` after the
        // handle is taken would drop (kill-on-drop) a process the caller could
        // otherwise have torn down correctly from the right context. `take()`
        // releases the lock before `block_on`, so a concurrent getter/`__repr__`
        // on another thread reads back `None` cleanly rather than blocking on the
        // teardown wait.
        reject_reentrant_runtime()?;
        if let Some(running) = self.take() {
            block_on(py, kill_and_reap(running))?;
        }
        Ok(false)
    }

    fn __aenter__<'py>(slf: Py<Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        pyo3_async_runtimes::tokio::future_into_py(py, async move { Ok(slf) })
    }

    /// Async counterpart of `__exit__`.
    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __aexit__<'py>(
        &self,
        py: Python<'py>,
        _exc_type: Option<Bound<'py, PyAny>>,
        _exc_value: Option<Bound<'py, PyAny>>,
        _traceback: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Check before taking: a synchronously-failing `drive_async` (no running
        // event loop) would otherwise drop the just-taken handle (kill-on-drop)
        // instead of leaving it in place for the caller to retry correctly.
        require_event_loop(py)?;
        let running = self.take();
        drive_async(py, async move {
            if let Some(running) = running {
                kill_and_reap(running).await?;
            }
            Ok::<bool, processkit::Error>(false)
        })
    }

    /// An async iterator over stdout, line by line:
    /// `async for line in proc.stdout_lines(): ...`.
    fn stdout_lines(&self) -> PyResult<PyStdoutLines> {
        // Setting up the stream spawns a pump task, so it must run inside the
        // tokio runtime context. Holding the std lock across this sync call is
        // safe: it does not await, so it cannot deadlock a concurrent verb.
        let _guard = rt().enter();
        let mut inner = self.lock();
        let running = inner
            .as_mut()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
        let lines = running.stdout_lines().map_err(map_err)?;
        Ok(PyStdoutLines {
            inner: Arc::new(Mutex::new(lines)),
        })
    }

    /// An async iterator over stdout and stderr as interleaved `OutputEvent`s.
    fn output_events(&self) -> PyResult<PyOutputEvents> {
        let _guard = rt().enter();
        let mut inner = self.lock();
        let running = inner
            .as_mut()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
        let events = running.output_events().map_err(map_err)?;
        Ok(PyOutputEvents {
            inner: Arc::new(Mutex::new(events)),
        })
    }

    /// Take the writable stdin handle. Raises `ProcessError` if stdin was not
    /// kept open (build the `Command` with `keep_stdin_open()`) or was already
    /// taken — so a missing setup fails here with a clear message, not later with
    /// an `AttributeError` on a `None`.
    fn take_stdin(&self) -> PyResult<PyProcessStdin> {
        let mut inner = self.lock();
        let running = inner
            .as_mut()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
        running
            .take_stdin()
            .map(|stdin| PyProcessStdin {
                inner: Arc::new(Mutex::new(Some(stdin))),
            })
            .ok_or_else(|| {
                ProcessError::new_err(
                    "stdin is not available — build the Command with keep_stdin_open() \
                     and call take_stdin() only once (scripted test doubles never \
                     provide stdin)",
                )
            })
    }

    /// Begin tearing the tree down without waiting. (Dropping the handle, or the
    /// owning group, also kills it; this just starts it early.) Mirrors
    /// `subprocess.Popen.kill()`: fire-and-forget, does not wait for exit.
    fn kill(&self) -> PyResult<()> {
        let _guard = rt().enter();
        let mut inner = self.lock();
        let running = inner
            .as_mut()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
        running.start_kill().map_err(map_err)
    }

    /// Wait for exit and return the `Outcome`. Consumes the handle. The
    /// synchronous twin of `aoutcome()` — usable on a handle from either
    /// `start()` or `astart()`, like every other sync/async verb pair in
    /// this library.
    fn outcome(&self, py: Python<'_>) -> PyResult<PyOutcome> {
        // Checked before `take_running()`: see the comment on `reject_reentrant_runtime`.
        reject_reentrant_runtime()?;
        let running = self.take_running()?;
        block_on(py, async move { running.wait().await }).map(PyOutcome::from)
    }

    /// Async counterpart of `outcome()`. (Named `aoutcome`, not `await` — a
    /// reserved word can't be a method name.)
    fn aoutcome<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        // Checked before `take_running()`: see the comment on `require_event_loop`.
        require_event_loop(py)?;
        let running = self.take_running()?;
        drive_async(py, async move { running.wait().await.map(PyOutcome::from) })
    }

    /// Wait for exit and return `Finished` (outcome + captured stderr) without
    /// buffering stdout — use this after streaming stdout. Consumes the handle.
    fn finish(&self, py: Python<'_>) -> PyResult<PyFinished> {
        reject_reentrant_runtime()?;
        let running = self.take_running()?;
        block_on(py, async move { running.finish().await }).map(PyFinished::from)
    }

    /// Async counterpart of `finish()`.
    fn afinish<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        let running = self.take_running()?;
        drive_async(
            py,
            async move { running.finish().await.map(PyFinished::from) },
        )
    }

    /// Wait for exit and capture the full `ProcessResult`. Consumes the handle.
    fn output(&self, py: Python<'_>) -> PyResult<PyProcessResult> {
        reject_reentrant_runtime()?;
        let running = self.take_running()?;
        block_on(py, async move { running.output_string().await }).map(PyProcessResult::from)
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        let running = self.take_running()?;
        drive_async(py, async move {
            running.output_string().await.map(PyProcessResult::from)
        })
    }

    /// Wait for exit and capture the full raw-bytes `BytesResult`. Consumes the handle.
    fn output_bytes(&self, py: Python<'_>) -> PyResult<PyBytesResult> {
        reject_reentrant_runtime()?;
        let running = self.take_running()?;
        block_on(py, async move { running.output_bytes().await }).map(PyBytesResult::from)
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        let running = self.take_running()?;
        drive_async(py, async move {
            running.output_bytes().await.map(PyBytesResult::from)
        })
    }

    /// Wait for exit while sampling resource usage every `every_seconds`,
    /// returning a `RunProfile`. Consumes the handle.
    fn profile(&self, py: Python<'_>, every_seconds: f64) -> PyResult<PyRunProfile> {
        let every = positive_duration(every_seconds, "every_seconds")?;
        reject_reentrant_runtime()?;
        let running = self.take_running()?;
        block_on(py, async move { running.profile(every).await }).map(PyRunProfile::from)
    }

    /// Async counterpart of `profile()`.
    fn aprofile<'py>(&self, py: Python<'py>, every_seconds: f64) -> PyResult<Bound<'py, PyAny>> {
        let every = positive_duration(every_seconds, "every_seconds")?;
        require_event_loop(py)?;
        let running = self.take_running()?;
        drive_async(py, async move {
            running.profile(every).await.map(PyRunProfile::from)
        })
    }

    /// Gracefully tear down (signal, wait up to `grace_seconds`, then kill) and
    /// return the `Outcome`. Consumes the handle. Named `shutdown`/`ashutdown`
    /// to match `ProcessGroup.shutdown()`/`ashutdown()` — same verb, same
    /// sync/async pairing convention, unlike the pre-1.1 `RunningProcess`
    /// where `shutdown()` was itself a coroutine (a trap: the same verb name
    /// meant "call it" on a `ProcessGroup` but "await it" here).
    fn shutdown(&self, py: Python<'_>, grace_seconds: f64) -> PyResult<PyOutcome> {
        let grace = nonnegative_duration(grace_seconds, "grace_seconds")?;
        reject_reentrant_runtime()?;
        let running = self.take_running()?;
        block_on(py, async move { running.shutdown(grace).await }).map(PyOutcome::from)
    }

    /// Async counterpart of `shutdown()`.
    fn ashutdown<'py>(&self, py: Python<'py>, grace_seconds: f64) -> PyResult<Bound<'py, PyAny>> {
        let grace = nonnegative_duration(grace_seconds, "grace_seconds")?;
        require_event_loop(py)?;
        let running = self.take_running()?;
        drive_async(py, async move {
            running.shutdown(grace).await.map(PyOutcome::from)
        })
    }

    fn __repr__(&self) -> String {
        match self.lock().as_ref() {
            Some(running) => format!("RunningProcess(pid={:?})", running.pid()),
            None => "RunningProcess(consumed)".to_string(),
        }
    }
}

/// Register this module's pyclasses (`RunningProcess`, `ProcessStdin`,
/// `StdoutLines`, `OutputEvents`) on `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyRunningProcess>()?;
    m.add_class::<PyProcessStdin>()?;
    m.add_class::<PyStdoutLines>()?;
    m.add_class::<PyOutputEvents>()?;
    Ok(())
}
