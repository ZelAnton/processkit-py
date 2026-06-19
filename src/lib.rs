//! PyO3 bindings to the `processkit` Rust crate — a thin binding, not a
//! reimplementation. The crate is async-throughout (tokio); this layer owns the
//! single tokio runtime (`pyo3-async-runtimes`' managed runtime) and drives the
//! crate's futures to completion for the synchronous surface. The GIL is
//! released around every blocking call so other Python threads run, and the
//! wait is broken into ticks so that `Ctrl+C` interrupts a blocked call.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use processkit::Command as PkCommand;
use processkit::JobRunner;
use processkit::Mechanism;
use processkit::Outcome as PkOutcome;
use processkit::OutputEvent as PkOutputEvent;
use processkit::OutputEvents as PkOutputEvents;
use processkit::Pipeline as PkPipeline;
use processkit::ProcessGroup as PkProcessGroup;
use processkit::ProcessGroupOptions;
use processkit::ProcessResult as PkProcessResult;
use processkit::ProcessStdin as PkProcessStdin;
use processkit::RestartPolicy;
use processkit::RunningProcess as PkRunningProcess;
use processkit::Signal as PkSignal;
use processkit::Stdin as PkStdin;
use processkit::StdoutLines as PkStdoutLines;
use processkit::StopReason;
use processkit::StreamExt;
use processkit::SupervisionOutcome;
use processkit::Supervisor as PkSupervisor;
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyOSError, PyStopAsyncIteration, PyValueError};
use pyo3::prelude::*;
use tokio::sync::Mutex;

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
create_exception!(_processkit, ResourceLimit, ProcessError);
create_exception!(_processkit, Unsupported, ProcessError);

/// Validate and convert a positive number of seconds into a `Duration`.
fn positive_duration(seconds: f64, what: &str) -> PyResult<Duration> {
    if !seconds.is_finite() || seconds <= 0.0 {
        return Err(PyValueError::new_err(format!(
            "{what} must be a positive, finite number of seconds"
        )));
    }
    Duration::try_from_secs_f64(seconds)
        .map_err(|err| PyValueError::new_err(format!("invalid {what}: {err}")))
}

/// Parse a restart policy name into a crate `RestartPolicy`.
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

/// Render a `StopReason` as a stable lowercase string.
fn stop_reason_str(reason: StopReason) -> &'static str {
    match reason {
        StopReason::PolicySatisfied => "policy_satisfied",
        StopReason::Predicate => "predicate",
        StopReason::RestartsExhausted => "restarts_exhausted",
        _ => "unknown",
    }
}

/// Parse a signal name (`"term"`, `"kill"`, `"int"`, `"hup"`, `"quit"`,
/// `"usr1"`, `"usr2"`; a `"sig"` prefix is accepted) into a crate `Signal`.
fn parse_signal(name: &str) -> PyResult<PkSignal> {
    let key = name.to_ascii_lowercase();
    let key = key.strip_prefix("sig").unwrap_or(&key);
    match key {
        "term" => Ok(PkSignal::Term),
        "kill" => Ok(PkSignal::Kill),
        "int" => Ok(PkSignal::Int),
        "hup" => Ok(PkSignal::Hup),
        "quit" => Ok(PkSignal::Quit),
        "usr1" => Ok(PkSignal::Usr1),
        "usr2" => Ok(PkSignal::Usr2),
        _ => Err(PyValueError::new_err(format!(
            "unknown signal {name:?}; use one of: term, kill, int, hup, quit, usr1, usr2"
        ))),
    }
}

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
        E::ResourceLimit { .. } => ResourceLimit::new_err(message),
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

/// Map a stdin I/O failure (a broken pipe, a closed child) onto `OSError`.
fn map_io_err(error: std::io::Error) -> PyErr {
    PyOSError::new_err(error.to_string())
}

