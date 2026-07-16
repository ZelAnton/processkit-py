//! The runner seam: a real `Runner`, the `ScriptedRunner` / `RecordReplayRunner`
//! / `RecordingRunner` / `DryRunRunner` test doubles, and the `Reply` builder,
//! sharing one generic set of run verbs over `ProcessRunner`.

use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, PoisonError};

use processkit::testing::{
    DryRunRunner as PkDryRunRunner, Invocation, RecordReplayRunner as PkRecordReplayRunner,
    RecordingRunner as PkRecordingRunner, Reply as PkReply, ScriptedRunner as PkScriptedRunner,
};
use processkit::JobRunner;
use processkit::ProcessResult as PkProcessResult;
use processkit::ProcessRunner;
use processkit::ProcessRunnerExt;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::command::PyCommand;
use crate::convert::nonnegative_duration;
use crate::errors::{map_err, ProcessError};
use crate::result::{PyBytesResult, PyProcessResult};
use crate::running::PyRunningProcess;
use crate::runtime::{block_on, drive_async_py};

// A per-call sink for the error a `ScriptedRunner.when` predicate raised (or the
// `TypeError` a non-`bool` return produced). The crate resolves a reply by
// calling each rule's predicate `(&Command) -> bool` — infallible from its
// perspective — so a raising predicate cannot abort the verb by itself. The
// predicate stashes its error in the innermost active sink and the run verb,
// wrapped in a `when`-capture scope, re-raises it instead of returning the reply
// a fallthrough would have selected.
//
// A tokio task-local (not a slot on the shared predicate closure or the runner)
// gives per-**call** isolation: the sink is scoped around each verb's future, so
// two concurrent verbs against the same shared `ScriptedRunner` — sync on
// separate threads, or async tasks interleaved on the runtime — each read and
// write their own sink and never cross errors, even though they share one
// predicate closure.
//
// Every Python path that drives a `ScriptedRunner` opens this scope, so the
// contract holds uniformly rather than only for the runner's own verbs: the
// runner's 12 verbs ([`with_when_capture_sync`]/[`with_when_capture_async`]), an
// injected runner under a `CliClient` (`cli.rs`) or a `Supervisor`
// (`supervisor.rs`), and each command of a batch (`batch.rs`, via
// [`WhenCaptureRunner`] — one fresh sink *per command*, since the crate's batch
// driver polls every command on ONE task and a single shared scope would cross
// their errors and keep only the first). Outside any scope the predicate falls
// back to the visible-on-stderr unraisable hook — its prior behavior, now
// reached only when no live scope can catch it, e.g. a predicate firing during
// interpreter finalization (`try_attach` yields `None`).
tokio::task_local! {
    static WHEN_PREDICATE_ERROR: Arc<Mutex<Option<PyErr>>>;
}

/// Stash a `when` predicate's error in the active per-call sink (first error
/// wins). Returns `Some(err)` when there is **no** active sink — the predicate
/// ran outside a wrapped run verb — so the caller can fall back to the unraisable
/// hook; returns `None` when the error was handed to a sink (or dropped as a
/// later duplicate within an already-erroring call).
fn stash_when_error(err: PyErr) -> Option<PyErr> {
    let mut carry = Some(err);
    let in_scope = WHEN_PREDICATE_ERROR
        .try_with(|slot| {
            let mut guard = slot.lock().unwrap_or_else(PoisonError::into_inner);
            if guard.is_none() {
                *guard = carry.take();
            }
        })
        .is_ok();
    // In scope: the error is this call's to re-raise (or a duplicate to drop —
    // either way `carry` is dropped here). Out of scope: return it for the
    // unraisable-hook fallback.
    if in_scope {
        None
    } else {
        carry
    }
}

/// A per-call `when`-predicate error sink (see [`WHEN_PREDICATE_ERROR`]): holds
/// the first error a rule predicate raised for one run verb, read back once the
/// verb's future resolves. Shared by every path that drives a `ScriptedRunner`
/// (the runner's own verbs here, plus `cli.rs`/`supervisor.rs`/`batch.rs`), so
/// the abort-on-broken-predicate contract holds uniformly.
pub(crate) type WhenSink = Arc<Mutex<Option<PyErr>>>;

/// A fresh, empty [`WhenSink`].
pub(crate) fn new_when_sink() -> WhenSink {
    Arc::new(Mutex::new(None))
}

