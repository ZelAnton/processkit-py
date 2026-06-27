//! The runner seam: a real `Runner`, a `ScriptedRunner` test double, and the
//! `Reply` builder, sharing one generic set of run verbs over `ProcessRunner`.

use std::path::PathBuf;
use std::sync::Arc;

use processkit::testing::{
    Invocation, RecordReplayRunner as PkRecordReplayRunner, RecordingRunner as PkRecordingRunner,
    Reply as PkReply, ScriptedRunner as PkScriptedRunner,
};
use processkit::JobRunner;
use processkit::ProcessRunner;
use processkit::ProcessRunnerExt;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::errors::{map_err, ProcessError};
use crate::runtime::{block_on_interruptible, drive_async};
use crate::{PyBytesResult, PyCommand, PyProcessResult, PyRunningProcess};

// The run verbs are generic over the crate's `ProcessRunner` so the real
// `Runner` and the `ScriptedRunner` share one implementation.

fn runner_output<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<PyProcessResult> {
    block_on_interruptible(py, runner.output_string(&command.inner))?
        .map(PyProcessResult::from)
        .map_err(map_err)
}

fn runner_output_bytes<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<PyBytesResult> {
    block_on_interruptible(py, runner.output_bytes(&command.inner))?
        .map(PyBytesResult::from)
        .map_err(map_err)
}

fn runner_run<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<String> {
    block_on_interruptible(py, runner.run(&command.inner))?.map_err(map_err)
}

fn runner_exit_code<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<i32> {
    block_on_interruptible(py, runner.exit_code(&command.inner))?.map_err(map_err)
}

fn runner_probe<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<bool> {
    block_on_interruptible(py, runner.probe(&command.inner))?.map_err(map_err)
}

fn runner_start<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<PyRunningProcess> {
    // `start()` is async, so `block_on_interruptible` provides the runtime
    // context while it (and its pump spawn) is polled — no `enter()` needed.
    block_on_interruptible(py, runner.start(&command.inner))?
        .map(PyRunningProcess::from)
        .map_err(map_err)
}

// Async run verbs over an owned `Arc<R>` so the future can hold the runner with
// no borrow of the pyclass.

fn runner_aoutput<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    drive_async(py, async move {
        runner.output_string(&cmd).await.map(PyProcessResult::from)
    })
}

fn runner_aoutput_bytes<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    drive_async(py, async move {
        runner.output_bytes(&cmd).await.map(PyBytesResult::from)
    })
}

fn runner_arun<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    drive_async(py, async move { runner.run(&cmd).await })
}

fn runner_aexit_code<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    drive_async(py, async move { runner.exit_code(&cmd).await })
}

fn runner_aprobe<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    drive_async(py, async move { runner.probe(&cmd).await })
}

fn runner_astart<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    drive_async(py, async move {
        runner.start(&cmd).await.map(PyRunningProcess::from)
    })
}

/// The real process runner. Inject it where you'd otherwise call `Command`
/// verbs directly, so the same code can take a `ScriptedRunner` under test.
#[pyclass(name = "Runner", module = "processkit")]
pub(crate) struct PyRunner {
    inner: Arc<JobRunner>,
}

#[pymethods]
impl PyRunner {
    #[new]
    fn new() -> Self {
        Self {
            inner: Arc::new(JobRunner::new()),
        }
    }

