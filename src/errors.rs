//! The exception hierarchy and the crate-error -> Python-exception mapping.

use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyFileNotFoundError, PyTimeoutError};
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyDict, PyTuple, PyType};

// Exception hierarchy: a single `ProcessError` root with one subclass per
// failure mode the crate distinguishes.
create_exception!(_processkit, ProcessError, PyException);
create_exception!(_processkit, NonZeroExit, ProcessError);
create_exception!(_processkit, Cancelled, ProcessError);
create_exception!(_processkit, Signalled, ProcessError);
create_exception!(_processkit, ResourceLimit, ProcessError);
create_exception!(_processkit, Unsupported, ProcessError);
create_exception!(_processkit, OutputTooLarge, ProcessError);

// `Timeout` and `ProcessNotFound` carry a second, builtin base so they are
// catchable the way the stdlib trains Python users to expect: a command timeout
// is also a `TimeoutError` (as `asyncio.TimeoutError` has been since 3.11), and
// a missing program is also a `FileNotFoundError` (which is what `subprocess`
// raises). `create_exception!` takes only one base, so these two are built at
// module init with `type(name, (ProcessError, <builtin>), ...)` and cached here
// for `map_err` to instantiate.
static TIMEOUT: PyOnceLock<Py<PyType>> = PyOnceLock::new();
static PROCESS_NOT_FOUND: PyOnceLock<Py<PyType>> = PyOnceLock::new();

/// Build a `ProcessError` subclass that also inherits `native_base` (a builtin
/// exception), so `except <native_base>` catches it too — `type(name, bases, {})`.
fn make_dual_exception<'py>(
    py: Python<'py>,
    name: &str,
    native_base: Bound<'py, PyType>,
    doc: &str,
) -> PyResult<Bound<'py, PyType>> {
    let bases = PyTuple::new(py, [py.get_type::<ProcessError>(), native_base])?;
    let namespace = PyDict::new(py);
    namespace.set_item("__doc__", doc)?;
    namespace.set_item("__module__", "processkit")?;
    let class = py
        .import("builtins")?
        .getattr("type")?
        .call1((name, bases, namespace))?;
    Ok(class.cast_into::<PyType>()?)
}

/// Register the dual-base exceptions on the module and cache them for `map_err`.
pub(crate) fn init_dual_exceptions(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    let timeout = make_dual_exception(
        py,
        "Timeout",
        py.get_type::<PyTimeoutError>(),
        "A run exceeded its configured timeout. Also a builtin `TimeoutError`.",
    )?;
    let not_found = make_dual_exception(
        py,
        "ProcessNotFound",
        py.get_type::<PyFileNotFoundError>(),
        "The program could not be found / spawned. Also a `FileNotFoundError`.",
    )?;
    m.add("Timeout", &timeout)?;
    m.add("ProcessNotFound", &not_found)?;
    // First write wins; the module is initialized once per interpreter (abi3
    // extension-module), so the discarded-`Err` case is unreachable in practice.
    let _ = TIMEOUT.set(py, timeout.unbind());
    let _ = PROCESS_NOT_FOUND.set(py, not_found.unbind());
    Ok(())
}

fn timeout_type(py: Python<'_>) -> Bound<'_, PyType> {
    TIMEOUT
        .get(py)
        .expect("Timeout type initialized at module init")
        .bind(py)
        .clone()
}

fn process_not_found_type(py: Python<'_>) -> Bound<'_, PyType> {
    PROCESS_NOT_FOUND
        .get(py)
        .expect("ProcessNotFound type initialized at module init")
        .bind(py)
        .clone()
}

/// Map a crate `Error` onto the Python exception hierarchy and attach the
/// structured fields the variant carries (`code`, `stdout`, `stderr`,
/// `program`, `signal`, `timeout_seconds`, output-cap counters) so callers can
/// inspect a failure programmatically, not just read its message.
///
/// Self-attaching: it acquires the GIL itself (a cheap re-entrant no-op when one
/// is already held), so both the sync surface and the async futures can map an
/// error with a uniform `.map_err(map_err)` — no caller-threaded `py` token.
///
/// `Error` is `#[non_exhaustive]`, so the wildcard arm both covers the rarer
/// variants (`Io`, `Parse`, `Stdin`, `NotReady`, …) and stays
/// forward-compatible.
pub(crate) fn map_err(error: processkit::Error) -> PyErr {
    use processkit::Error as E;
    use std::io::ErrorKind;

    Python::attach(|py| {
        let message = error.to_string();
        let err = match &error {
            E::Timeout { .. } => PyErr::from_type(timeout_type(py), message),
            E::Cancelled { .. } => Cancelled::new_err(message),
            E::Exit { .. } => NonZeroExit::new_err(message),
            E::Signalled { .. } => Signalled::new_err(message),
            E::NotFound { .. } => PyErr::from_type(process_not_found_type(py), message),
            // The real spawn path reports a missing program as `Spawn` carrying
            // an `io::Error` of kind `NotFound`; surface that as
            // `ProcessNotFound` too.
            E::Spawn { source, .. } if source.kind() == ErrorKind::NotFound => {
                PyErr::from_type(process_not_found_type(py), message)
            }
            E::ResourceLimit { .. } => ResourceLimit::new_err(message),
            E::Unsupported { .. } => Unsupported::new_err(message),
            E::OutputTooLarge { .. } => OutputTooLarge::new_err(message),
            _ => ProcessError::new_err(message),
        };

        // Attach structured fields. `setattr` failures are ignored: the typed
        // exception with its message is already a faithful error.
        let value = err.value(py);
        match &error {
            E::Exit {
                code,
                program,
                stdout,
                stderr,
            } => {
                let _ = value.setattr("program", program.as_str());
                let _ = value.setattr("code", *code);
                let _ = value.setattr("stdout", stdout.as_str());
                let _ = value.setattr("stderr", stderr.as_str());
            }
            E::Signalled {
                program,
                signal,
                stdout,
                stderr,
            } => {
                let _ = value.setattr("program", program.as_str());
                let _ = value.setattr("signal", *signal);
                let _ = value.setattr("stdout", stdout.as_str());
                let _ = value.setattr("stderr", stderr.as_str());
            }
            E::Timeout {
                program,
                timeout,
                stdout,
                stderr,
            } => {
                let _ = value.setattr("program", program.as_str());
                let _ = value.setattr("timeout_seconds", timeout.as_secs_f64());
                let _ = value.setattr("stdout", stdout.as_str());
                let _ = value.setattr("stderr", stderr.as_str());
            }
            E::OutputTooLarge {
                program,
                line_limit,
                byte_limit,
                total_lines,
                total_bytes,
            } => {
                let _ = value.setattr("program", program.as_str());
                let _ = value.setattr("line_limit", *line_limit);
                let _ = value.setattr("byte_limit", *byte_limit);
                let _ = value.setattr("total_lines", *total_lines);
                let _ = value.setattr("total_bytes", *total_bytes);
            }
            E::NotFound { program, .. }
            | E::Spawn { program, .. }
            | E::Cancelled { program }
            | E::Stdin { program, .. } => {
                let _ = value.setattr("program", program.as_str());
            }
            _ => {}
        }
        err
    })
}
