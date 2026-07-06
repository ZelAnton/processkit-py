//! The runner seam: a real `Runner`, the `ScriptedRunner` / `RecordReplayRunner`
//! / `RecordingRunner` / `DryRunRunner` test doubles, and the `Reply` builder,
//! sharing one generic set of run verbs over `ProcessRunner`.

use std::path::PathBuf;
use std::sync::Arc;

use processkit::testing::{
    DryRunRunner as PkDryRunRunner, Invocation, RecordReplayRunner as PkRecordReplayRunner,
    RecordingRunner as PkRecordingRunner, Reply as PkReply, ScriptedRunner as PkScriptedRunner,
};
use processkit::JobRunner;
use processkit::ProcessRunner;
use processkit::ProcessRunnerExt;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::command::PyCommand;
use crate::convert::nonnegative_duration;
use crate::errors::{map_err, ProcessError};
use crate::result::{PyBytesResult, PyProcessResult};
use crate::running::PyRunningProcess;
use crate::runtime::{block_on, drive_async};

// The run verbs are generic over the crate's `ProcessRunner` so the real
// `Runner` and the `ScriptedRunner` share one implementation.

pub(crate) fn runner_output<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<PyProcessResult> {
    block_on(py, runner.output_string(&command.inner)).map(PyProcessResult::from)
}

pub(crate) fn runner_output_bytes<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<PyBytesResult> {
    block_on(py, runner.output_bytes(&command.inner)).map(PyBytesResult::from)
}

pub(crate) fn runner_run<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<String> {
    block_on(py, runner.run(&command.inner))
}

pub(crate) fn runner_exit_code<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<i32> {
    block_on(py, runner.exit_code(&command.inner))
}

pub(crate) fn runner_probe<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<bool> {
    block_on(py, runner.probe(&command.inner))
}

fn runner_start<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<PyRunningProcess> {
    // `start()` is async, so `block_on` provides the runtime context while it
    // (and its pump spawn) is polled — no `enter()` needed.
    block_on(py, runner.start(&command.inner)).map(PyRunningProcess::from)
}

// Async run verbs over an owned `Arc<R>` so the future can hold the runner with
// no borrow of the pyclass.

pub(crate) fn runner_aoutput<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    drive_async(py, async move {
        runner.output_string(&cmd).await.map(PyProcessResult::from)
    })
}

pub(crate) fn runner_aoutput_bytes<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    drive_async(py, async move {
        runner.output_bytes(&cmd).await.map(PyBytesResult::from)
    })
}

pub(crate) fn runner_arun<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    drive_async(py, async move { runner.run(&cmd).await })
}

pub(crate) fn runner_aexit_code<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    drive_async(py, async move { runner.exit_code(&cmd).await })
}

pub(crate) fn runner_aprobe<'py, R: ProcessRunner + Send + Sync + 'static>(
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

/// Wrap a Python predicate `(Command) -> bool` as a `ScriptedRunner.when`
/// rule. Mirrors `supervisor::make_stop_predicate`'s infallible-bridge
/// convention: a raising or non-`bool` predicate reads as "does not match"
/// rather than panicking across the FFI boundary, with the error surfaced via
/// the unraisable hook (visible on stderr) instead of silently swallowed.
fn make_command_predicate(
    callback: Py<PyAny>,
) -> impl Fn(&processkit::Command) -> bool + Send + Sync + 'static {
    move |command| {
        Python::attach(|py| {
            let py_command = match Py::new(
                py,
                PyCommand {
                    inner: command.clone(),
                },
            ) {
                Ok(py_command) => py_command,
                Err(err) => {
                    err.write_unraisable(py, None);
                    return false;
                }
            };
            match callback
                .call1(py, (py_command,))
                .and_then(|value| value.extract::<bool>(py))
            {
                Ok(matches) => matches,
                Err(err) => {
                    err.write_unraisable(py, Some(callback.bind(py)));
                    false
                }
            }
        })
    }
}

/// Wrap a Python callable `(str) -> None` as a `DryRunRunner.on_invocation`
/// reaction. Mirrors `make_command_predicate`'s infallible-bridge convention: a
/// dry-run echo is a fire-and-forget side effect, so a raising callback is
/// surfaced via the unraisable hook (visible on stderr) rather than propagated
/// — a broken echo must not derail the run it was only observing.
fn make_invocation_callback(callback: Py<PyAny>) -> impl Fn(&str) + Send + Sync + 'static {
    move |line| {
        Python::attach(|py| {
            if let Err(err) = callback.call1(py, (line,)) {
                err.write_unraisable(py, Some(callback.bind(py)));
            }
        })
    }
}

