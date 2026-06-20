//! Module-level batch execution: run many `Command`s with bounded concurrency.
//!
//! Each result slot is a `ProcessResult` (a non-zero exit is data on it) or, for
//! a command that failed (a spawn or I/O error), the corresponding
//! `ProcessError` instance — mirroring the crate's per-command `Result`. The
//! batch never short-circuits.

use processkit::output_all as pk_output_all;
use processkit::output_all_bytes as pk_output_all_bytes;
use processkit::JobRunner;
use processkit::ProcessResult as PkProcessResult;
use pyo3::prelude::*;

use crate::command::PyCommand;
use crate::errors::map_err;
use crate::result::{PyBytesResult, PyProcessResult};
use crate::runtime::block_on_interruptible;

/// Clamp the requested concurrency, defaulting to the logical CPU count.
fn resolve_concurrency(concurrency: Option<usize>) -> usize {
    concurrency
        .unwrap_or_else(|| {
            std::thread::available_parallelism()
                .map(|n| n.get())
                .unwrap_or(4)
        })
        .max(1)
}

/// Clone the inner `Command`s out of the Python handles (under the GIL) so the
/// owned list can move into the async batch driver.
fn take_commands(py: Python<'_>, commands: &[Py<PyCommand>]) -> Vec<processkit::Command> {
    commands
        .iter()
        .map(|c| c.borrow(py).inner.clone())
        .collect()
}

fn string_results_to_pylist(
    py: Python<'_>,
    results: Vec<processkit::Result<PkProcessResult<String>>>,
) -> PyResult<Vec<Py<PyAny>>> {
    results
        .into_iter()
        .map(|r| match r {
            Ok(inner) => Ok(Py::new(py, PyProcessResult { inner })?.into_any()),
            Err(err) => Ok(map_err(err).into_value(py).into_any()),
        })
        .collect()
}

fn bytes_results_to_pylist(
    py: Python<'_>,
    results: Vec<processkit::Result<PkProcessResult<Vec<u8>>>>,
) -> PyResult<Vec<Py<PyAny>>> {
    results
        .into_iter()
        .map(|r| match r {
            Ok(inner) => Ok(Py::new(py, PyBytesResult { inner })?.into_any()),
            Err(err) => Ok(map_err(err).into_value(py).into_any()),
        })
        .collect()
}

/// Run every command, at most `concurrency` live at once (default: CPU count),
/// and return their `ProcessResult`s in input order. A spawn/I/O failure for a
/// command appears as a `ProcessError` instance in its slot.
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None))]
pub(crate) fn output_all(
    py: Python<'_>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<usize>,
) -> PyResult<Vec<Py<PyAny>>> {
    let cmds = take_commands(py, &commands);
    let n = resolve_concurrency(concurrency);
    let results = block_on_interruptible(py, async move {
        let runner = JobRunner::new();
        pk_output_all(cmds, n, &runner).await
    })?;
    string_results_to_pylist(py, results)
}

/// Async counterpart of `output_all`.
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None))]
pub(crate) fn aoutput_all<'py>(
    py: Python<'py>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    let cmds = take_commands(py, &commands);
    let n = resolve_concurrency(concurrency);
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let runner = JobRunner::new();
        let results = pk_output_all(cmds, n, &runner).await;
        Python::attach(|py| string_results_to_pylist(py, results))
    })
}

/// Raw-bytes companion to `output_all` (`BytesResult` per command).
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None))]
pub(crate) fn output_all_bytes(
    py: Python<'_>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<usize>,
) -> PyResult<Vec<Py<PyAny>>> {
    let cmds = take_commands(py, &commands);
    let n = resolve_concurrency(concurrency);
    let results = block_on_interruptible(py, async move {
        let runner = JobRunner::new();
        pk_output_all_bytes(cmds, n, &runner).await
    })?;
    bytes_results_to_pylist(py, results)
}

/// Async counterpart of `output_all_bytes`.
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None))]
pub(crate) fn aoutput_all_bytes<'py>(
    py: Python<'py>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    let cmds = take_commands(py, &commands);
    let n = resolve_concurrency(concurrency);
    pyo3_async_runtimes::tokio::future_into_py(py, async move {
        let runner = JobRunner::new();
        let results = pk_output_all_bytes(cmds, n, &runner).await;
        Python::attach(|py| bytes_results_to_pylist(py, results))
    })
}
