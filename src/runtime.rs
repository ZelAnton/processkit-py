//! The single tokio runtime the binding owns and the interruptible blocking
//! driver that powers the synchronous surface.

use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Mutex as StdMutex, MutexGuard as StdMutexGuard, PoisonError};
use std::time::Duration;

use pyo3::prelude::*;
use pyo3::{intern, IntoPyObjectExt};

use crate::errors::{map_err, ProcessError};

/// The one tokio runtime the binding owns, shared by the sync surface
/// (`block_on`) and the async surface (`future_into_py`).
///
/// This is the *raw*, infallible accessor. Every path that actually **drives**
/// the runtime — `block_on`, `future_into_py`, or `Runtime::enter` to spawn a
/// stream pump — must first pass [`guard_against_fork`] (directly, or via the
/// checked [`runtime`] accessor) so a runtime copied into a POSIX `fork()` child
/// is refused instead of hung.
pub(crate) fn rt() -> &'static tokio::runtime::Runtime {
    pyo3_async_runtimes::tokio::get_runtime()
}

/// PID of the process that first touched the shared tokio runtime, or `0` before
/// the first touch. Set once on first access and compared on every later one to
/// detect a POSIX `fork()` that copied an already-initialized runtime into a
/// child (see [`guard_against_fork`]). A real `getpid()` is never `0`, so `0` is
/// a safe "not yet claimed" sentinel.
static RUNTIME_OWNER_PID: AtomicU32 = AtomicU32::new(0);

/// Fail fast if the shared tokio runtime would be driven from a process that
/// `fork()`ed *after* the runtime was already initialized in its parent.
///
/// `pyo3-async-runtimes` keeps the tokio runtime in a process-global `OnceLock`.
/// A POSIX `fork()` copies that struct — including the `OnceLock`'s "already
/// initialized" flag — into the child, but **not** the runtime's worker threads:
/// `fork()` carries only the calling thread into the child. So in the child the
/// runtime *looks* ready yet has no workers to drive I/O, and any lock a vanished
/// worker held at fork time (the tokio I/O driver's, the allocator's) stays
/// locked forever. Driving it there — `block_on`, `future_into_py`, or even
/// `Runtime::enter` plus spawning a stream pump — hangs or panics with no
/// recovery.
///
/// We cannot rebuild the managed runtime in the child: its `OnceLock` is already
/// set and private to `pyo3-async-runtimes`, so there is no sound "reset". The
/// only safe answer is to refuse quickly and clearly and point the caller at the
/// `spawn` / `forkserver` multiprocessing start methods (see
/// `docs/platforms.md`). Claiming ownership on the first *touch* rather than at
/// import means a process that forks *before* its first processkit call is
/// unaffected — its child simply initializes its own fresh runtime.
fn guard_against_fork() -> PyResult<()> {
    // `std::process::id()` is an uncached `getpid()` on Unix, so it reflects the
    // child's real PID immediately after `fork()` (not the parent's). On Windows,
    // where there is no `fork()`, the PID never changes and this is a no-op.
    let me = std::process::id();
    // Claim ownership on the first touch; otherwise the stored owner must be us.
    // A stored owner that is neither `0` nor `me` is a parent's PID carried in by
    // `fork()` — exactly the hazard we refuse.
    match RUNTIME_OWNER_PID.compare_exchange(0, me, Ordering::AcqRel, Ordering::Acquire) {
        Ok(_) => Ok(()),
        Err(owner) if owner == me => Ok(()),
        Err(_forked) => Err(ProcessError::new_err(
            "processkit's async runtime was initialized in a parent process and \
             cannot be used here: this process was created by POSIX fork() (for \
             example os.fork(), or multiprocessing / ProcessPoolExecutor with the \
             default 'fork' start method on Linux) after processkit had already \
             run. A forked child does not inherit the runtime's worker threads, so \
             driving it now would hang or panic. Use the 'spawn' or 'forkserver' \
             start method (multiprocessing.get_context(\"spawn\")), or perform the \
             fork before the first processkit call.",
        )),
    }
}