/// Downcast a Python `runner=` argument to a type-erased, shareable
/// `ProcessRunner` — the single extraction point `output_all`/`aoutput_all`/
/// `output_all_bytes`/`aoutput_all_bytes` (`batch.rs`), `Supervisor.__new__`
/// (`supervisor.rs`), and `CliClient.__new__` (`cli.rs`) use to accept an
/// injected runner instead of hardcoding the real `JobRunner`. Accepts any of
/// the five runner pyclasses (`Runner`, `ScriptedRunner`, `RecordingRunner`,
/// `RecordReplayRunner`, `DryRunRunner`); each already wraps its concrete
/// runner in an `Arc`, so `.clone()` unsize-coerces to the trait object at this
/// function's declared return type — no extra allocation beyond the `Arc` bump.
///
/// The crate's `ProcessGroup` also implements `ProcessRunner` (`group.rs`
/// binds its verb surface directly, over the same generic `runner_*`
/// helpers this module exposes), but it is deliberately NOT an
/// `extract_runner` target: a `ProcessGroup` is a containment container a
/// caller already holds and injects directly, not a `runner=` kwarg value —
/// and unlike the five dedicated doubles/real-runner pyclasses, it carries
/// real OS resources (a Job Object / cgroup) that a generic "one of these
/// five" injection point shouldn't paper over.
pub(crate) fn extract_runner(
    obj: &Bound<'_, PyAny>,
) -> PyResult<Arc<dyn ProcessRunner + Send + Sync>> {
    if let Ok(r) = obj.cast::<PyRunner>() {
        return Ok(r.borrow().inner.clone());
    }
    if let Ok(r) = obj.cast::<PyScriptedRunner>() {
        return Ok(r.borrow().inner.clone());
    }
    if let Ok(r) = obj.cast::<PyRecordingRunner>() {
        return Ok(r.borrow().inner.clone());
    }
    if let Ok(r) = obj.cast::<PyRecordReplayRunner>() {
        return Ok(r.borrow().inner.clone());
    }
    if let Ok(r) = obj.cast::<PyDryRunRunner>() {
        return Ok(r.borrow().inner.clone());
    }
    Err(pyo3::exceptions::PyTypeError::new_err(
        "runner must be one of Runner, ScriptedRunner, RecordingRunner, RecordReplayRunner, \
         DryRunRunner",
    ))
}

/// Emit a runner pyclass's `#[pymethods]` block: the six sync + six async run-verb
/// forwarders (every runner delegates these to the generic `runner_*` helpers
/// over its `self.inner`), spliced together with the type's own methods. PyO3's
/// `multiple-pymethods` is off, so a pyclass may have only ONE `#[pymethods]`
/// impl — `$unique` captures the constructor / builders / `__repr__` as a token
/// tree (attributes like `#[new]` / `#[staticmethod]` included) and is emitted in
/// the same block as the shared verbs. This is the single source of truth for the
/// run-verb surface across all four runners.
macro_rules! runner_pymethods {
    ($ty:ty { $($unique:tt)* }) => {
        #[pymethods]
        impl $ty {
            $($unique)*

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
            fn aoutput<'py>(
                &self,
                py: Python<'py>,
                command: &PyCommand,
            ) -> PyResult<Bound<'py, PyAny>> {
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
            fn arun<'py>(
                &self,
                py: Python<'py>,
                command: &PyCommand,
            ) -> PyResult<Bound<'py, PyAny>> {
                runner_arun(py, self.inner.clone(), command)
            }

            /// Async counterpart of `exit_code()`.
            fn aexit_code<'py>(
                &self,
                py: Python<'py>,
                command: &PyCommand,
            ) -> PyResult<Bound<'py, PyAny>> {
                runner_aexit_code(py, self.inner.clone(), command)
            }

            /// Async counterpart of `probe()`.
            fn aprobe<'py>(
                &self,
                py: Python<'py>,
                command: &PyCommand,
            ) -> PyResult<Bound<'py, PyAny>> {
                runner_aprobe(py, self.inner.clone(), command)
            }

            /// Async counterpart of `start()`.
            fn astart<'py>(
                &self,
                py: Python<'py>,
                command: &PyCommand,
            ) -> PyResult<Bound<'py, PyAny>> {
                runner_astart(py, self.inner.clone(), command)
            }
        }
    };
}