/// Take a sink's stashed predicate error, if any, once its scoped future has
/// resolved.
pub(crate) fn take_when_error(sink: &WhenSink) -> Option<PyErr> {
    sink.lock().unwrap_or_else(PoisonError::into_inner).take()
}

/// Run `fut` with `sink` installed as the active `when`-predicate error sink for
/// the duration of the future (same task; a nested scope shadows an outer one so
/// each verb reads its own). The caller reads `sink` with [`take_when_error`]
/// after the future resolves. This is the single point that touches the
/// [`WHEN_PREDICATE_ERROR`] task-local, so every consumer (this module,
/// `cli.rs`, `supervisor.rs`, `batch.rs`) goes through one door.
pub(crate) fn scope_when<F: Future>(sink: WhenSink, fut: F) -> impl Future<Output = F::Output> {
    WHEN_PREDICATE_ERROR.scope(sink, fut)
}

/// Scope `fut` (which already yields a `PyResult`) under a fresh sink and, once
/// it resolves, re-raise a stashed `when`-predicate error in preference to
/// `fut`'s own outcome. The async building block the `CliClient` async verbs use
/// (their future runs `build_command` + the runner call, both of which belong
/// inside the scope). For a future that yields a raw crate error, use
/// [`with_when_capture_async`] instead.
pub(crate) async fn scope_when_capture<T>(
    fut: impl Future<Output = PyResult<T>> + Send,
) -> PyResult<T> {
    let sink = new_when_sink();
    let result = scope_when(sink.clone(), fut).await;
    match take_when_error(&sink) {
        Some(err) => Err(err),
        None => result,
    }
}

/// Run a runner verb future under a fresh per-call `when`-predicate error sink
/// (sync). If a `ScriptedRunner.when` predicate raised while the crate resolved
/// a reply, re-raise that error instead of returning the reply-derived result.
/// `pub(crate)` so the `CliClient` sync verbs (`cli.rs`) and the `Supervisor`
/// sync run (`supervisor.rs`) share the same scope as the runner's own verbs.
pub(crate) fn with_when_capture_sync<U>(
    py: Python<'_>,
    fut: impl Future<Output = Result<U, processkit::Error>> + Send,
) -> PyResult<U>
where
    U: Send,
{
    let sink = new_when_sink();
    let result = block_on(py, scope_when(sink.clone(), fut));
    if let Some(err) = take_when_error(&sink) {
        return Err(err);
    }
    result
}

/// Async counterpart of [`with_when_capture_sync`]: a fresh sink is scoped around
/// the awaited verb, and a `when`-predicate error takes precedence over the
/// reply-derived result (or the mapped crate error).
fn with_when_capture_async<'py, U>(
    py: Python<'py>,
    fut: impl Future<Output = Result<U, processkit::Error>> + Send + 'static,
) -> PyResult<Bound<'py, PyAny>>
where
    U: for<'a> IntoPyObject<'a> + Send + 'static,
{
    drive_async_py(py, async move {
        let sink = new_when_sink();
        let result = scope_when(sink.clone(), fut).await;
        if let Some(err) = take_when_error(&sink) {
            return Err(err);
        }
        result.map_err(map_err)
    })
}

/// A batch-only `ProcessRunner` wrapper that gives each command its own
/// `when`-predicate error sink.
///
/// The [`WHEN_PREDICATE_ERROR`] task-local is per-task, and the crate's batch
/// driver ([`processkit::output_all`]) polls every command's verb future on ONE
/// task — a `poll_fn` with a bounded active list, **not** `tokio::spawn` — so a
/// single scope around the whole batch would share one sink across every command
/// and lose per-command attribution (keeping only the first error). This wrapper
/// instead opens a fresh sink around each command's `output_string`/
/// `output_bytes` future, so a raising `when` predicate surfaces in exactly that
/// command's result slot — the batch analogue of a direct `runner.output(cmd)`
/// aborting.
///
/// Slot correlation: the driver invokes the verb (`output_string`/`output_bytes`)
/// for input command 0, 1, 2, … in strictly increasing order. The slot index is
/// therefore taken at **call time** — the synchronous head of the verb, before
/// the returned future is polled — so it maps 1:1 to the input index no matter
/// how the driver later interleaves or completes the futures. (Taking it inside
/// the future instead would tie it to first-poll order, which the driver's
/// `swap_remove` reorders the instant a scripted verb completes synchronously,
/// misattributing errors to the wrong slot.) `batch.rs` pre-sizes `errors` to
/// the command count and, after the batch, reads slot i to override command i's
/// result with its predicate error when present.
///
/// The `ProcessRunner` trait is `#[async_trait]` (each verb returns a boxed
/// future); this is the same desugaring written by hand, so the `fetch_add` can
/// run in the synchronous head before `Box::pin`. `start` is left to the trait
/// default — the batch driver only ever calls `output_string`/`output_bytes`.
pub(crate) struct WhenCaptureRunner {
    inner: Arc<dyn ProcessRunner + Send + Sync>,
    /// One slot per input command, indexed by call order (== input index).
    errors: Mutex<Vec<Option<PyErr>>>,
    /// The next slot index to hand out, bumped once at the synchronous head of
    /// each verb call.
    next: AtomicUsize,
}

