//! PyO3 bindings to the `processkit` Rust crate — a thin binding, not a
//! reimplementation. The crate is async-throughout (tokio); this layer owns the
//! single tokio runtime (`pyo3-async-runtimes`' managed runtime) and drives the
//! crate's futures to completion for the synchronous surface. The GIL is
//! released around every blocking call so other Python threads run, and the
//! wait is broken into ticks so that `Ctrl+C` interrupts a blocked call — on the
//! **main thread** only, since CPython delivers signals there (a sync verb run on
//! a worker thread blocks un-interruptibly; use the async API off the main
//! thread).

use pyo3::prelude::*;

mod batch;
mod cli;
mod command;
mod convert;
mod errors;
mod group;
mod logging;
mod result;
mod runner;
mod running;
mod runtime;
mod supervisor;

// `gil_used = false` opts the module into PEP 703 free-threaded CPython: on a
// free-threaded build importing it does NOT re-enable the GIL. Sound here because
// the binding holds no unsynchronized shared state — the tokio runtime is a
// managed singleton, the exception caches use `PyOnceLock`, stream handles are
// `Arc<Mutex<…>>`, the opt-in `tracing` subscriber is a stateless ZST layer over
// `tracing`'s internally-synchronized global dispatch (installed once via an
// `OnceLock`, forwarding to thread-safe `logging`), and every pyclass is guarded
// by PyO3's own per-object borrow checking. A no-op on the standard (GIL) build.
//
// Registration is delegated to each module's own `register(m)` fn (classes,
// functions, and — for `errors` — the exception hierarchy), so adding a new
// pyclass/function touches only its defining module, not this central list.
#[pymodule(gil_used = false)]
fn _processkit(m: &Bound<'_, PyModule>) -> PyResult<()> {
    command::register(m)?;
    result::register(m)?;
    group::register(m)?;
    running::register(m)?;
    supervisor::register(m)?;
    runner::register(m)?;
    cli::register(m)?;
    batch::register(m)?;
    logging::register(m)?;
    errors::register(m)?;
    Ok(())
}
