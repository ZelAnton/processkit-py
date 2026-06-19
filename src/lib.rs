//! PyO3 bindings to the `processkit` Rust crate — a thin binding, not a
//! reimplementation. The crate is async-throughout (tokio); this layer owns the
//! single tokio runtime (`pyo3-async-runtimes`' managed runtime) and drives the
//! crate's futures to completion for the synchronous surface. The GIL is
//! released around every blocking call so other Python threads run, and the
//! wait is broken into ticks so that `Ctrl+C` interrupts a blocked call.

use std::path::PathBuf;
use std::time::Duration;

use processkit::Command as PkCommand;
use processkit::Mechanism;
use processkit::ProcessGroup as PkProcessGroup;
use processkit::ProcessResult as PkProcessResult;
use processkit::RunningProcess as PkRunningProcess;
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::prelude::*;

/// The one tokio runtime the binding owns, shared by the sync surface
/// (`block_on`) and the async surface (`future_into_py`).
fn rt() -> &'static tokio::runtime::Runtime {
    pyo3_async_runtimes::tokio::get_runtime()
}

/// How often a blocked sync call surfaces to check for pending Python signals.
const SIGNAL_POLL_INTERVAL: Duration = Duration::from_millis(100);

/// Drive a future to completion with the GIL released, re-acquiring it on a
/// fixed tick to honour pending signals (notably `Ctrl+C`). A fast future
/// returns on the first tick with no added latency; a slow one yields every
/// `SIGNAL_POLL_INTERVAL` so `Python::check_signals` can raise. When it raises,
/// `fut` is dropped here — which, for a run that owns its process group, tears
/// the tree down.
fn block_on_interruptible<F, T>(py: Python<'_>, fut: F) -> PyResult<T>
where
    F: std::future::Future<Output = T> + Send,
    T: Send,
{
    let mut fut = std::pin::pin!(fut);
    loop {
        let step = py.detach(|| {
            rt().block_on(async { tokio::time::timeout(SIGNAL_POLL_INTERVAL, fut.as_mut()).await })
        });
        match step {
            Ok(value) => return Ok(value),
            // The tick elapsed without completion — let Python run its signal
            // handlers, then keep waiting.
            Err(_elapsed) => py.check_signals()?,
        }
    }
}

// Exception hierarchy: a single `ProcessError` root with one subclass per
// failure mode the crate distinguishes. Builtin/asyncio aliasing is layered in
// the Python package (`__init__.py`), not here.
create_exception!(_processkit, ProcessError, PyException);
create_exception!(_processkit, NonZeroExit, ProcessError);
create_exception!(_processkit, Timeout, ProcessError);
create_exception!(_processkit, Cancelled, ProcessError);
create_exception!(_processkit, Signalled, ProcessError);
create_exception!(_processkit, ProcessNotFound, ProcessError);
create_exception!(_processkit, Unsupported, ProcessError);

/// Map a crate `Error` onto the Python exception hierarchy and attach the
/// structured fields the variant carries (`code`, `stdout`, `stderr`,
/// `program`, `signal`, `timeout_seconds`) so callers can inspect a failure
/// programmatically, not just read its message.
///
/// `Error` is `#[non_exhaustive]`, so the wildcard arm both covers the rarer
/// variants (`Io`, `Parse`, `Stdin`, `OutputTooLarge`, …) and stays
/// forward-compatible.
fn map_err(py: Python<'_>, error: processkit::Error) -> PyErr {
    use processkit::Error as E;
    use std::io::ErrorKind;

    let message = error.to_string();
    let err = match &error {
        E::Timeout { .. } => Timeout::new_err(message),
        E::Cancelled { .. } => Cancelled::new_err(message),
        E::Exit { .. } => NonZeroExit::new_err(message),
        E::Signalled { .. } => Signalled::new_err(message),
        E::NotFound { .. } => ProcessNotFound::new_err(message),
        // The real spawn path reports a missing program as `Spawn` carrying an
        // `io::Error` of kind `NotFound`; surface that as `ProcessNotFound` too.
        E::Spawn { source, .. } if source.kind() == ErrorKind::NotFound => {
            ProcessNotFound::new_err(message)
        }
        E::Unsupported { .. } => Unsupported::new_err(message),
        _ => ProcessError::new_err(message),
    };

    // Attach structured fields. `setattr` failures are ignored: the typed
    // exception with its message is already a faithful error.
    let value = err.value(py);
    match &error {
        E::Exit {
            code,
            program,
            stdout,
            stderr,
        } => {
            let _ = value.setattr("program", program.as_str());
            let _ = value.setattr("code", *code);
            let _ = value.setattr("stdout", stdout.as_str());
            let _ = value.setattr("stderr", stderr.as_str());
        }
        E::Signalled {
            program,
            signal,
            stdout,
            stderr,
        } => {
            let _ = value.setattr("program", program.as_str());
            let _ = value.setattr("signal", *signal);
            let _ = value.setattr("stdout", stdout.as_str());
            let _ = value.setattr("stderr", stderr.as_str());
        }
        E::Timeout {
            program,
            timeout,
            stdout,
            stderr,
        } => {
            let _ = value.setattr("program", program.as_str());
            let _ = value.setattr("timeout_seconds", timeout.as_secs_f64());
            let _ = value.setattr("stdout", stdout.as_str());
            let _ = value.setattr("stderr", stderr.as_str());
        }
        E::NotFound { program, .. } | E::Spawn { program, .. } | E::Cancelled { program } => {
            let _ = value.setattr("program", program.as_str());
        }
        _ => {}
    }
    err
}

/// The captured result of a finished run. A non-zero exit, a timeout, and a
/// signal-kill are all *data* here — `output()` never raises on them.
#[pyclass(name = "ProcessResult", frozen, module = "processkit")]
struct PyProcessResult {
    inner: PkProcessResult<String>,
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

/// A command builder. Builder methods return a new `Command`, so a configured
/// command is reusable and chains read left to right.
#[pyclass(name = "Command", module = "processkit")]
struct PyCommand {
    inner: PkCommand,
}

#[pymethods]
impl PyCommand {
    #[new]
    #[pyo3(signature = (program, args = None))]
    fn new(program: PathBuf, args: Option<Vec<String>>) -> Self {
        // `PathBuf` so a `str`, `bytes`, or any `os.PathLike` is accepted —
        // matching how Python's own subprocess APIs take a program.
        let mut inner = PkCommand::new(program);
        if let Some(args) = args {
            inner = inner.args(args);
        }
        Self { inner }
    }

    fn arg(&self, arg: &str) -> Self {
        Self {
            inner: self.inner.clone().arg(arg),
        }
    }

    fn args(&self, args: Vec<String>) -> Self {
        Self {
            inner: self.inner.clone().args(args),
        }
    }

    fn cwd(&self, path: PathBuf) -> Self {
        Self {
            inner: self.inner.clone().current_dir(path),
        }
    }

    fn env(&self, key: &str, value: &str) -> Self {
        Self {
            inner: self.inner.clone().env(key, value),
        }
    }

    /// Set a wall-clock timeout. On expiry the whole tree is killed; `output()`
    /// reports it as `timed_out`, while `run()` / `exit_code()` raise `Timeout`.
    fn timeout(&self, seconds: f64) -> PyResult<Self> {
        if !seconds.is_finite() || seconds <= 0.0 {
            return Err(PyValueError::new_err(
                "timeout must be a positive, finite number of seconds",
            ));
        }
        // `try_from_secs_f64` (not `from_secs_f64`) so a finite-but-huge value
        // that overflows `Duration` is a clean error, not a Rust panic.
        let duration = Duration::try_from_secs_f64(seconds)
            .map_err(|err| PyValueError::new_err(format!("invalid timeout: {err}")))?;
        Ok(Self {
            inner: self.inner.clone().timeout(duration),
        })
    }

    /// Run to completion and capture output. A non-zero exit is data, not an
    /// error — inspect `code` / `is_success` on the result.
    fn output(&self, py: Python<'_>) -> PyResult<PyProcessResult> {
        match block_on_interruptible(py, self.inner.output_string())? {
            Ok(inner) => Ok(PyProcessResult { inner }),
            Err(err) => Err(map_err(py, err)),
        }
    }

    /// Require a zero exit and return stdout, trailing whitespace trimmed.
    /// Raises `NonZeroExit` (or `Timeout` / `Signalled`) otherwise.
    fn run(&self, py: Python<'_>) -> PyResult<String> {
        block_on_interruptible(py, self.inner.run())?.map_err(|err| map_err(py, err))
    }

    /// The exit code; a timeout / signal-kill raises rather than returning a
    /// sentinel.
    fn exit_code(&self, py: Python<'_>) -> PyResult<i32> {
        block_on_interruptible(py, self.inner.exit_code())?.map_err(|err| map_err(py, err))
    }

    /// Run a predicate command and read its exit code as a bool: `0` → `True`,
    /// `1` → `False`, anything else raises.
    fn probe(&self, py: Python<'_>) -> PyResult<bool> {
        block_on_interruptible(py, self.inner.probe())?.map_err(|err| map_err(py, err))
    }

    /// Async counterpart of `output()`. Awaitable under asyncio; cancelling the
    /// awaiting task tears down the process tree (the run's transient job is
    /// dropped) and raises `asyncio.CancelledError`.
    ///
    /// Provisional: the async surface is finalised in Phase 2 (streaming,
    /// `async with ProcessGroup`).
    fn aoutput<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match cmd.output_string().await {
                Ok(inner) => Ok(PyProcessResult { inner }),
                Err(err) => Err(Python::attach(|py| map_err(py, err))),
            }
        })
    }

    /// Async counterpart of `run()`. See `aoutput` for cancellation semantics.
    fn arun<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            cmd.run()
                .await
                .map_err(|err| Python::attach(|py| map_err(py, err)))
        })
    }

    fn __repr__(&self) -> String {
        format!("Command({:?})", self.inner.command_line())
    }
}