    /// Run a command and capture output (a non-zero exit is data).
    fn output(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyProcessResult> {
        runner_output(py, &*self.inner, command)
    }

    /// Run a command and capture raw-bytes stdout.
    fn output_bytes(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyBytesResult> {
        runner_output_bytes(py, &*self.inner, command)
    }

    /// Require a zero exit and return trimmed stdout.
    fn run(&self, py: Python<'_>, command: &PyCommand) -> PyResult<String> {
        runner_run(py, &*self.inner, command)
    }

    /// The command's exit code.
    fn exit_code(&self, py: Python<'_>, command: &PyCommand) -> PyResult<i32> {
        runner_exit_code(py, &*self.inner, command)
    }

    /// Read a predicate command's exit code as a bool.
    fn probe(&self, py: Python<'_>, command: &PyCommand) -> PyResult<bool> {
        runner_probe(py, &*self.inner, command)
    }

    /// Start a command and return a `RunningProcess`.
    fn start(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyRunningProcess> {
        runner_start(py, &*self.inner, command)
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aoutput(py, self.inner.clone(), command)
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(
        &self,
        py: Python<'py>,
        command: &PyCommand,
    ) -> PyResult<Bound<'py, PyAny>> {
        runner_aoutput_bytes(py, self.inner.clone(), command)
    }

    /// Async counterpart of `run()`.
    fn arun<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_arun(py, self.inner.clone(), command)
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aexit_code(py, self.inner.clone(), command)
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aprobe(py, self.inner.clone(), command)
    }

    /// Async counterpart of `start()`.
    fn astart<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_astart(py, self.inner.clone(), command)
    }

    fn __repr__(&self) -> String {
        "Runner()".to_string()
    }
}

/// A scripted test double for a `Runner`: configure canned replies for argv
/// prefixes, then run commands through it without spawning real processes. The
/// results it returns are genuine `ProcessResult` / `RunningProcess` objects.
#[pyclass(name = "ScriptedRunner", module = "processkit")]
pub(crate) struct PyScriptedRunner {
    // `Arc` so the async run verbs can hold the runner across the await; builders
    // reconfigure it via `Arc::try_unwrap`, which requires no in-flight call.
    inner: Arc<PkScriptedRunner>,
}

impl PyScriptedRunner {
    /// Apply a consuming builder to the wrapped runner. Requires sole ownership
    /// (no async call holding a clone).
    fn reconfigure(
        &mut self,
        build: impl FnOnce(PkScriptedRunner) -> PkScriptedRunner,
    ) -> PyResult<()> {
        let placeholder = Arc::new(PkScriptedRunner::new());
        match Arc::try_unwrap(std::mem::replace(&mut self.inner, placeholder)) {
            Ok(runner) => {
                self.inner = Arc::new(build(runner));
                Ok(())
            }
            Err(original) => {
                self.inner = original;
                Err(ProcessError::new_err(
                    "cannot reconfigure a ScriptedRunner while a call is in flight",
                ))
            }
        }
    }
}

#[pymethods]
impl PyScriptedRunner {
    #[new]
    fn new() -> Self {
        Self {
            inner: Arc::new(PkScriptedRunner::new()),
        }
    }

    /// Reply with `reply` when a command's argv starts with `prefix`.
    fn on(&mut self, prefix: Vec<String>, reply: &PyReply) -> PyResult<()> {
        let reply = reply.inner.clone();
        self.reconfigure(move |runner| runner.on(prefix, reply))
    }

    /// The reply for any command not matched by an `on(...)` rule.
    fn fallback(&mut self, reply: &PyReply) -> PyResult<()> {
        let reply = reply.inner.clone();
        self.reconfigure(move |runner| runner.fallback(reply))
    }

    fn output(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyProcessResult> {
        runner_output(py, &*self.inner, command)
    }

    fn output_bytes(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyBytesResult> {
        runner_output_bytes(py, &*self.inner, command)
    }

    fn run(&self, py: Python<'_>, command: &PyCommand) -> PyResult<String> {
        runner_run(py, &*self.inner, command)
    }

    fn exit_code(&self, py: Python<'_>, command: &PyCommand) -> PyResult<i32> {
        runner_exit_code(py, &*self.inner, command)
    }

    fn probe(&self, py: Python<'_>, command: &PyCommand) -> PyResult<bool> {
        runner_probe(py, &*self.inner, command)
    }

    fn start(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyRunningProcess> {
        runner_start(py, &*self.inner, command)
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aoutput(py, self.inner.clone(), command)
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(
        &self,
        py: Python<'py>,
        command: &PyCommand,
    ) -> PyResult<Bound<'py, PyAny>> {
        runner_aoutput_bytes(py, self.inner.clone(), command)
    }

    /// Async counterpart of `run()`.
    fn arun<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_arun(py, self.inner.clone(), command)
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aexit_code(py, self.inner.clone(), command)
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aprobe(py, self.inner.clone(), command)
    }

    /// Async counterpart of `start()`.
    fn astart<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_astart(py, self.inner.clone(), command)
    }

    fn __repr__(&self) -> String {
        "ScriptedRunner()".to_string()
    }
}

/// A canned reply for a `ScriptedRunner` rule.
#[pyclass(name = "Reply", module = "processkit")]
pub(crate) struct PyReply {
    inner: PkReply,
}

#[pymethods]
impl PyReply {
    /// A successful run with the given stdout (exit code 0).
    #[staticmethod]
    fn ok(stdout: String) -> Self {
        Self {
            inner: PkReply::ok(stdout),
        }
    }

