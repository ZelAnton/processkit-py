//! Module-level batch execution: run many `Command`s with bounded concurrency.
//!
//! Each result slot is a `ProcessResult` (a non-zero exit is data on it) or, for
//! a command that failed (a spawn or I/O error), the corresponding
//! `ProcessError` instance — mirroring the crate's per-command `Result`. The
//! batch never short-circuits.

use std::sync::Arc;

use processkit::output_all as pk_output_all;
use processkit::output_all_bytes as pk_output_all_bytes;
use processkit::JobRunner;
use processkit::ProcessResult as PkProcessResult;
use processkit::ProcessRunner;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::command::PyCommand;
use crate::errors::map_err;
use crate::result::{PyBytesResult, PyProcessResult};
use crate::runner::{extract_runner, WhenCaptureRunner};
use crate::runtime::{block_on_interruptible, drive_async_py};

/// Resolve an optional Python `runner=` argument to the runner every command in
/// the batch is driven through: the real `JobRunner` by default, or whatever
/// `extract_runner` downcasts the given object to (a `ScriptedRunner` and
/// friends, for hermetic batch tests with no real spawns).
fn resolve_runner(
    runner: Option<&Bound<'_, PyAny>>,
) -> PyResult<Arc<dyn ProcessRunner + Send + Sync>> {
    match runner {
        Some(obj) => extract_runner(obj),
        None => Ok(Arc::new(JobRunner::new())),
    }
}

/// Resolve the requested concurrency, defaulting to the logical CPU count.
/// Rejects `0` explicitly: it used to be silently clamped to `1` (a confusing
/// "I asked for no concurrency and got some anyway"), which is worse than a
/// clear error, since `0` most likely means a caller-computed value (e.g. an
/// empty allowlist's length) that was never meant to reach here at all.
fn resolve_concurrency(concurrency: Option<usize>) -> PyResult<usize> {
    match concurrency {
        Some(0) => Err(PyValueError::new_err(
            "concurrency must be at least 1 (0 would run nothing, silently)",
        )),
        Some(n) => Ok(n),
        None => Ok(std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(4)),
    }
}

/// Clone the inner `Command`s out of the Python handles (under the GIL) so the
/// owned list can move into the async batch driver. `try_borrow`, not the
/// panicking `borrow`: a concurrent access to one of these `Command` handles
/// from another thread surfaces as a clean `PyErr`, not a `PanicException`
/// across the FFI boundary.
fn take_commands(py: Python<'_>, commands: &[Py<PyCommand>]) -> PyResult<Vec<processkit::Command>> {
    commands
        .iter()
        .map(|c| Ok(c.try_borrow(py)?.inner.clone()))
        .collect()
}

/// Turn the driver's per-command results into the Python result list, in input
/// order. `predicate_errors[i]` — the error command `i`'s injected
/// `ScriptedRunner.when` predicate raised (or `None`) — overrides that slot: a
/// broken match predicate surfaces in its own slot (the batch analogue of a
/// direct verb aborting) instead of the reply a fallthrough would have masked it
/// behind. `results` and `predicate_errors` are the same length and both in
/// input order (see [`WhenCaptureRunner`]).
fn string_results_to_pylist(
    py: Python<'_>,
    results: Vec<processkit::Result<PkProcessResult<String>>>,
    predicate_errors: Vec<Option<PyErr>>,
) -> PyResult<Vec<Py<PyAny>>> {
    results
        .into_iter()
        .zip(predicate_errors)
        .map(|(r, predicate_err)| match predicate_err {
            Some(err) => Ok(err.into_value(py).into_any()),
            None => match r {
                Ok(inner) => Ok(Py::new(py, PyProcessResult { inner })?.into_any()),
                Err(err) => Ok(map_err(err).into_value(py).into_any()),
            },
        })
        .collect()
}