impl WhenCaptureRunner {
    /// Wrap `inner`, pre-sizing the per-command error log to `count` commands.
    pub(crate) fn new(inner: Arc<dyn ProcessRunner + Send + Sync>, count: usize) -> Self {
        Self {
            inner,
            errors: Mutex::new((0..count).map(|_| None).collect()),
            next: AtomicUsize::new(0),
        }
    }

    /// Take the per-command predicate errors after the batch has finished; slot
    /// `i` is input command `i` (see the type doc). Must be called only once the
    /// driving future has resolved, so no verb future is still writing.
    pub(crate) fn take_errors(&self) -> Vec<Option<PyErr>> {
        std::mem::take(&mut self.errors.lock().unwrap_or_else(PoisonError::into_inner))
    }

    /// Record command `idx`'s predicate error (first write wins within a command).
    /// An out-of-range `idx` — impossible for a correctly pre-sized log — is
    /// dropped defensively rather than panicking across the batch's FFI boundary.
    fn record(&self, idx: usize, err: PyErr) {
        let mut errors = self.errors.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some(slot) = errors.get_mut(idx) {
            if slot.is_none() {
                *slot = Some(err);
            }
        }
    }
}

/// The boxed-future type a hand-written `#[async_trait]` verb returns.
type VerbFuture<'a, T> = Pin<Box<dyn Future<Output = processkit::Result<T>> + Send + 'a>>;

impl ProcessRunner for WhenCaptureRunner {
    fn output_string<'life0, 'life1, 'async_trait>(
        &'life0 self,
        command: &'life1 processkit::Command,
    ) -> VerbFuture<'async_trait, PkProcessResult<String>>
    where
        'life0: 'async_trait,
        'life1: 'async_trait,
        Self: 'async_trait,
    {
        // Take the slot index in the synchronous head (see the type doc), then run
        // the inner verb under a fresh per-command `when`-predicate sink.
        let idx = self.next.fetch_add(1, Ordering::Relaxed);
        Box::pin(async move {
            let sink = new_when_sink();
            let result = scope_when(sink.clone(), self.inner.output_string(command)).await;
            if let Some(err) = take_when_error(&sink) {
                self.record(idx, err);
            }
            result
        })
    }

    fn output_bytes<'life0, 'life1, 'async_trait>(
        &'life0 self,
        command: &'life1 processkit::Command,
    ) -> VerbFuture<'async_trait, PkProcessResult<Vec<u8>>>
    where
        'life0: 'async_trait,
        'life1: 'async_trait,
        Self: 'async_trait,
    {
        let idx = self.next.fetch_add(1, Ordering::Relaxed);
        Box::pin(async move {
            let sink = new_when_sink();
            let result = scope_when(sink.clone(), self.inner.output_bytes(command)).await;
            if let Some(err) = take_when_error(&sink) {
                self.record(idx, err);
            }
            result
        })
    }
}

// The run verbs are generic over the crate's `ProcessRunner` so the real
// `Runner` and the `ScriptedRunner` share one implementation.

pub(crate) fn runner_output<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<PyProcessResult> {
    with_when_capture_sync(py, runner.output_string(&command.inner)).map(PyProcessResult::from)
}

pub(crate) fn runner_output_bytes<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<PyBytesResult> {
    with_when_capture_sync(py, runner.output_bytes(&command.inner)).map(PyBytesResult::from)
}