    /// A failed run with the given exit code and stderr.
    #[staticmethod]
    fn fail(code: i32, stderr: String) -> Self {
        Self {
            inner: PkReply::fail(code, stderr),
        }
    }

    /// A run that times out.
    #[staticmethod]
    fn timeout() -> Self {
        Self {
            inner: PkReply::timeout(),
        }
    }

    /// A run killed by a signal (`signal=None` for an unknown signal).
    #[staticmethod]
    #[pyo3(signature = (signal=None))]
    fn signalled(signal: Option<i32>) -> Self {
        Self {
            inner: PkReply::signalled(signal),
        }
    }

    /// A run that never exits on its own (cancel / timeout still ends it).
    #[staticmethod]
    fn pending() -> Self {
        Self {
            inner: PkReply::pending(),
        }
    }

    /// A successful run emitting the given stdout lines.
    #[staticmethod]
    fn lines(lines: Vec<String>) -> Self {
        Self {
            inner: PkReply::lines(lines),
        }
    }

    /// Attach stdout to this reply (e.g. to a failure).
    fn with_stdout(&self, stdout: String) -> Self {
        Self {
            inner: self.inner.clone().with_stdout(stdout),
        }
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.inner)
    }
}

/// A runner that records real runs to a cassette file (`record`) and replays
/// them deterministically without spawning (`replay`) — for tests that exercise
/// real tools once, then run offline against the captured transcript.
#[pyclass(name = "RecordReplayRunner", module = "processkit")]
pub(crate) struct PyRecordReplayRunner {
    inner: Arc<PkRecordReplayRunner<JobRunner>>,
}

#[pymethods]
impl PyRecordReplayRunner {
    /// Record real runs (via the real runner) to a cassette at `path`; call
    /// `save()` to write it to disk.
    #[staticmethod]
    fn record(path: PathBuf) -> Self {
        Self {
            inner: Arc::new(PkRecordReplayRunner::record(path, JobRunner::new())),
        }
    }

    /// Replay runs from the cassette at `path` (no real processes spawned).
    #[staticmethod]
    fn replay(path: PathBuf) -> PyResult<Self> {
        PkRecordReplayRunner::replay(path)
            .map(|inner| Self {
                inner: Arc::new(inner),
            })
            .map_err(map_err)
    }

    /// Write the recorded cassette to its file.
    fn save(&self) -> PyResult<()> {
        self.inner.save().map_err(map_err)
    }

    fn output(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyProcessResult> {
        runner_output(py, &*self.inner, command)
    }

    fn output_bytes(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyBytesResult> {
        runner_output_bytes(py, &*self.inner, command)
    }

    fn run(&self, py: Python<'_>, command: &PyCommand) -> PyResult<String> {
        runner_run(py, &*self.inner, command)
    }

    fn exit_code(&self, py: Python<'_>, command: &PyCommand) -> PyResult<i32> {
        runner_exit_code(py, &*self.inner, command)
    }

    fn probe(&self, py: Python<'_>, command: &PyCommand) -> PyResult<bool> {
        runner_probe(py, &*self.inner, command)
    }

    fn start(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyRunningProcess> {
        runner_start(py, &*self.inner, command)
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aoutput(py, self.inner.clone(), command)
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(
        &self,
        py: Python<'py>,
        command: &PyCommand,
    ) -> PyResult<Bound<'py, PyAny>> {
        runner_aoutput_bytes(py, self.inner.clone(), command)
    }

    /// Async counterpart of `run()`.
    fn arun<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_arun(py, self.inner.clone(), command)
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aexit_code(py, self.inner.clone(), command)
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aprobe(py, self.inner.clone(), command)
    }

    /// Async counterpart of `start()`.
    fn astart<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_astart(py, self.inner.clone(), command)
    }

    fn __repr__(&self) -> String {
        "RecordReplayRunner()".to_string()
    }
}

/// One call captured by a `RecordingRunner`: the program, args, working
/// directory, environment overrides, and whether stdin was supplied. The values
/// are inspectable (this is your own test data) for assertions; the `repr` stays
/// redacted (program, arg count, cwd, env names, has_stdin — never argv or env
/// values) like `Command`'s.
#[pyclass(name = "Invocation", module = "processkit")]
pub(crate) struct PyInvocation {
    inner: Invocation,
}

impl From<Invocation> for PyInvocation {
    fn from(inner: Invocation) -> Self {
        Self { inner }
    }
}

#[pymethods]
impl PyInvocation {
    /// The program that was run.
    #[getter]
    fn program(&self) -> String {
        self.inner.program.to_string_lossy().into_owned()
    }