fn bytes_results_to_pylist(
    py: Python<'_>,
    results: Vec<processkit::Result<PkProcessResult<Vec<u8>>>>,
    predicate_errors: Vec<Option<PyErr>>,
) -> PyResult<Vec<Py<PyAny>>> {
    results
        .into_iter()
        .zip(predicate_errors)
        .map(|(r, predicate_err)| match predicate_err {
            Some(err) => Ok(err.into_value(py).into_any()),
            None => match r {
                Ok(inner) => Ok(Py::new(py, PyBytesResult { inner })?.into_any()),
                Err(err) => Ok(map_err(err).into_value(py).into_any()),
            },
        })
        .collect()
}

/// Run every command, at most `concurrency` live at once (default: CPU count),
/// and return their `ProcessResult`s in input order. A spawn/I/O failure for a
/// command appears as a `ProcessError` instance in its slot.
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None, runner=None))]
pub(crate) fn output_all(
    py: Python<'_>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<usize>,
    runner: Option<&Bound<'_, PyAny>>,
) -> PyResult<Vec<Py<PyAny>>> {
    let cmds = take_commands(py, &commands)?;
    let n = resolve_concurrency(concurrency)?;
    // Wrap the runner so each command runs under its own `when`-predicate error
    // sink (see `WhenCaptureRunner`): a raising `when` predicate then surfaces in
    // that command's own result slot, like a direct verb aborting.
    let capture = WhenCaptureRunner::new(resolve_runner(runner)?, cmds.len());
    let fut = async { pk_output_all(cmds, n, &capture).await };
    let results = block_on_interruptible(py, fut)?;
    string_results_to_pylist(py, results, capture.take_errors())
}

/// Async counterpart of `output_all`.
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None, runner=None))]
pub(crate) fn aoutput_all<'py>(
    py: Python<'py>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<usize>,
    runner: Option<&Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyAny>> {
    let cmds = take_commands(py, &commands)?;
    let n = resolve_concurrency(concurrency)?;
    let runner = resolve_runner(runner)?;
    let count = cmds.len();
    drive_async_py(py, async move {
        let capture = WhenCaptureRunner::new(runner, count);
        let results = pk_output_all(cmds, n, &capture).await;
        let errors = capture.take_errors();
        Python::attach(|py| string_results_to_pylist(py, results, errors))
    })
}

/// Raw-bytes companion to `output_all` (`BytesResult` per command).
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None, runner=None))]
pub(crate) fn output_all_bytes(
    py: Python<'_>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<usize>,
    runner: Option<&Bound<'_, PyAny>>,
) -> PyResult<Vec<Py<PyAny>>> {
    let cmds = take_commands(py, &commands)?;
    let n = resolve_concurrency(concurrency)?;
    let capture = WhenCaptureRunner::new(resolve_runner(runner)?, cmds.len());
    let fut = async { pk_output_all_bytes(cmds, n, &capture).await };
    let results = block_on_interruptible(py, fut)?;
    bytes_results_to_pylist(py, results, capture.take_errors())
}

/// Async counterpart of `output_all_bytes`.
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None, runner=None))]
pub(crate) fn aoutput_all_bytes<'py>(
    py: Python<'py>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<usize>,
    runner: Option<&Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyAny>> {
    let cmds = take_commands(py, &commands)?;
    let n = resolve_concurrency(concurrency)?;
    let runner = resolve_runner(runner)?;
    let count = cmds.len();
    drive_async_py(py, async move {
        let capture = WhenCaptureRunner::new(runner, count);
        let results = pk_output_all_bytes(cmds, n, &capture).await;
        let errors = capture.take_errors();
        Python::attach(|py| bytes_results_to_pylist(py, results, errors))
    })
}

/// Register this module's functions (`output_all`, `aoutput_all`,
/// `output_all_bytes`, `aoutput_all_bytes`) on `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(pyo3::wrap_pyfunction!(output_all, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(aoutput_all, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(output_all_bytes, m)?)?;
    m.add_function(pyo3::wrap_pyfunction!(aoutput_all_bytes, m)?)?;
    Ok(())
}
