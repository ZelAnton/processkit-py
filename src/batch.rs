//! Module-level batch execution: run many `Command`s with bounded concurrency.
//!
//! Each result slot is a `ProcessResult` (a non-zero exit is data on it) or, for
//! a command that failed (a spawn or I/O error), the corresponding
//! `ProcessError` instance — mirroring the crate's per-command `Result`. The
//! batch never short-circuits.

use std::sync::Arc;

use processkit::prelude::StreamExt;
// The *streaming* fan-out (`output_stream`), not the buffering `output_all`, is
// what this binding drives: it is the same engine with the same bounded
// concurrency, no-short-circuit and cancellation semantics (since crate 3.0.0
// `output_all` is literally this stream collected in order), but each completion
// arrives tagged with its **input index**. That index is what pairs a command's
// result with the `when`-predicate error its own run recorded — see
// [`WhenCaptureRunner`] for why a positional counter cannot do that job any more.
use processkit::output_stream as pk_output_stream;
use processkit::output_stream_bytes as pk_output_stream_bytes;
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

/// Resolve the requested concurrency, defaulting to the process-available CPU
/// count (`available_parallelism`, which honors CPU affinity and cgroup quotas
/// where the platform supports them). If the operating system cannot report it,
/// use the shared fallback of `4`. Reject non-positive values explicitly: they
/// must raise the same `ValueError` as the pure-Python streaming batch helpers,
/// rather than a PyO3 `usize` conversion error or a silent clamp to `1`.
fn resolve_concurrency(concurrency: Option<i64>) -> PyResult<usize> {
    match concurrency {
        Some(n) if n < 1 => Err(PyValueError::new_err(
            "concurrency must be a positive integer",
        )),
        Some(n) => usize::try_from(n)
            .map_err(|_| PyValueError::new_err("concurrency must be a positive integer")),
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

/// One command's outcome as the fan-out reported it: either the error its
/// injected `ScriptedRunner.when` predicate raised, or the crate's own
/// per-command `Result`. A broken match predicate takes precedence and surfaces
/// in its own slot (the batch analogue of a direct verb aborting) instead of the
/// reply a fallthrough would have masked it behind.
enum Slot<T> {
    PredicateError(PyErr),
    Result(processkit::Result<PkProcessResult<T>>),
}

/// Drive the fan-out to exhaustion, routing each completion into its **input**
/// slot and pairing it with the predicate error that command's own run recorded.
///
/// `capture.take_completed_error()` is called immediately after each item, while
/// that item's verb future is the one that just resolved — the pairing
/// [`WhenCaptureRunner`] documents. This is also where the crate's own
/// `collect_in_order` reassembly lives for this binding: same routing (`slots[idx]`
/// keyed on the input index), just carrying the extra per-command error alongside.
///
/// The stream is bound through `processkit::prelude::StreamExt` (which the crate
/// re-exports precisely so a consumer needs no direct `tokio-stream`/`futures`
/// dependency of its own) rather than by naming `Stream`, keeping this binding's
/// dependency set unchanged.
async fn collect_in_input_order<T, S>(
    stream: S,
    capture: &WhenCaptureRunner,
    total: usize,
) -> Vec<Slot<T>>
where
    S: StreamExt<Item = (usize, processkit::Result<PkProcessResult<T>>)>,
{
    let mut slots: Vec<Option<Slot<T>>> = (0..total).map(|_| None).collect();
    let mut stream = std::pin::pin!(stream);
    while let Some((idx, result)) = stream.next().await {
        let slot = match capture.take_completed_error() {
            Some(err) => Slot::PredicateError(err),
            None => Slot::Result(result),
        };
        if let Some(cell) = slots.get_mut(idx) {
            *cell = Some(slot);
        }
    }
    slots
        .into_iter()
        .map(|slot| {
            slot.unwrap_or_else(|| {
                // Unreachable: the fan-out fills every input slot before it ends.
                // Reported as data rather than panicking across the FFI boundary.
                Slot::PredicateError(PyValueError::new_err(
                    "the batch driver ended without reporting this command",
                ))
            })
        })
        .collect()
}

/// Turn the driver's per-command slots into the Python result list, in input order.
fn string_results_to_pylist(py: Python<'_>, slots: Vec<Slot<String>>) -> PyResult<Vec<Py<PyAny>>> {
    slots
        .into_iter()
        .map(|slot| match slot {
            Slot::PredicateError(err) => Ok(err.into_value(py).into_any()),
            Slot::Result(Ok(inner)) => Ok(Py::new(py, PyProcessResult { inner })?.into_any()),
            Slot::Result(Err(err)) => Ok(map_err(err).into_value(py).into_any()),
        })
        .collect()
}

fn bytes_results_to_pylist(py: Python<'_>, slots: Vec<Slot<Vec<u8>>>) -> PyResult<Vec<Py<PyAny>>> {
    slots
        .into_iter()
        .map(|slot| match slot {
            Slot::PredicateError(err) => Ok(err.into_value(py).into_any()),
            Slot::Result(Ok(inner)) => Ok(Py::new(py, PyBytesResult { inner })?.into_any()),
            Slot::Result(Err(err)) => Ok(map_err(err).into_value(py).into_any()),
        })
        .collect()
}

/// Run every command, at most `concurrency` live at once (default:
/// process-available CPU count, with a fallback of `4`), and return their
/// `ProcessResult`s in input order. A spawn/I/O failure for a command appears as
/// a `ProcessError` instance in its slot. A non-positive `concurrency` raises
/// `ValueError`.
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None, runner=None))]
pub(crate) fn output_all(
    py: Python<'_>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<i64>,
    runner: Option<&Bound<'_, PyAny>>,
) -> PyResult<Vec<Py<PyAny>>> {
    let cmds = take_commands(py, &commands)?;
    let n = resolve_concurrency(concurrency)?;
    let total = cmds.len();
    // Wrap the runner so each command runs under its own `when`-predicate error
    // sink (see `WhenCaptureRunner`): a raising `when` predicate then surfaces in
    // that command's own result slot, like a direct verb aborting.
    let capture = WhenCaptureRunner::new(resolve_runner(runner)?);
    let fut = async {
        collect_in_input_order(pk_output_stream(cmds, n, &capture), &capture, total).await
    };
    let slots = block_on_interruptible(py, fut)?;
    string_results_to_pylist(py, slots)
}

