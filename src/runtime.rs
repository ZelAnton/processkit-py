//! The single tokio runtime the binding owns and the interruptible blocking
//! driver that powers the synchronous surface.

use std::time::Duration;

use pyo3::prelude::*;

use crate::errors::{map_err, ProcessError};

/// The one tokio runtime the binding owns, shared by the sync surface
/// (`block_on`) and the async surface (`future_into_py`).
pub(crate) fn rt() -> &'static tokio::runtime::Runtime {
    pyo3_async_runtimes::tokio::get_runtime()
}

/// Bridge a crate future to a Python awaitable: drive it on the shared runtime
/// (`future_into_py`) and convert a crate error to the right Python exception
/// with `map_err`. The caller maps the success value to its Python wrapper
/// inside the future (e.g. `.map(PyProcessResult::from)`); a scalar result
/// (`String` / `i32` / `bool`) passes through unchanged. This is the async twin
/// of the sync `block_on` and keeps every `a`-prefixed verb a one-liner.
pub(crate) fn drive_async<F, U>(py: Python<'_>, fut: F) -> PyResult<Bound<'_, PyAny>>
where
    F: std::future::Future<Output = Result<U, processkit::Error>> + Send + 'static,
    U: for<'py> IntoPyObject<'py> + Send + 'static,
{
    pyo3_async_runtimes::tokio::future_into_py(py, async move { fut.await.map_err(map_err) })
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
    // `rt().block_on` is NOT re-entrant: driving it from a thread that is already
    // inside the runtime panics ("Cannot start a runtime from within a runtime").
    // That happens if a Rust->Python callback running inside the runtime — e.g. a
    // `Supervisor` `stop_when` predicate — calls a synchronous verb. Detect it and
    // raise a clear error instead of letting tokio panic (PyO3 would otherwise turn
    // the panic into a `PanicException`, which the predicate wrapper swallows,
    // producing a silent, confusing failure). This is a no-op on the normal sync
    // path, where the calling thread holds no runtime context.
    if tokio::runtime::Handle::try_current().is_ok() {
        return Err(ProcessError::new_err(
            "cannot call a synchronous processkit verb from inside an async context \
             or a callback that runs on the runtime (e.g. a Supervisor stop_when \
             predicate); use the async (a-prefixed) API, or compute the value before \
             the callback",
        ));
    }
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
/// precondition `drive_async`/`future_into_py` need to schedule their bridged
/// future. Check this *before* a consuming verb takes its handle out of
/// `self`: `future_into_py` fails synchronously when no loop is running, and by
/// then the taken value would already be moved into the future it builds, so a
/// synchronous failure would drop it (kill-on-drop) instead of leaving it in
/// place for the caller to retry correctly.
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