pub(crate) fn runner_run<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<String> {
    with_when_capture_sync(py, runner.run(&command.inner))
}

pub(crate) fn runner_exit_code<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<i32> {
    with_when_capture_sync(py, runner.exit_code(&command.inner))
}

pub(crate) fn runner_probe<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<bool> {
    with_when_capture_sync(py, runner.probe(&command.inner))
}

fn runner_start<R: ProcessRunner + Sync + ?Sized>(
    py: Python<'_>,
    runner: &R,
    command: &PyCommand,
) -> PyResult<PyRunningProcess> {
    // `start()` is async, so `block_on` (inside the capture wrapper) provides the
    // runtime context while it (and its pump spawn) is polled — no `enter()`
    // needed.
    with_when_capture_sync(py, runner.start(&command.inner)).map(PyRunningProcess::from)
}

// Async run verbs over an owned `Arc<R>` so the future can hold the runner with
// no borrow of the pyclass.

pub(crate) fn runner_aoutput<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    with_when_capture_async(py, async move {
        runner.output_string(&cmd).await.map(PyProcessResult::from)
    })
}

pub(crate) fn runner_aoutput_bytes<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    with_when_capture_async(py, async move {
        runner.output_bytes(&cmd).await.map(PyBytesResult::from)
    })
}

pub(crate) fn runner_arun<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    with_when_capture_async(py, async move { runner.run(&cmd).await })
}

pub(crate) fn runner_aexit_code<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    with_when_capture_async(py, async move { runner.exit_code(&cmd).await })
}

pub(crate) fn runner_aprobe<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    with_when_capture_async(py, async move { runner.probe(&cmd).await })
}

fn runner_astart<'py, R: ProcessRunner + Send + Sync + 'static>(
    py: Python<'py>,
    runner: Arc<R>,
    command: &PyCommand,
) -> PyResult<Bound<'py, PyAny>> {
    let cmd = command.inner.clone();
    with_when_capture_async(py, async move {
        runner.start(&cmd).await.map(PyRunningProcess::from)
    })
}

/// Wrap a Python predicate `(Command) -> bool` as a `ScriptedRunner.when`
/// rule. The crate's rule predicate is infallible (`-> bool`), so a raising or
/// non-`bool` predicate cannot abort reply resolution by itself. Instead the
/// error is **stashed in the active per-call sink** ([`WHEN_PREDICATE_ERROR`])
/// and the wrapper returns `true` (matches) so the crate stops at this rule
/// rather than falling through to a later rule or the fallback; the enclosing run
/// verb ([`with_when_capture_sync`]/[`with_when_capture_async`]) then re-raises
/// the stashed error to the caller. A broken match predicate must surface — not
/// silently pick a fallback reply that could mask a defect.
///
/// Outside any active sink it keeps the prior behavior: read as "does not match"
/// with the error surfaced via the unraisable hook (visible on stderr) rather
/// than propagated across the FFI boundary. Every Python path that drives a
/// `ScriptedRunner` now opens a sink — the runner's own verbs, an injected runner
/// under a `CliClient`/`Supervisor`, and each command of a batch — so this
/// fallback is reached only when no live scope can catch it (e.g. a predicate
/// firing during interpreter finalization).
fn make_command_predicate(
    callback: Py<PyAny>,
) -> impl Fn(&processkit::Command) -> bool + Send + Sync + 'static {
    move |command| {
        // `try_attach`, not `attach`: a scripted-runner predicate can run on a
        // tokio worker not joined at `Py_Finalize` (the runtime is an immortal
        // singleton). A finalizing interpreter yields `None` -> the safe "does
        // not match" default, instead of the panic/crash a plain `attach` would
        // cause at shutdown. Same finalization guard as `logging.rs`'s bridge.
        Python::try_attach(|py| {
            let py_command = match Py::new(
                py,
                PyCommand {
                    inner: command.clone(),
                },
            ) {
                Ok(py_command) => py_command,
                Err(err) => return propagate_when_error(py, err, None),
            };
            match callback
                .call1(py, (py_command,))
                .and_then(|value| value.extract::<bool>(py))
            {
                Ok(matches) => matches,
                Err(err) => propagate_when_error(py, err, Some(callback.bind(py))),
            }
        })
        .unwrap_or(false)
    }
}