/// The real process runner. Inject it where you'd otherwise call `Command`
/// verbs directly, so the same code can take a `ScriptedRunner` under test.
#[pyclass(name = "Runner", module = "processkit")]
pub(crate) struct PyRunner {
    inner: Arc<JobRunner>,
}

runner_pymethods!(PyRunner {
    #[new]
    fn new() -> Self {
        Self {
            inner: Arc::new(JobRunner::new()),
        }
    }

    fn __repr__(&self) -> String {
        "Runner()".to_string()
    }
});

/// A scripted test double for a `Runner`: configure canned replies for argv
/// prefixes, then run commands through it without spawning real processes. The
/// results it returns are genuine `ProcessResult` / `RunningProcess` objects.
#[pyclass(name = "ScriptedRunner", module = "processkit.testing")]
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

runner_pymethods!(PyScriptedRunner {
    #[new]
    fn new() -> Self {
        Self {
            inner: Arc::new(PkScriptedRunner::new()),
        }
    }

    /// Reply with `reply` when a command's argv starts with `prefix`. `prefix`
    /// elements accept a `str` or any `os.PathLike[str]` — unified with
    /// `Command`'s own `arg`/`args` typing, since a prefix matches against a
    /// `Command`'s actual argv (which can itself contain path elements).
    fn on(&mut self, prefix: Vec<PathBuf>, reply: &PyReply) -> PyResult<()> {
        let reply = reply.inner.clone();
        self.reconfigure(move |runner| runner.on(prefix, reply))
    }

    /// The reply for any command not matched by an `on(...)` rule.
    fn fallback(&mut self, reply: &PyReply) -> PyResult<()> {
        let reply = reply.inner.clone();
        self.reconfigure(move |runner| runner.fallback(reply))
    }

    /// Reply with `reply` when `predicate(command)` accepts it — for a match
    /// that isn't a plain argv prefix (`on()`), e.g. inspecting `cwd`/`env`/
    /// flags via `Command`'s own inspection accessors. `predicate` is
    /// infallible from the crate's perspective: a raising or non-`bool`
    /// predicate is treated as "does not match" (like
    /// `Supervisor.stop_when`), with the error surfaced via the unraisable
    /// hook rather than silently swallowed.
    fn when(&mut self, predicate: Py<PyAny>, reply: &PyReply) -> PyResult<()> {
        let reply = reply.inner.clone();
        self.reconfigure(move |runner| runner.when(make_command_predicate(predicate), reply))
    }

    /// Reply with each of `replies` in turn on successive matching calls (the
    /// first match gets the first reply, the second the second, …); once
    /// exhausted, the last reply repeats forever. The declarative form for
    /// retry scenarios (fail once, then succeed). Matches like `on()` (program
    /// + argument prefix).
    fn on_sequence(
        &mut self,
        py: Python<'_>,
        prefix: Vec<PathBuf>,
        replies: Vec<Py<PyReply>>,
    ) -> PyResult<()> {
        // The crate's `on_sequence` panics on an empty `replies` — a Python-
        // reachable call must never trigger a Rust panic across the FFI
        // boundary, so reject it here first.
        if replies.is_empty() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "on_sequence needs at least one reply",
            ));
        }
        let replies: Vec<PkReply> = replies.iter().map(|r| r.borrow(py).inner.clone()).collect();
        self.reconfigure(move |runner| runner.on_sequence(prefix, replies))
    }

    fn __repr__(&self) -> String {
        "ScriptedRunner()".to_string()
    }
});

/// A canned reply for a `ScriptedRunner` rule.
#[pyclass(name = "Reply", module = "processkit.testing")]
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

    /// Attach stderr to this reply — including a successful (`ok`) reply, so
    /// a scripted success can still carry stderr output without resorting to
    /// `fail(0, ...)` as a workaround.
    fn with_stderr(&self, stderr: String) -> Self {
        Self {
            inner: self.inner.clone().with_stderr(stderr),
        }
    }

    /// On a scripted `start`, sleep `seconds` before each stdout line — so a
    /// hermetic streaming test can observe genuinely incremental delivery.
    /// The scripted run "exits" after the last line. Ignored by the bulk
    /// `output`/`run` path (only `start`/`astart` stream line by line).
    fn with_line_delay(&self, seconds: f64) -> PyResult<Self> {
        let delay = nonnegative_duration(seconds, "seconds")?;
        Ok(Self {
            inner: self.inner.clone().with_line_delay(delay),
        })
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.inner)
    }
}