/// How a process ended: a clean exit code, a signal-kill, or a timeout.
#[pyclass(name = "Outcome", frozen, module = "processkit")]
struct PyOutcome {
    inner: PkOutcome,
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
struct PyOutputEvent {
    is_stderr: bool,
    text: String,
}

impl PyOutputEvent {
    fn from_event(event: PkOutputEvent) -> Self {
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
struct PyFinished {
    outcome: PkOutcome,
    stderr: String,
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

/// A writable handle to a running process's stdin. Obtain it once via
/// `RunningProcess.take_stdin()`; all methods are awaitable.
#[pyclass(name = "ProcessStdin", module = "processkit")]
struct PyProcessStdin {
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
struct PyStdoutLines {
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
struct PyOutputEvents {
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

    /// Feed the given bytes to the child's stdin, then close it (EOF).
    fn stdin_bytes(&self, data: Vec<u8>) -> Self {
        Self {
            inner: self.inner.clone().stdin(PkStdin::from_bytes(data)),
        }
    }

    /// Feed the given text to the child's stdin, then close it (EOF).
    fn stdin_text(&self, text: String) -> Self {
        Self {
            inner: self.inner.clone().stdin(PkStdin::from_string(text)),
        }
    }

    /// Keep stdin piped and open for interactive writing after the process
    /// starts, via `RunningProcess.take_stdin()`.
    fn keep_stdin_open(&self) -> Self {
        Self {
            inner: self.inner.clone().keep_stdin_open(),
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

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            cmd.exit_code()
                .await
                .map_err(|err| Python::attach(|py| map_err(py, err)))
        })
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            cmd.probe()
                .await
                .map_err(|err| Python::attach(|py| map_err(py, err)))
        })
    }

    /// Start the command and return a `RunningProcess` for streaming and
    /// interactive I/O. The process runs concurrently — this resolves as soon as
    /// it has spawned, not when it finishes.
    fn astart<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match cmd.start().await {
                Ok(running) => Ok(PyRunningProcess {
                    inner: Some(running),
                }),
                Err(err) => Err(Python::attach(|py| map_err(py, err))),
            }
        })
    }

    /// Pipe this command's stdout into `other`'s stdin, returning a `Pipeline`.
    /// Equivalent to `self | other`.
    fn pipe(&self, other: &PyCommand) -> PyPipeline {
        PyPipeline {
            inner: self.inner.clone().pipe(other.inner.clone()),
        }
    }

    fn __or__(&self, other: &PyCommand) -> PyPipeline {
        self.pipe(other)
    }

    fn __repr__(&self) -> String {
        format!("Command({:?})", self.inner.command_line())
    }
}

/// A shell-free pipeline `a | b | c`: each stage's stdout feeds the next's
/// stdin, all in one process group, with pipefail outcome semantics.
#[pyclass(name = "Pipeline", module = "processkit")]
struct PyPipeline {
    inner: PkPipeline,
}

#[pymethods]
impl PyPipeline {
    /// Extend the pipeline with another stage. Equivalent to `self | other`.
    fn pipe(&self, other: &PyCommand) -> Self {
        Self {
            inner: self.inner.clone().pipe(other.inner.clone()),
        }
    }

    fn __or__(&self, other: &PyCommand) -> Self {
        self.pipe(other)
    }

    /// Set a wall-clock timeout for the whole pipeline.
    fn timeout(&self, seconds: f64) -> PyResult<Self> {
        if !seconds.is_finite() || seconds <= 0.0 {
            return Err(PyValueError::new_err(
                "timeout must be a positive, finite number of seconds",
            ));
        }
        let duration = Duration::try_from_secs_f64(seconds)
            .map_err(|err| PyValueError::new_err(format!("invalid timeout: {err}")))?;
        Ok(Self {
            inner: self.inner.clone().timeout(duration),
        })
    }

    /// Run the pipeline and capture the last stage's output (sync).
    fn output(&self, py: Python<'_>) -> PyResult<PyProcessResult> {
        match block_on_interruptible(py, self.inner.output_string())? {
            Ok(inner) => Ok(PyProcessResult { inner }),
            Err(err) => Err(map_err(py, err)),
        }
    }

    /// Require success and return the last stage's trimmed stdout (sync).
    fn run(&self, py: Python<'_>) -> PyResult<String> {
        block_on_interruptible(py, self.inner.run())?.map_err(|err| map_err(py, err))
    }

    /// The pipeline's exit code (sync).
    fn exit_code(&self, py: Python<'_>) -> PyResult<i32> {
        block_on_interruptible(py, self.inner.exit_code())?.map_err(|err| map_err(py, err))
    }

    /// Run a predicate pipeline and read its exit code as a bool (sync).
    fn probe(&self, py: Python<'_>) -> PyResult<bool> {
        block_on_interruptible(py, self.inner.probe())?.map_err(|err| map_err(py, err))
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match pipeline.output_string().await {
                Ok(inner) => Ok(PyProcessResult { inner }),
                Err(err) => Err(Python::attach(|py| map_err(py, err))),
            }
        })
    }

    /// Async counterpart of `run()`.
    fn arun<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            pipeline
                .run()
                .await
                .map_err(|err| Python::attach(|py| map_err(py, err)))
        })
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            pipeline
                .exit_code()
                .await
                .map_err(|err| Python::attach(|py| map_err(py, err)))
        })
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            pipeline
                .probe()
                .await
                .map_err(|err| Python::attach(|py| map_err(py, err)))
        })
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.inner)
    }
}