/// Route a `when`-predicate error to the active per-call sink and return the
/// match verdict the crate should see. In scope: stash it and return `true`, so
/// reply resolution stops at this rule (no fallthrough) and the run verb
/// re-raises. Out of scope: fall back to the unraisable hook and read as "does
/// not match" (`false`), the prior behavior. `hook_target` names the callback in
/// the unraisable report (`None` for a bridge/argument-build error).
fn propagate_when_error(
    py: Python<'_>,
    err: PyErr,
    hook_target: Option<&Bound<'_, PyAny>>,
) -> bool {
    match stash_when_error(err) {
        None => true,
        Some(err) => {
            err.write_unraisable(py, hook_target);
            false
        }
    }
}

/// Wrap a Python callable `(str) -> None` as a `DryRunRunner.on_invocation`
/// reaction. Mirrors `make_command_predicate`'s infallible-bridge convention: a
/// dry-run echo is a fire-and-forget side effect, so a raising callback is
/// surfaced via the unraisable hook (visible on stderr) rather than propagated
/// — a broken echo must not derail the run it was only observing.
fn make_invocation_callback(callback: Py<PyAny>) -> impl Fn(&str) + Send + Sync + 'static {
    move |line| {
        // `try_attach`, not `attach`: a dry-run echo can fire from a tokio worker
        // not joined at `Py_Finalize`. A finalizing interpreter yields `None`, so
        // the echo is dropped as a no-op — a plain `attach` would panic/crash at
        // shutdown. Same finalization guard as `logging.rs`'s bridge.
        let _ = Python::try_attach(|py| {
            if let Err(err) = callback.call1(py, (line,)) {
                err.write_unraisable(py, Some(callback.bind(py)));
            }
        });
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
    // Every runner pyclass is now `#[pyclass(frozen)]`, so read it with `.get()`
    // (infallible, no runtime borrow) instead of the old `.borrow()` — which
    // took a shared PyO3 borrow that a concurrent (pre-`frozen`) `&mut self`
    // builder could reject with a `PanicException`. `.runner()` hands back the
    // concrete `Arc<…>`, unsize-coerced to the trait object at the return type.
    if let Ok(r) = obj.cast::<PyRunner>() {
        return Ok(r.get().runner());
    }
    if let Ok(r) = obj.cast::<PyScriptedRunner>() {
        return Ok(r.get().runner());
    }
    if let Ok(r) = obj.cast::<PyRecordingRunner>() {
        return Ok(r.get().runner());
    }
    if let Ok(r) = obj.cast::<PyRecordReplayRunner>() {
        return Ok(r.get().runner());
    }
    if let Ok(r) = obj.cast::<PyDryRunRunner>() {
        return Ok(r.get().runner());
    }
    Err(pyo3::exceptions::PyTypeError::new_err(
        "runner must be one of Runner, ScriptedRunner, RecordingRunner, RecordReplayRunner, \
         DryRunRunner",
    ))
}