/// A runner that records real runs to a cassette file (`record`) and replays
/// them deterministically without spawning (`replay`) — for tests that exercise
/// real tools once, then run offline against the captured transcript.
///
/// Reviewed for processkit 2.1.0 (T-024): the crate's cassette now records a
/// *failed* call too (e.g. a missing program), not just a successful one, and
/// replays it as the same `Error` variant (`cassette.rs`'s `CassetteError` +
/// `to_error`) rather than a misleading `Error::CassetteMiss`. This binding
/// needed **no** change: `record`/`replay`/`save` below, and every verb
/// (`output`/`run`/... via `runner_pymethods!`), already funnel every
/// `Result<_, processkit::Error>` through `map_err`/`map_err_ref`
/// (`errors.rs`), which is variant-generic and accessor-driven — it maps
/// whatever `Error` variant it's handed (a replayed `NotFound` included) to
/// the matching typed Python exception with the same structured fields
/// (`.program`, ...), with no built-in assumption that a cassette only ever
/// holds successes. See `tests/test_runner_seam.py`'s
/// `test_cassette_records_and_replays_a_failed_call`.
#[pyclass(name = "RecordReplayRunner", module = "processkit.testing")]
pub(crate) struct PyRecordReplayRunner {
    inner: Arc<PkRecordReplayRunner<JobRunner>>,
}

runner_pymethods!(PyRecordReplayRunner {
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

    fn __repr__(&self) -> String {
        "RecordReplayRunner()".to_string()
    }
});