/// A handle to a started process: stream its output, write to its stdin, and
/// await its completion. The consuming methods (`wait`, `finish`, `output`,
/// `shutdown`) leave the handle spent; using it afterwards raises.
#[pyclass(name = "RunningProcess", module = "processkit")]
struct PyRunningProcess {
    // `None` after a consuming method has taken ownership of the process.
    inner: Option<PkRunningProcess>,
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

    /// An async iterator over stdout, line by line:
    /// `async for line in proc.stdout_lines(): ...`.
    fn stdout_lines(&mut self, py: Python<'_>) -> PyResult<PyStdoutLines> {
        // Setting up the stream spawns a pump task, so it must run inside the
        // tokio runtime context.
        let _guard = rt().enter();
        let lines = self
            .running_mut()?
            .stdout_lines()
            .map_err(|err| map_err(py, err))?;
        Ok(PyStdoutLines {
            inner: Arc::new(Mutex::new(lines)),
        })
    }

    /// An async iterator over stdout and stderr as interleaved `OutputEvent`s.
    fn output_events(&mut self, py: Python<'_>) -> PyResult<PyOutputEvents> {
        let _guard = rt().enter();
        let events = self
            .running_mut()?
            .output_events()
            .map_err(|err| map_err(py, err))?;
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
    fn start_kill(&mut self, py: Python<'_>) -> PyResult<()> {
        let _guard = rt().enter();
        self.running_mut()?
            .start_kill()
            .map_err(|err| map_err(py, err))
    }

    /// Await exit and return the `Outcome`. Consumes the handle.
    fn wait<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let running = self.take_running()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match running.wait().await {
                Ok(outcome) => Ok(PyOutcome { inner: outcome }),
                Err(err) => Err(Python::attach(|py| map_err(py, err))),
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
                Err(err) => Err(Python::attach(|py| map_err(py, err))),
            }
        })
    }

    /// Await exit and capture the full `ProcessResult`. Consumes the handle.
    fn output<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let running = self.take_running()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match running.output_string().await {
                Ok(inner) => Ok(PyProcessResult { inner }),
                Err(err) => Err(Python::attach(|py| map_err(py, err))),
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
        if !grace_seconds.is_finite() || grace_seconds < 0.0 {
            return Err(PyValueError::new_err(
                "grace_seconds must be a non-negative, finite number",
            ));
        }
        let grace = Duration::try_from_secs_f64(grace_seconds)
            .map_err(|err| PyValueError::new_err(format!("invalid grace_seconds: {err}")))?;
        let running = self.take_running()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match running.shutdown(grace).await {
                Ok(outcome) => Ok(PyOutcome { inner: outcome }),
                Err(err) => Err(Python::attach(|py| map_err(py, err))),
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

/// A snapshot of a `ProcessGroup`'s resource usage.
#[pyclass(name = "ProcessGroupStats", frozen, module = "processkit")]
struct PyProcessGroupStats {
    active_process_count: usize,
    peak_memory_bytes: Option<u64>,
    total_cpu_time: Option<Duration>,
}

#[pymethods]
impl PyProcessGroupStats {
    /// Number of live processes currently in the group.
    #[getter]
    fn active_process_count(&self) -> usize {
        self.active_process_count
    }

    /// Peak resident memory across the tree in bytes, if measurable.
    #[getter]
    fn peak_memory_bytes(&self) -> Option<u64> {
        self.peak_memory_bytes
    }

    /// Total CPU time consumed by the tree in seconds, if measurable.
    #[getter]
    fn total_cpu_time_seconds(&self) -> Option<f64> {
        self.total_cpu_time.map(|d| d.as_secs_f64())
    }

    fn __repr__(&self) -> String {
        format!(
            "ProcessGroupStats(active_process_count={}, peak_memory_bytes={:?}, total_cpu_time_seconds={:?})",
            self.active_process_count,
            self.peak_memory_bytes,
            self.total_cpu_time.map(|d| d.as_secs_f64()),
        )
    }
}

/// Tear the group down gracefully when we are its sole owner; if an `astart`
/// future is still racing (another `Arc` ref alive), fall back to a hard kill of
/// the whole tree so teardown still happens.
async fn shutdown_group(group: Arc<PkProcessGroup>) -> processkit::Result<()> {
    match Arc::try_unwrap(group) {
        Ok(group) => group.shutdown().await,
        Err(group) => group.terminate_all(),
    }
}

/// A kill-on-drop container for a process *tree*. Use it as a context manager
/// (`with` or `async with`): every process started inside, and everything those
/// processes spawn, is torn down when the block exits.
///
/// The teardown asymmetry is load-bearing and honest: on Windows the Job Object
/// reaps the tree when the last handle closes (kernel-enforced); on Linux/macOS
/// teardown is driven from the `__exit__` path and is best-effort if the
/// interpreter is hard-killed.
#[pyclass(name = "ProcessGroup", module = "processkit")]
struct PyProcessGroup {
    // `None` after the group is shut down — every method then errors cleanly.
    // `Arc` so the async `astart` can hold the group across the await without
    // borrowing the pyclass.
    inner: Option<Arc<PkProcessGroup>>,
}

impl PyProcessGroup {
    fn group(&self) -> PyResult<&Arc<PkProcessGroup>> {
        self.inner
            .as_ref()
            .ok_or_else(|| ProcessError::new_err("ProcessGroup is already closed"))
    }
}

#[pymethods]
impl PyProcessGroup {
    #[new]
    #[pyo3(signature = (
        *,
        memory_max=None,
        max_processes=None,
        cpu_quota=None,
        shutdown_timeout=None,
        escalate_to_kill=None,
    ))]
    fn new(
        py: Python<'_>,
        memory_max: Option<u64>,
        max_processes: Option<u32>,
        cpu_quota: Option<f64>,
        shutdown_timeout: Option<f64>,
        escalate_to_kill: Option<bool>,
    ) -> PyResult<Self> {
        let configured = memory_max.is_some()
            || max_processes.is_some()
            || cpu_quota.is_some()
            || shutdown_timeout.is_some()
            || escalate_to_kill.is_some();
        let group = if configured {
            let mut options = ProcessGroupOptions::default();
            if let Some(bytes) = memory_max {
                options = options.memory_max(bytes);
            }
            if let Some(n) = max_processes {
                options = options.max_processes(n);
            }
            if let Some(cores) = cpu_quota {
                options = options.cpu_quota(cores);
            }
            if let Some(seconds) = shutdown_timeout {
                if !seconds.is_finite() || seconds < 0.0 {
                    return Err(PyValueError::new_err(
                        "shutdown_timeout must be a non-negative, finite number of seconds",
                    ));
                }
                let duration = Duration::try_from_secs_f64(seconds).map_err(|err| {
                    PyValueError::new_err(format!("invalid shutdown_timeout: {err}"))
                })?;
                options = options.shutdown_timeout(duration);
            }
            if let Some(escalate) = escalate_to_kill {
                options = options.escalate_to_kill(escalate);
            }
            PkProcessGroup::with_options(options).map_err(|err| map_err(py, err))?
        } else {
            PkProcessGroup::new().map_err(|err| map_err(py, err))?
        };
        Ok(Self {
            inner: Some(Arc::new(group)),
        })
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

    fn __aenter__<'py>(slf: Py<Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        pyo3_async_runtimes::tokio::future_into_py(py, async move { Ok(slf) })
    }

    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __aexit__<'py>(
        &mut self,
        py: Python<'py>,
        _exc_type: Option<Bound<'py, PyAny>>,
        _exc_value: Option<Bound<'py, PyAny>>,
        _traceback: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let group = self.inner.take();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            if let Some(group) = group {
                shutdown_group(group)
                    .await
                    .map_err(|err| Python::attach(|py| map_err(py, err)))?;
            }
            Ok(false)
        })
    }

    /// Start a command inside the group and return a handle (sync). The process
    /// runs concurrently; this does not wait for it to finish.
    fn start(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyRunningProcess> {
        let group = self.group()?.clone();
        let running = block_on_interruptible(py, group.start(&command.inner))?
            .map_err(|err| map_err(py, err))?;
        Ok(PyRunningProcess {
            inner: Some(running),
        })
    }

    /// Async counterpart of `start()`.
    fn astart<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        let group = self.group()?.clone();
        let cmd = command.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match group.start(&cmd).await {
                Ok(running) => Ok(PyRunningProcess {
                    inner: Some(running),
                }),
                Err(err) => Err(Python::attach(|py| map_err(py, err))),
            }
        })
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

    /// Send a signal to every process in the tree. `name` is one of `term`,
    /// `kill`, `int`, `hup`, `quit`, `usr1`, `usr2` (Windows emulates the
    /// terminate/kill semantics).
    fn signal(&self, py: Python<'_>, name: &str) -> PyResult<()> {
        let signal = parse_signal(name)?;
        self.group()?.signal(signal).map_err(|err| map_err(py, err))
    }

    /// Suspend every process in the tree.
    fn suspend(&self, py: Python<'_>) -> PyResult<()> {
        self.group()?.suspend().map_err(|err| map_err(py, err))
    }

    /// Resume every previously-suspended process in the tree.
    fn resume(&self, py: Python<'_>) -> PyResult<()> {
        self.group()?.resume().map_err(|err| map_err(py, err))
    }

    /// Immediately kill the whole tree (a hard kill, no graceful window).
    fn terminate_all(&self, py: Python<'_>) -> PyResult<()> {
        self.group()?
            .terminate_all()
            .map_err(|err| map_err(py, err))
    }

    /// A snapshot of the group's resource usage.
    fn stats(&self, py: Python<'_>) -> PyResult<PyProcessGroupStats> {
        let stats = self.group()?.stats().map_err(|err| map_err(py, err))?;
        Ok(PyProcessGroupStats {
            active_process_count: stats.active_process_count,
            peak_memory_bytes: stats.peak_memory_bytes,
            total_cpu_time: stats.total_cpu_time,
        })
    }

    /// Tear down the whole tree gracefully (sync). Idempotent — a second call is
    /// a no-op.
    fn shutdown(&mut self, py: Python<'_>) -> PyResult<()> {
        if let Some(group) = self.inner.take() {
            block_on_interruptible(py, shutdown_group(group))?.map_err(|err| map_err(py, err))?;
        }
        Ok(())
    }

    /// Async counterpart of `shutdown()`. Idempotent.
    fn ashutdown<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let group = self.inner.take();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            if let Some(group) = group {
                shutdown_group(group)
                    .await
                    .map_err(|err| Python::attach(|py| map_err(py, err)))?;
            }
            Ok(())
        })
    }

    fn __repr__(&self) -> String {
        match &self.inner {
            Some(_) => "ProcessGroup(open)".to_string(),
            None => "ProcessGroup(closed)".to_string(),
        }
    }
}