/// Emit a runner pyclass's `#[pymethods]` block: the six sync + six async run-verb
/// forwarders (every runner delegates these to the generic `runner_*` helpers
/// over its `self.runner()` accessor — a uniform inherent method every runner
/// pyclass defines that hands back an owned `Arc<ConcreteRunner>`, so the macro
/// stays agnostic to whether the field is a plain `Arc` or a reconfigurable
/// `Mutex<Arc<…>>`), spliced together with the type's own methods. PyO3's
/// `multiple-pymethods` is off, so a pyclass may have only ONE `#[pymethods]`
/// impl — `$unique` captures the constructor / builders / `__repr__` as a token
/// tree (attributes like `#[new]` / `#[staticmethod]` included) and is emitted in
/// the same block as the shared verbs. This is the single source of truth for the
/// run-verb surface across all five runners.
macro_rules! runner_pymethods {
    ($ty:ty { $($unique:tt)* }) => {
        #[pymethods]
        impl $ty {
            $($unique)*

            /// Run a command and capture output (a non-zero exit is data).
            fn output(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyProcessResult> {
                runner_output(py, &*self.runner(), command)
            }

            /// Run a command and capture raw-bytes stdout.
            fn output_bytes(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyBytesResult> {
                runner_output_bytes(py, &*self.runner(), command)
            }

            /// Require a zero exit and return trimmed stdout.
            fn run(&self, py: Python<'_>, command: &PyCommand) -> PyResult<String> {
                runner_run(py, &*self.runner(), command)
            }

            /// The command's exit code.
            fn exit_code(&self, py: Python<'_>, command: &PyCommand) -> PyResult<i32> {
                runner_exit_code(py, &*self.runner(), command)
            }

            /// Read a predicate command's exit code as a bool.
            fn probe(&self, py: Python<'_>, command: &PyCommand) -> PyResult<bool> {
                runner_probe(py, &*self.runner(), command)
            }

            /// Start a command and return a `RunningProcess`.
            fn start(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyRunningProcess> {
                runner_start(py, &*self.runner(), command)
            }

            /// Async counterpart of `output()`.
            fn aoutput<'py>(
                &self,
                py: Python<'py>,
                command: &PyCommand,
            ) -> PyResult<Bound<'py, PyAny>> {
                runner_aoutput(py, self.runner(), command)
            }

            /// Async counterpart of `output_bytes()`.
            fn aoutput_bytes<'py>(
                &self,
                py: Python<'py>,
                command: &PyCommand,
            ) -> PyResult<Bound<'py, PyAny>> {
                runner_aoutput_bytes(py, self.runner(), command)
            }

            /// Async counterpart of `run()`.
            fn arun<'py>(
                &self,
                py: Python<'py>,
                command: &PyCommand,
            ) -> PyResult<Bound<'py, PyAny>> {
                runner_arun(py, self.runner(), command)
            }

            /// Async counterpart of `exit_code()`.
            fn aexit_code<'py>(
                &self,
                py: Python<'py>,
                command: &PyCommand,
            ) -> PyResult<Bound<'py, PyAny>> {
                runner_aexit_code(py, self.runner(), command)
            }

            /// Async counterpart of `probe()`.
            fn aprobe<'py>(
                &self,
                py: Python<'py>,
                command: &PyCommand,
            ) -> PyResult<Bound<'py, PyAny>> {
                runner_aprobe(py, self.runner(), command)
            }

            /// Async counterpart of `start()`.
            fn astart<'py>(
                &self,
                py: Python<'py>,
                command: &PyCommand,
            ) -> PyResult<Bound<'py, PyAny>> {
                runner_astart(py, self.runner(), command)
            }
        }
    };
}

/// The real process runner. Inject it where you'd otherwise call `Command`
/// verbs directly, so the same code can take a `ScriptedRunner` under test.
///
/// `frozen`: it holds an immutable `Arc<JobRunner>` (no builders), so `&self`
/// throughout — a concurrent call from another thread never trips PyO3's borrow
/// flag, and `extract_runner` reads it via `.get()` with no runtime borrow.
#[pyclass(name = "Runner", module = "processkit", frozen)]
pub(crate) struct PyRunner {
    inner: Arc<JobRunner>,
}

impl PyRunner {
    /// The shared accessor the `runner_pymethods!` verbs use (see the macro).
    fn runner(&self) -> Arc<JobRunner> {
        self.inner.clone()
    }
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
/// `frozen` + `Mutex<Arc<…>>`: every method (run verbs AND builders) is `&self`,
/// so a concurrent call from another thread serializes on the std mutex rather
/// than racing PyO3's borrow flag into a raw `RuntimeError`. The builders used
/// to take `&mut self`, which meant `runner.on(...)` on one thread and
/// `runner.output(...)` on another could collide on that exclusive borrow; they
/// now reconfigure through interior mutability instead.
#[pyclass(name = "ScriptedRunner", module = "processkit.testing", frozen)]
pub(crate) struct PyScriptedRunner {
    // The `Arc` still lets the async run verbs hold the runner across the await;
    // a builder reconfigures it via `Arc::try_unwrap`, which requires no
    // in-flight call (sync or async). The lock is only ever held for the brief,
    // non-awaiting swap — never across a `block_on`/await — so it cannot
    // serialize a run or deadlock.
    inner: Mutex<Arc<PkScriptedRunner>>,
}

impl PyScriptedRunner {
    /// The shared accessor the `runner_pymethods!` verbs use: clone the current
    /// runner `Arc` out from under the lock (released before this returns, so a
    /// verb never holds it across its `block_on`/await).
    fn runner(&self) -> Arc<PkScriptedRunner> {
        self.inner
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }

