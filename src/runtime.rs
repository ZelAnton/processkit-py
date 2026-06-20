//! The single tokio runtime the binding owns and the interruptible blocking
//! driver that powers the synchronous surface.

use std::time::Duration;

use pyo3::prelude::*;

/// The one tokio runtime the binding owns, shared by the sync surface
/// (`block_on`) and the async surface (`future_into_py`).
pub(crate) fn rt() -> &'static tokio::runtime::Runtime {
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
pub(crate) fn block_on_interruptible<F, T>(py: Python<'_>, fut: F) -> PyResult<T>
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