/// Wrap a Python predicate `(ProcessResult) -> bool` as a `Supervisor.stop_when`
/// callback. Errors / non-bool returns are treated as "do not stop".
fn make_stop_predicate(
    callback: Py<PyAny>,
) -> impl Fn(&PkProcessResult<String>) -> bool + Send + Sync + 'static {
    move |result| {
        Python::attach(|py| {
            match Py::new(
                py,
                PyProcessResult {
                    inner: result.clone(),
                },
            ) {
                Ok(py_result) => callback
                    .call1(py, (py_result,))
                    .and_then(|value| value.extract::<bool>(py))
                    .unwrap_or(false),
                Err(_) => false,
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
struct PySupervisionOutcome {
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
struct PySupervisor {
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
        if let Some(initial) = backoff_initial {
            let initial = positive_duration(initial, "backoff_initial")?;
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
        let outcome =
            block_on_interruptible(py, supervisor.run())?.map_err(|err| map_err(py, err))?;
        Ok(convert_supervision_outcome(&outcome))
    }

    /// Async counterpart of `run()`. Consumes the supervisor.
    fn arun<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let supervisor = self.take_supervisor()?;
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match supervisor.run().await {
                Ok(outcome) => Ok(convert_supervision_outcome(&outcome)),
                Err(err) => Err(Python::attach(|py| map_err(py, err))),
            }
        })
    }
}

#[pymodule]
fn _processkit(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCommand>()?;
    m.add_class::<PyProcessResult>()?;
    m.add_class::<PyProcessGroup>()?;
    m.add_class::<PyRunningProcess>()?;
    m.add_class::<PyOutcome>()?;
    m.add_class::<PyFinished>()?;
    m.add_class::<PyOutputEvent>()?;
    m.add_class::<PyProcessStdin>()?;
    m.add_class::<PyStdoutLines>()?;
    m.add_class::<PyOutputEvents>()?;
    m.add_class::<PyProcessGroupStats>()?;
    m.add_class::<PyPipeline>()?;
    m.add_class::<PySupervisor>()?;
    m.add_class::<PySupervisionOutcome>()?;

    let py = m.py();
    m.add("ProcessError", py.get_type::<ProcessError>())?;
    m.add("NonZeroExit", py.get_type::<NonZeroExit>())?;
    m.add("Timeout", py.get_type::<Timeout>())?;
    m.add("Cancelled", py.get_type::<Cancelled>())?;
    m.add("Signalled", py.get_type::<Signalled>())?;
    m.add("ProcessNotFound", py.get_type::<ProcessNotFound>())?;
    m.add("ResourceLimit", py.get_type::<ResourceLimit>())?;
    m.add("Unsupported", py.get_type::<Unsupported>())?;
    Ok(())
}