    /// Apply a consuming builder to the wrapped runner. Requires sole ownership
    /// (no sync or async call holding a clone); `Arc::try_unwrap` fails cleanly
    /// otherwise. The lock is held only for the non-awaiting swap.
    fn reconfigure(
        &self,
        build: impl FnOnce(PkScriptedRunner) -> PkScriptedRunner,
    ) -> PyResult<()> {
        let mut guard = self.inner.lock().unwrap_or_else(PoisonError::into_inner);
        let placeholder = Arc::new(PkScriptedRunner::new());
        match Arc::try_unwrap(std::mem::replace(&mut *guard, placeholder)) {
            Ok(runner) => {
                *guard = Arc::new(build(runner));
                Ok(())
            }
            Err(original) => {
                *guard = original;
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
            inner: Mutex::new(Arc::new(PkScriptedRunner::new())),
        }
    }

    /// Reply with `reply` when a command's argv starts with `prefix`. `prefix`
    /// elements accept a `str` or any `os.PathLike[str]` — unified with
    /// `Command`'s own `arg`/`args` typing, since a prefix matches against a
    /// `Command`'s actual argv (which can itself contain path elements).
    fn on(&self, prefix: Vec<PathBuf>, reply: &PyReply) -> PyResult<()> {
        let reply = reply.inner.clone();
        self.reconfigure(move |runner| runner.on(prefix, reply))
    }

    /// The reply for any command not matched by an `on(...)` rule.
    fn fallback(&self, reply: &PyReply) -> PyResult<()> {
        let reply = reply.inner.clone();
        self.reconfigure(move |runner| runner.fallback(reply))
    }

    /// Reply with `reply` when `predicate(command)` accepts it — for a match
    /// that isn't a plain argv prefix (`on()`), e.g. inspecting `cwd`/`env`/
    /// flags via `Command`'s own inspection accessors. A `predicate` that
    /// raises or returns a non-`bool` aborts the run verb with that error (like
    /// `Supervisor.stop_when`) rather than selecting the next rule or the
    /// fallback — a broken match predicate surfaces instead of silently masking
    /// a test defect behind a fallback reply. This holds on every path the runner
    /// can be driven from: its own verbs, an injected runner under a `CliClient`
    /// or a `Supervisor`, and each command of a batch (`output_all`/…) — where
    /// the error surfaces in that command's own result slot.
    fn when(&self, predicate: Py<PyAny>, reply: &PyReply) -> PyResult<()> {
        let reply = reply.inner.clone();
        self.reconfigure(move |runner| runner.when(make_command_predicate(predicate), reply))
    }

    /// Reply with each of `replies` in turn on successive matching calls (the
    /// first match gets the first reply, the second the second, …); once
    /// exhausted, the last reply repeats forever. The declarative form for
    /// retry scenarios (fail once, then succeed). Matches like `on()` (program
    /// + argument prefix).
    fn on_sequence(
        &self,
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
        // `try_borrow`, not the panicking `borrow`: a concurrent access to one
        // of these `Reply` handles from another thread must surface as a clean
        // `PyErr`, not a `PanicException` across the FFI boundary.
        let replies: Vec<PkReply> = replies
            .iter()
            .map(|r| Ok(r.try_borrow(py)?.inner.clone()))
            .collect::<PyResult<_>>()?;
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
/// `frozen`: an immutable `Arc<…>` (no builders; `record`/`replay` are
/// constructors and `save` only reads), so `&self` throughout and no borrow-flag
/// race with a concurrent call.
#[pyclass(name = "RecordReplayRunner", module = "processkit.testing", frozen)]
pub(crate) struct PyRecordReplayRunner {
    inner: Arc<PkRecordReplayRunner<JobRunner>>,
}

impl PyRecordReplayRunner {
    /// The shared accessor the `runner_pymethods!` verbs use (see the macro).
    fn runner(&self) -> Arc<PkRecordReplayRunner<JobRunner>> {
        self.inner.clone()
    }
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
/// `frozen`: an immutable `Arc<…>` — every recorded call is captured through the
/// crate runner's own internal synchronization (`calls()`/`only_call()` just
/// read a snapshot), so this pyclass needs no builder and stays `&self`
/// throughout, with no borrow-flag race with a concurrent call.
#[pyclass(name = "RecordingRunner", module = "processkit.testing", frozen)]
pub(crate) struct PyRecordingRunner {
    // Type-erased (not the crate's own `RecordingRunner<ScriptedRunner>`
    // specialization), so `new()` can wrap ANY of the five runner pyclasses —
    // not just a fresh `ScriptedRunner` the way `replying()` builds one.
    inner: Arc<PkRecordingRunner<Arc<dyn ProcessRunner + Send + Sync>>>,
}

impl PyRecordingRunner {
    /// The shared accessor the `runner_pymethods!` verbs use (see the macro).
    fn runner(&self) -> Arc<PkRecordingRunner<Arc<dyn ProcessRunner + Send + Sync>>> {
        self.inner.clone()
    }
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
    /// `DryRunRunner`, or another `RecordingRunner` — recording every call made
    /// through it. The general form behind `replying()`, for combining
    /// recording with a double you've already built (e.g. a
    /// `RecordReplayRunner` cassette or a `DryRunRunner`) or with the real
    /// `Runner`.
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
/// `frozen` + `Mutex<Arc<…>>`, mirroring `PyScriptedRunner`: `on_invocation` is a
/// builder that used to take `&mut self` and could collide with a concurrent
/// verb's borrow; it now reconfigures through interior mutability, so every
/// method is `&self`.
#[pyclass(name = "DryRunRunner", module = "processkit.testing", frozen)]
pub(crate) struct PyDryRunRunner {
    // `Arc` so the async run verbs can hold the runner across the await;
    // `on_invocation` reconfigures it via `Arc::try_unwrap`, which requires no
    // in-flight call. The lock is only held for the brief, non-awaiting swap.
    inner: Mutex<Arc<PkDryRunRunner>>,
}

impl PyDryRunRunner {
    /// The shared accessor the `runner_pymethods!` verbs (and `commands()`/
    /// `only_command()`/`__repr__`) use: clone the current runner `Arc` out from
    /// under the lock, released before this returns.
    fn runner(&self) -> Arc<PkDryRunRunner> {
        self.inner
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clone()
    }

    /// Apply a consuming builder to the wrapped runner. Requires sole ownership
    /// (no sync or async call holding a clone); the rendered-commands log is
    /// carried across, since the builder only sets the callback field. The lock
    /// is held only for the non-awaiting swap.
    fn reconfigure(&self, build: impl FnOnce(PkDryRunRunner) -> PkDryRunRunner) -> PyResult<()> {
        let mut guard = self.inner.lock().unwrap_or_else(PoisonError::into_inner);
        let placeholder = Arc::new(PkDryRunRunner::new());
        match Arc::try_unwrap(std::mem::replace(&mut *guard, placeholder)) {
            Ok(runner) => {
                *guard = Arc::new(build(runner));
                Ok(())
            }
            Err(original) => {
                *guard = original;
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
            inner: Mutex::new(Arc::new(PkDryRunRunner::new())),
        }
    }

    /// Call `callback` with each command's rendered line as it is dry-run
    /// "executed" — e.g. printing it for a tool's `--dry-run` echo — **in
    /// addition to**, not instead of, the collected `commands()` snapshot.
    /// `callback` is infallible from the crate's perspective: a raising one is
    /// surfaced via the unraisable hook (like `ScriptedRunner.when`'s
    /// predicate) rather than propagating across the FFI boundary.
    fn on_invocation(&self, callback: Py<PyAny>) -> PyResult<()> {
        self.reconfigure(move |runner| runner.on_invocation(make_invocation_callback(callback)))
    }

    /// The rendered command line for every call so far, in order — each
    /// produced by `Command.command_line()`, the same display quoting you'd
    /// reach for by hand.
    fn commands(&self) -> Vec<String> {
        self.runner().commands()
    }

    /// The single rendered command line; raises `ProcessError` unless exactly
    /// one call was made. (Reimplemented over `commands()` rather than the
    /// crate's own `only_command()`, which *panics* on the wrong count — a
    /// Python-reachable call must raise, not abort across the FFI boundary.)
    fn only_command(&self) -> PyResult<String> {
        let commands = self.runner().commands();
        match commands.len() {
            1 => Ok(commands.into_iter().next().expect("length checked above")),
            n => Err(ProcessError::new_err(format!(
                "expected exactly one dry-run call, got {n}"
            ))),
        }
    }

    fn __repr__(&self) -> String {
        format!("DryRunRunner(commands={})", self.runner().commands().len())
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