    /// The arguments, in order.
    #[getter]
    fn args(&self) -> Vec<String> {
        self.inner.args_str()
    }

    /// The working directory, if one was set.
    #[getter]
    fn cwd(&self) -> Option<String> {
        self.inner
            .cwd
            .as_ref()
            .map(|p| p.to_string_lossy().into_owned())
    }

    /// The environment overrides as a dict; a `None` value is a removal
    /// (`env_remove`). Later settings of the same key win (the effective value).
    #[getter]
    fn env<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (key, value) in &self.inner.envs {
            let key = key.to_string_lossy().into_owned();
            let value = value.as_ref().map(|v| v.to_string_lossy().into_owned());
            dict.set_item(key, value)?;
        }
        Ok(dict)
    }

    /// Whether a (non-empty) stdin source was supplied.
    #[getter]
    fn has_stdin(&self) -> bool {
        self.inner.has_stdin
    }

    /// Whether `flag` appears among the arguments.
    fn has_flag(&self, flag: &str) -> bool {
        self.inner.has_flag(flag)
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.inner)
    }
}

/// A recording test double: replies to every command with a canned `Reply` and
/// records each call, so a test can assert on *what* its code ran. Inspect the
/// captured calls with `calls()` / `only_call()` (each an `Invocation`).
#[pyclass(name = "RecordingRunner", module = "processkit")]
pub(crate) struct PyRecordingRunner {
    inner: Arc<PkRecordingRunner<PkScriptedRunner>>,
}

#[pymethods]
impl PyRecordingRunner {
    /// A recorder whose inner runner replies with `reply` to everything.
    #[staticmethod]
    fn replying(reply: &PyReply) -> Self {
        Self {
            inner: Arc::new(PkRecordingRunner::replying(reply.inner.clone())),
        }
    }

    fn output(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyProcessResult> {
        runner_output(py, &*self.inner, command)
    }

    fn output_bytes(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyBytesResult> {
        runner_output_bytes(py, &*self.inner, command)
    }

    fn run(&self, py: Python<'_>, command: &PyCommand) -> PyResult<String> {
        runner_run(py, &*self.inner, command)
    }

    fn exit_code(&self, py: Python<'_>, command: &PyCommand) -> PyResult<i32> {
        runner_exit_code(py, &*self.inner, command)
    }

    fn probe(&self, py: Python<'_>, command: &PyCommand) -> PyResult<bool> {
        runner_probe(py, &*self.inner, command)
    }

    fn start(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyRunningProcess> {
        runner_start(py, &*self.inner, command)
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aoutput(py, self.inner.clone(), command)
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(
        &self,
        py: Python<'py>,
        command: &PyCommand,
    ) -> PyResult<Bound<'py, PyAny>> {
        runner_aoutput_bytes(py, self.inner.clone(), command)
    }

    /// Async counterpart of `run()`.
    fn arun<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_arun(py, self.inner.clone(), command)
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aexit_code(py, self.inner.clone(), command)
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aprobe(py, self.inner.clone(), command)
    }

    /// Async counterpart of `start()`.
    fn astart<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_astart(py, self.inner.clone(), command)
    }

    /// A snapshot of every recorded invocation, in call order.
    fn calls(&self) -> Vec<PyInvocation> {
        self.inner
            .calls()
            .into_iter()
            .map(PyInvocation::from)
            .collect()
    }

    /// The single recorded invocation; raises `ProcessError` unless exactly one
    /// call was made.
    fn only_call(&self) -> PyResult<PyInvocation> {
        let calls = self.inner.calls();
        match calls.len() {
            1 => Ok(PyInvocation::from(
                calls.into_iter().next().expect("length checked above"),
            )),
            n => Err(ProcessError::new_err(format!(
                "expected exactly one call, got {n}"
            ))),
        }
    }

    fn __repr__(&self) -> String {
        format!("RecordingRunner(calls={})", self.inner.calls().len())
    }
}