/// One call captured by a `RecordingRunner`: the program, args, working
/// directory, environment overrides, and whether stdin was supplied. The values
/// are inspectable (this is your own test data) for assertions; the `repr` stays
/// redacted (program, arg count, cwd, env names, has_stdin — never argv or env
/// values) like `Command`'s.
#[pyclass(name = "Invocation", module = "processkit.testing")]
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

    /// The environment overrides as a dict, in call order; a `None` value is a
    /// removal (`env_remove`). This is **not** the platform-correct effective
    /// override: an exact-same-key duplicate collapses to its last value (plain
    /// Python dict semantics), but a Windows-style *differently-cased*
    /// duplicate (`"Path"` and `"PATH"`) survives as two separate entries,
    /// since dict keys compare case-sensitively — dict semantics decide, not
    /// the platform's env-key rules. For the platform-correct check use
    /// `env_is()` / `has_env()` regardless of case.
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

    /// Whether the invocation set `name` to exactly `value` — the platform-
    /// correct answer (case-insensitive on Windows, last write wins), unlike
    /// scanning the raw `env` dict by hand.
    fn env_is(&self, name: &str, value: &str) -> bool {
        self.inner.env_is(name, value)
    }

    /// Whether the invocation set `name` to some value; a removal
    /// (`env_remove`) does not count.
    fn has_env(&self, name: &str) -> bool {
        self.inner.has_env(name)
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
#[pyclass(name = "RecordingRunner", module = "processkit.testing")]
pub(crate) struct PyRecordingRunner {
    // Type-erased (not the crate's own `RecordingRunner<ScriptedRunner>`
    // specialization), so `new()` can wrap ANY of the four runner pyclasses —
    // not just a fresh `ScriptedRunner` the way `replying()` builds one.
    inner: Arc<PkRecordingRunner<Arc<dyn ProcessRunner + Send + Sync>>>,
}

runner_pymethods!(PyRecordingRunner {
    /// A recorder whose inner runner replies with `reply` to everything.
    #[staticmethod]
    fn replying(reply: &PyReply) -> Self {
        let scripted: Arc<dyn ProcessRunner + Send + Sync> =
            Arc::new(PkScriptedRunner::new().fallback(reply.inner.clone()));
        Self {
            inner: Arc::new(PkRecordingRunner::new(scripted)),
        }
    }

    /// Wrap `inner` — any of `Runner`, `ScriptedRunner`, `RecordReplayRunner`,
    /// or another `RecordingRunner` — recording every call made through it.
    /// The general form behind `replying()`, for combining recording with a
    /// double you've already built (e.g. a `RecordReplayRunner` cassette) or
    /// with the real `Runner`.
    #[staticmethod]
    fn new(inner: &Bound<'_, PyAny>) -> PyResult<Self> {
        let inner = extract_runner(inner)?;
        Ok(Self {
            inner: Arc::new(PkRecordingRunner::new(inner)),
        })
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
});

/// A dry-run test double: never spawns a process. Every verb renders the
/// command to its display-quoted line (the crate's own `Command::command_line`
/// quoting — the same text `Command.command_line()` exposes, not a hand-rolled
/// escaper) and returns a synthetic successful result — the seam behind a
/// tool's own `--dry-run`/`--echo` mode. Unlike a `ScriptedRunner` there is
/// nothing to script: a dry run has only a command line to show, so every call
/// unconditionally "succeeds" (empty stdout, an exit code drawn from the
/// command's own `success_codes` so the checking verbs agree). Inspect the
/// rendered lines with `commands()` / `only_command()`, or stream them live as
/// each call happens with `on_invocation()`.
#[pyclass(name = "DryRunRunner", module = "processkit.testing")]
pub(crate) struct PyDryRunRunner {
    // `Arc` so the async run verbs can hold the runner across the await;
    // `on_invocation` reconfigures it via `Arc::try_unwrap`, which requires no
    // in-flight call — mirrors `PyScriptedRunner`.
    inner: Arc<PkDryRunRunner>,
}

impl PyDryRunRunner {
    /// Apply a consuming builder to the wrapped runner. Requires sole ownership
    /// (no async call holding a clone); the rendered-commands log is carried
    /// across, since the builder only sets the callback field.
    fn reconfigure(
        &mut self,
        build: impl FnOnce(PkDryRunRunner) -> PkDryRunRunner,
    ) -> PyResult<()> {
        let placeholder = Arc::new(PkDryRunRunner::new());
        match Arc::try_unwrap(std::mem::replace(&mut self.inner, placeholder)) {
            Ok(runner) => {
                self.inner = Arc::new(build(runner));
                Ok(())
            }
            Err(original) => {
                self.inner = original;
                Err(ProcessError::new_err(
                    "cannot reconfigure a DryRunRunner while a call is in flight",
                ))
            }
        }
    }
}

runner_pymethods!(PyDryRunRunner {
    #[new]
    fn new() -> Self {
        Self {
            inner: Arc::new(PkDryRunRunner::new()),
        }
    }

    /// Call `callback` with each command's rendered line as it is dry-run
    /// "executed" — e.g. printing it for a tool's `--dry-run` echo — **in
    /// addition to**, not instead of, the collected `commands()` snapshot.
    /// `callback` is infallible from the crate's perspective: a raising one is
    /// surfaced via the unraisable hook (like `ScriptedRunner.when`'s
    /// predicate) rather than propagating across the FFI boundary.
    fn on_invocation(&mut self, callback: Py<PyAny>) -> PyResult<()> {
        self.reconfigure(move |runner| runner.on_invocation(make_invocation_callback(callback)))
    }

    /// The rendered command line for every call so far, in order — each
    /// produced by `Command.command_line()`, the same display quoting you'd
    /// reach for by hand.
    fn commands(&self) -> Vec<String> {
        self.inner.commands()
    }

    /// The single rendered command line; raises `ProcessError` unless exactly
    /// one call was made. (Reimplemented over `commands()` rather than the
    /// crate's own `only_command()`, which *panics* on the wrong count — a
    /// Python-reachable call must raise, not abort across the FFI boundary.)
    fn only_command(&self) -> PyResult<String> {
        let commands = self.inner.commands();
        match commands.len() {
            1 => Ok(commands.into_iter().next().expect("length checked above")),
            n => Err(ProcessError::new_err(format!(
                "expected exactly one dry-run call, got {n}"
            ))),
        }
    }

    fn __repr__(&self) -> String {
        format!("DryRunRunner(commands={})", self.inner.commands().len())
    }
});

/// Register this module's pyclasses (`Runner`, `ScriptedRunner`, `Reply`,
/// `RecordReplayRunner`, `RecordingRunner`, `DryRunRunner`, `Invocation`) on
/// `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyRunner>()?;
    m.add_class::<PyScriptedRunner>()?;
    m.add_class::<PyReply>()?;
    m.add_class::<PyRecordReplayRunner>()?;
    m.add_class::<PyRecordingRunner>()?;
    m.add_class::<PyDryRunRunner>()?;
    m.add_class::<PyInvocation>()?;
    Ok(())
}
