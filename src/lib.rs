//! PyO3 bindings to the `processkit` Rust crate — a thin binding, not a
//! reimplementation. The crate is async-throughout (tokio); this layer owns the
//! single tokio runtime (`pyo3-async-runtimes`' managed runtime) and drives the
//! crate's futures to completion for the synchronous surface. The GIL is
//! released around every blocking call so other Python threads run, and the
//! wait is broken into ticks so that `Ctrl+C` interrupts a blocked call.

use pyo3::prelude::*;

mod command;
mod convert;
mod errors;
mod group;
mod result;
mod runner;
mod running;
mod runtime;
mod supervisor;

use crate::command::{PyCommand, PyPipeline};
use crate::errors::{
    init_dual_exceptions, Cancelled, NonZeroExit, OutputTooLarge, ProcessError, ResourceLimit,
    Signalled, Unsupported,
};
use crate::group::{PyProcessGroup, PyProcessGroupStats};
use crate::result::{PyBytesResult, PyFinished, PyOutcome, PyOutputEvent, PyProcessResult};
use crate::runner::{PyReply, PyRunner, PyScriptedRunner};
use crate::running::{PyOutputEvents, PyProcessStdin, PyRunningProcess, PyStdoutLines};
use crate::supervisor::{PySupervisionOutcome, PySupervisor};

#[pymodule]
fn _processkit(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCommand>()?;
    m.add_class::<PyProcessResult>()?;
    m.add_class::<PyBytesResult>()?;
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
    m.add_class::<PyRunner>()?;
    m.add_class::<PyScriptedRunner>()?;
    m.add_class::<PyReply>()?;

    let py = m.py();
    // Register the single-base exceptions, normalizing `__module__` to the
    // public package so reprs/tracebacks read `processkit.X` rather than leaking
    // the private `_processkit` extension name (the dual-base ones below set it
    // at construction, and the pyclasses use `module = "processkit"`).
    for (name, ty) in [
        ("ProcessError", py.get_type::<ProcessError>()),
        ("NonZeroExit", py.get_type::<NonZeroExit>()),
        ("Cancelled", py.get_type::<Cancelled>()),
        ("Signalled", py.get_type::<Signalled>()),
        ("ResourceLimit", py.get_type::<ResourceLimit>()),
        ("Unsupported", py.get_type::<Unsupported>()),
        ("OutputTooLarge", py.get_type::<OutputTooLarge>()),
    ] {
        ty.setattr("__module__", "processkit")?;
        m.add(name, ty)?;
    }
    // `Timeout` and `ProcessNotFound` are dual-base (also `TimeoutError` /
    // `FileNotFoundError`); built and registered here.
    init_dual_exceptions(m)?;
    Ok(())
}