/// A handle to a process started inside a `ProcessGroup`. Phase 1 exposes only
/// its identity; streaming and interactive I/O arrive with the async surface.
#[pyclass(name = "RunningProcess", module = "processkit")]
struct PyRunningProcess {
    inner: PkRunningProcess,
}

#[pymethods]
impl PyRunningProcess {
    /// The OS process id, or `None` if the child has already been reaped.
    #[getter]
    fn pid(&self) -> Option<u32> {
        self.inner.pid()
    }

    fn __repr__(&self) -> String {
        format!("RunningProcess(pid={:?})", self.inner.pid())
    }
}

/// A kill-on-drop container for a process *tree*. Use it as a context manager:
/// every process started inside, and everything those processes spawn, is torn
/// down when the `with` block exits.
///
/// The teardown asymmetry is load-bearing and honest: on Windows the Job Object
/// reaps the tree when the last handle closes (kernel-enforced); on Linux/macOS
/// teardown is driven from the `__exit__` path and is best-effort if the
/// interpreter is hard-killed.
#[pyclass(name = "ProcessGroup", module = "processkit")]
struct PyProcessGroup {
    // `None` after the group is shut down — every method then errors cleanly.
    inner: Option<PkProcessGroup>,
}

impl PyProcessGroup {
    fn group(&self) -> PyResult<&PkProcessGroup> {
        self.inner
            .as_ref()
            .ok_or_else(|| ProcessError::new_err("ProcessGroup is already closed"))
    }
}