/// Async counterpart of `output_all`, including its process-available default,
/// fallback of `4`, and `ValueError` for a non-positive `concurrency`.
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None, runner=None))]
pub(crate) fn aoutput_all<'py>(
    py: Python<'py>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<i64>,
    runner: Option<&Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyAny>> {
    let cmds = take_commands(py, &commands)?;
    let n = resolve_concurrency(concurrency)?;
    let runner = resolve_runner(runner)?;
    let total = cmds.len();
    drive_async_py(py, async move {
        let capture = WhenCaptureRunner::new(runner);
        let slots =
            collect_in_input_order(pk_output_stream(cmds, n, &capture), &capture, total).await;
        Python::attach(|py| string_results_to_pylist(py, slots))
    })
}

/// Raw-bytes companion to `output_all` (`BytesResult` per command), with the
/// same process-available default, fallback of `4`, and validation.
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None, runner=None))]
pub(crate) fn output_all_bytes(
    py: Python<'_>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<i64>,
    runner: Option<&Bound<'_, PyAny>>,
) -> PyResult<Vec<Py<PyAny>>> {
    let cmds = take_commands(py, &commands)?;
    let n = resolve_concurrency(concurrency)?;
    let total = cmds.len();
    let capture = WhenCaptureRunner::new(resolve_runner(runner)?);
    let fut = async {
        collect_in_input_order(pk_output_stream_bytes(cmds, n, &capture), &capture, total).await
    };
    let slots = block_on_interruptible(py, fut)?;
    bytes_results_to_pylist(py, slots)
}

/// Async counterpart of `output_all_bytes`, including its process-available
/// default, fallback of `4`, and `ValueError` for a non-positive `concurrency`.
#[pyfunction]
#[pyo3(signature = (commands, *, concurrency=None, runner=None))]
pub(crate) fn aoutput_all_bytes<'py>(
    py: Python<'py>,
    commands: Vec<Py<PyCommand>>,
    concurrency: Option<i64>,
    runner: Option<&Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyAny>> {
    let cmds = take_commands(py, &commands)?;
    let n = resolve_concurrency(concurrency)?;
    let runner = resolve_runner(runner)?;
    let total = cmds.len();
    drive_async_py(py, async move {
        let capture = WhenCaptureRunner::new(runner);
        let slots =
            collect_in_input_order(pk_output_stream_bytes(cmds, n, &capture), &capture, total)
                .await;
        Python::attach(|py| bytes_results_to_pylist(py, slots))
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