/// The shared runtime, guarded against post-`fork()` use. Use this over [`rt`]
/// anywhere the returned handle is driven immediately (`enter` to spawn a stream
/// pump); [`rt`] stays infallible for the hot loop in [`block_on_interruptible`],
/// which runs [`guard_against_fork`] once up front instead of per iteration.
pub(crate) fn runtime() -> PyResult<&'static tokio::runtime::Runtime> {
    guard_against_fork()?;
    Ok(rt())
}

/// Bridge a crate future to a Python awaitable: convert its error to the right
/// Python exception with `map_err`, its success value to the matching Python
/// wrapper, and hand the whole thing to the single lazy, owner-aware bridge
/// (`PyLazyFuture`). The caller maps the success value inside `fut` (e.g.
/// `.map(PyProcessResult::from)`); a scalar result (`String` / `i32` / `bool`)
/// passes through unchanged. This is the async twin of the sync `block_on` and
/// keeps every `a`-prefixed verb a one-liner.
///
/// Unlike a bare `future_into_py`, the returned awaitable does **not** start the
/// work until it is first `await`ed — see [`PyLazyFuture`] for the full
/// lifecycle contract (lazy start, owner-driven teardown, unchanged
/// cancellation).
pub(crate) fn drive_async<F, U>(py: Python<'_>, fut: F) -> PyResult<Bound<'_, PyAny>>
where
    F: Future<Output = Result<U, processkit::Error>> + Send + 'static,
    U: for<'py> IntoPyObject<'py> + Send + 'static,
{
    lazy_bridge(py, async move {
        let value = fut.await.map_err(map_err)?;
        // Convert to a Python object here so every `a`-verb's distinct success
        // type collapses to the one erased bridge type. The GIL is held only for
        // the conversion itself — the same inline-`attach` pattern the batch
        // helpers already use inside `future_into_py`.
        Python::attach(|py| value.into_py_any(py))
    })
}

/// Like [`drive_async`], but for a future that already yields a `PyResult`
/// (its own Python exception, e.g. `StopAsyncIteration` from a streaming
/// `__anext__`, or a raw `PyOSError` from a stdin write) rather than a crate
/// error. Routes through the same lazy bridge so every `a`-prefixed awaitable
/// — consuming verb, streaming step, or async context-manager entry — shares
/// one lifecycle contract instead of calling `future_into_py` directly.
pub(crate) fn drive_async_py<F, T>(py: Python<'_>, fut: F) -> PyResult<Bound<'_, PyAny>>
where
    F: Future<Output = PyResult<T>> + Send + 'static,
    T: for<'py> IntoPyObject<'py> + Send + 'static,
{
    lazy_bridge(py, async move {
        let value = fut.await?;
        Python::attach(|py| value.into_py_any(py))
    })
}

/// The inert, type-erased bridged work a [`PyLazyFuture`] holds until its first
/// `await`: it awaits the crate/Python future and converts the outcome to a
/// Python object under the GIL — the tail `future_into_py` runs at completion.
/// Boxed so every `a`-verb's distinct future type collapses to one bridge type.
type BridgedWork = Pin<Box<dyn Future<Output = PyResult<Py<PyAny>>> + Send + 'static>>;

/// Wrap inert bridged `work` in a lazy, owner-aware [`PyLazyFuture`]. Nothing is
/// scheduled here: a Rust future does nothing until polled, and `PyLazyFuture`
/// does not hand it to the runtime until it is first awaited.
fn lazy_bridge<F>(py: Python<'_>, work: F) -> PyResult<Bound<'_, PyAny>>
where
    F: Future<Output = PyResult<Py<PyAny>>> + Send + 'static,
{
    let lazy = PyLazyFuture {
        state: StdMutex::new(LazyState::Pending(Box::pin(work))),
    };
    Ok(Py::new(py, lazy)?.into_bound(py).into_any())
}

/// The single async bridge every `a`-prefixed verb returns: a lazily-scheduled,
/// owner-aware awaitable with an explicit lifecycle contract.
///
/// # Why not raw `future_into_py`
///
/// `pyo3_async_runtimes::tokio::future_into_py` *eagerly* spawns its future on
/// the shared runtime the instant it is called and keeps a strong reference to
/// the backing `asyncio.Future`, so the work runs to completion even if the
/// awaitable is never awaited, its last Python owner is dropped, or the event
/// loop closes underneath it. For a plain `Command.aoutput()` that leaks a
/// child; for `Supervisor(restart="always").arun()` it is an immortal restart
/// loop that pins every captured Python callback (`stop_when`/`give_up_when`)
/// until the interpreter exits — and a detached task that may reach for the GIL
/// (`Python::attach`) during interpreter finalization.
///
/// # Contract
///
/// * **Ownership.** While `Pending`, this owns the inert work future and
///   everything it captured — including a process handle a consuming verb took
///   eagerly out of `self` (`RunningProcess.aoutput()` & co.). On the first
///   `await`, ownership of the work transfers to the runtime.
/// * **Lazy start.** A Rust future is inert until polled, and this does not
///   hand the work to `future_into_py` until `__await__`. So an `a`-verb called
///   **without `await`** starts nothing at all.
/// * **Owner-driven teardown.** Dropping a `Pending` awaitable — an `a`-verb
///   called without `await`, or its last owner lost before the first `await` —
///   drops the inert future, releasing every Python object it captured and, for
///   a future that already owns a started process/tree, tearing that tree down
///   via kill-on-drop. Nothing was ever scheduled, so no detached task survives
///   to touch Python during finalization.
/// * **Cancellation is unchanged.** Once awaited, `future_into_py` schedules
///   the work exactly once and returns the real `asyncio.Future`; from then on
///   we delegate to its own `__await__` and cancellation, so `Future.cancel()`
///   still raises `CancelledError` and tears the process tree down exactly as
///   before.
#[pyclass(module = "processkit")]
pub(crate) struct PyLazyFuture {
    state: StdMutex<LazyState>,
}

enum LazyState {
    /// Built but not yet scheduled — nothing runs until `__await__`.
    Pending(BridgedWork),
    /// Scheduled: the backing `asyncio.Future` `future_into_py` returned, whose
    /// own await/cancel machinery every later `__await__` delegates to.
    Started(Py<PyAny>),
    /// The work was taken to be scheduled but `future_into_py` failed (no
    /// running loop); the future — and any process it owned — was already
    /// dropped, so there is nothing left to await.
    Spent,
}

impl PyLazyFuture {
    /// Lock the state, recovering from a (never-expected) poisoned mutex rather
    /// than panicking across the FFI boundary — the guarded sections never
    /// panic, so poisoning cannot actually happen.
    fn lock(&self) -> StdMutexGuard<'_, LazyState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[pymethods]
impl PyLazyFuture {
    /// Schedule the work on the first `await` (the one place it is actually
    /// spawned) and delegate to the backing `asyncio.Future`'s own await/cancel
    /// machinery. Idempotent on re-await: later calls delegate to the same
    /// backing future, mirroring `asyncio.Future` semantics.
    fn __await__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        // Refuse before touching state so a fork child fails cleanly and
        // idempotently on every await, without spending the inert work (which
        // `future_into_py` below would otherwise schedule onto a runtime whose
        // worker threads did not survive the fork).
        guard_against_fork()?;
        let mut state = self.lock();
        if let LazyState::Started(inner) = &*state {
            return inner.bind(py).call_method0(intern!(py, "__await__"));
        }
        let work = match std::mem::replace(&mut *state, LazyState::Spent) {
            LazyState::Pending(work) => work,
            // `Started` is handled above; `Spent` means a prior `__await__` took
            // the work and `future_into_py` failed, dropping it (and any process
            // it owned) already.
            LazyState::Started(_) | LazyState::Spent => {
                return Err(ProcessError::new_err(
                    "this async operation has already been consumed",
                ));
            }
        };
        // Hand the inert work to the runtime. On success, remember the backing
        // future so a re-await delegates to it; on failure the work (and any
        // process it owns) has already been dropped and the state stays `Spent`.
        let inner = pyo3_async_runtimes::tokio::future_into_py(py, work)?;
        *state = LazyState::Started(inner.clone().unbind());
        inner.call_method0(intern!(py, "__await__"))
    }

    fn __repr__(&self) -> &'static str {
        match &*self.lock() {
            LazyState::Pending(_) => "<processkit awaitable (pending)>",
            LazyState::Started(_) => "<processkit awaitable (started)>",
            LazyState::Spent => "<processkit awaitable (spent)>",
        }
    }
}

/// Drive a crate future to completion on the sync surface and convert a crate
/// error to the right Python exception with `map_err` — the sync twin of
/// `drive_async`. The caller maps the success value to its Python wrapper on the
/// returned `PyResult` (e.g. `.map(PyProcessResult::from)`); a scalar result
/// (`String` / `i32` / `bool` / `()`) is returned as-is. This is the interruptible
/// `block_on_interruptible(...)?.map_err(map_err)` dance in one place, so every
/// sync verb is a one-liner and `map_err` lives in a single spot.
pub(crate) fn block_on<F, U>(py: Python<'_>, fut: F) -> PyResult<U>
where
    F: std::future::Future<Output = Result<U, processkit::Error>> + Send,
    U: Send,
{
    block_on_interruptible(py, fut)?.map_err(map_err)
}

/// How often a blocked sync call surfaces to check for pending Python signals.
const SIGNAL_POLL_INTERVAL: Duration = Duration::from_millis(100);

/// Drive a future to completion with the GIL released, re-acquiring it on a
/// fixed tick to honour pending signals (notably `Ctrl+C`). A fast future
/// returns on the first tick with no added latency; a slow one yields every
/// `SIGNAL_POLL_INTERVAL` so `Python::check_signals` can raise. When it raises,
/// `fut` is dropped here — which, for a run that owns its process group, tears
/// the tree down.
pub(crate) fn block_on_interruptible<F, T>(py: Python<'_>, fut: F) -> PyResult<T>
where
    F: std::future::Future<Output = T> + Send,
    T: Send,
{
    // Refuse a runtime copied into a POSIX `fork()` child before touching it —
    // otherwise `rt().block_on` below drives a runtime with no surviving worker
    // threads and hangs/panics for good. Checked once here, not per loop tick.
    guard_against_fork()?;
    // `rt().block_on` is NOT re-entrant: driving it from a thread that is already
    // inside the runtime panics ("Cannot start a runtime from within a runtime").
    // That happens if a Rust->Python callback running inside the runtime — e.g. a
    // `Supervisor` `stop_when` predicate — calls a synchronous verb. Detect it and
    // raise a clear error instead of letting tokio panic (PyO3 would otherwise turn
    // the panic into a `PanicException`, which the predicate wrapper swallows,
    // producing a silent, confusing failure). This is a no-op on the normal sync
    // path, where the calling thread holds no runtime context.
    reject_reentrant_runtime()?;
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

/// Whether an asyncio event loop is currently running on this thread — the
/// precondition the async surface needs. Check this *before* a consuming verb
/// takes its handle out of `self` so calling an `a`-prefixed verb from sync
/// code (no loop) raises here, cleanly, *before* the handle is consumed —
/// leaving it in place for the caller to reach for the correct sync twin. The
/// lazy bridge (`drive_async`) would otherwise happily wrap the taken handle in
/// a never-awaitable future whose only fate is kill-on-drop, silently spending
/// a live handle the caller could still have used.
pub(crate) fn require_event_loop(py: Python<'_>) -> PyResult<()> {
    pyo3_async_runtimes::tokio::get_current_loop(py)
        .map(|_| ())
        .map_err(|_| {
            ProcessError::new_err(
                "no running asyncio event loop; call this async (a-prefixed) verb \
                 with `await` from inside a coroutine, not from sync code",
            )
        })
}

/// Whether the calling thread is already inside the shared tokio runtime — the
/// same condition `block_on_interruptible` rejects above. Check this *before* a
/// sync consuming verb takes its handle out of `self`, for the same reason
/// `require_event_loop` is checked before `drive_async`.
pub(crate) fn reject_reentrant_runtime() -> PyResult<()> {
    if tokio::runtime::Handle::try_current().is_ok() {
        return Err(ProcessError::new_err(
            "cannot call a synchronous processkit verb from inside an async context \
             or a callback that runs on the runtime (e.g. a Supervisor stop_when \
             predicate); use the async (a-prefixed) API, or compute the value before \
             the callback",
        ));
    }
    Ok(())
}