#[pymethods]
impl PyProcessGroup {
    #[new]
    fn new(py: Python<'_>) -> PyResult<Self> {
        PkProcessGroup::new()
            .map(|group| Self { inner: Some(group) })
            .map_err(|err| map_err(py, err))
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __exit__<'py>(
        &mut self,
        py: Python<'py>,
        _exc_type: Option<Bound<'py, PyAny>>,
        _exc_value: Option<Bound<'py, PyAny>>,
        _traceback: Option<Bound<'py, PyAny>>,
    ) -> PyResult<bool> {
        self.shutdown(py)?;
        // Never suppress an exception raised inside the `with` block.
        Ok(false)
    }

    /// Start a command inside the group and return a handle. The process runs
    /// concurrently; this does not wait for it to finish.
    fn start(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyRunningProcess> {
        let group = self.group()?;
        let running = block_on_interruptible(py, group.start(&command.inner))?
            .map_err(|err| map_err(py, err))?;
        Ok(PyRunningProcess { inner: running })
    }

    /// The containment mechanism in use: `"job_object"` (Windows),
    /// `"cgroup_v2"` (Linux), or `"process_group"` (POSIX fallback).
    #[getter]
    fn mechanism(&self) -> PyResult<&'static str> {
        let mechanism = match self.group()?.mechanism() {
            Mechanism::JobObject => "job_object",
            Mechanism::CgroupV2 => "cgroup_v2",
            Mechanism::ProcessGroup => "process_group",
            _ => "unknown",
        };
        Ok(mechanism)
    }

    /// The process ids currently contained by the group.
    fn members(&self, py: Python<'_>) -> PyResult<Vec<u32>> {
        self.group()?.members().map_err(|err| map_err(py, err))
    }

    /// Tear down the whole tree gracefully (signal, bounded wait, then kill on
    /// POSIX; atomic on Windows). Idempotent — a second call is a no-op.
    fn shutdown(&mut self, py: Python<'_>) -> PyResult<()> {
        if let Some(group) = self.inner.take() {
            block_on_interruptible(py, group.shutdown())?.map_err(|err| map_err(py, err))?;
        }
        Ok(())
    }

    fn __repr__(&self) -> String {
        match &self.inner {
            Some(_) => "ProcessGroup(open)".to_string(),
            None => "ProcessGroup(closed)".to_string(),
        }
    }
}

#[pymodule]
fn _processkit(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCommand>()?;
    m.add_class::<PyProcessResult>()?;
    m.add_class::<PyProcessGroup>()?;
    m.add_class::<PyRunningProcess>()?;

    let py = m.py();
    m.add("ProcessError", py.get_type::<ProcessError>())?;
    m.add("NonZeroExit", py.get_type::<NonZeroExit>())?;
    m.add("Timeout", py.get_type::<Timeout>())?;
    m.add("Cancelled", py.get_type::<Cancelled>())?;
    m.add("Signalled", py.get_type::<Signalled>())?;
    m.add("ProcessNotFound", py.get_type::<ProcessNotFound>())?;
    m.add("Unsupported", py.get_type::<Unsupported>())?;
    Ok(())
}
