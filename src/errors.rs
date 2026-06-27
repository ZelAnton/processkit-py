//! The exception hierarchy and the crate-error -> Python-exception mapping.
//!
//! Decision (2026-07, deep-audit Stage 4 / D5): keep the hierarchy defined
//! here in Rust rather than moving it to a pure-Python `_errors.py` sidecar.
//! B1 (Stage 2) already shrank the ceremony this module needs — `map_err`'s
//! field attachment is now accessor-driven and variant-generic instead of
//! hand-matching every crate error variant — so the sidecar's main promised
//! win (less boilerplate) is smaller than it would have been pre-B1. What
//! remains (`create_exception!` for the 6 single-base exceptions, the
//! `PyOnceLock`-cached dual-base trio below) is a one-time, module-init-only
//! cost, not something touched per raised error. A sidecar would also add a
//! Python-side import + attribute lookup + call to CONSTRUCT every exception
//! (`map_err` currently builds them directly in Rust), a real per-error-path
//! cost for no functional gain, on a hierarchy that is public, exception-
//! catching surface (already shipped in the released `v1.0.0`) — not the
//! place to trade correctness risk for stylistic cleanup right now. Revisit
//! only if the ceremony grows again (e.g. a 4th dual-base exception) enough
//! to outweigh this.

use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyFileNotFoundError, PyPermissionError, PyTimeoutError};
use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::types::{PyDict, PyTuple, PyType};

// Exception hierarchy: a single `ProcessError` root with one subclass per
// failure mode the crate distinguishes.
create_exception!(_processkit, ProcessError, PyException);
create_exception!(_processkit, NonZeroExit, ProcessError);
create_exception!(_processkit, Signalled, ProcessError);
create_exception!(_processkit, ResourceLimit, ProcessError);
create_exception!(_processkit, Unsupported, ProcessError);
create_exception!(_processkit, OutputTooLarge, ProcessError);
create_exception!(_processkit, Cancelled, ProcessError);

// `Timeout` and `ProcessNotFound` carry a second, builtin base so they are
// catchable the way the stdlib trains Python users to expect: a command timeout
// is also a `TimeoutError` (as `asyncio.TimeoutError` has been since 3.11), and
// a missing program is also a `FileNotFoundError` (which is what `subprocess`
// raises). `create_exception!` takes only one base, so these two are built at
// module init with `type(name, (ProcessError, <builtin>), ...)` and cached here
// for `map_err` to instantiate.
static TIMEOUT: PyOnceLock<Py<PyType>> = PyOnceLock::new();
static PROCESS_NOT_FOUND: PyOnceLock<Py<PyType>> = PyOnceLock::new();
static PERMISSION_DENIED: PyOnceLock<Py<PyType>> = PyOnceLock::new();

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

/// Register every exception (single-base and dual-base) on `_processkit`.
///
/// Single-base exceptions get their `__module__` normalized to the public
/// package so reprs/tracebacks read `processkit.X` rather than leaking the
/// private `_processkit` extension name (the dual-base ones set it at
/// construction; the pyclasses set `module = "processkit"` themselves, except
/// the testing doubles which set `module = "processkit.testing"`).
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    for (name, ty) in [
        ("ProcessError", py.get_type::<ProcessError>()),
        ("NonZeroExit", py.get_type::<NonZeroExit>()),
        ("Signalled", py.get_type::<Signalled>()),
        ("ResourceLimit", py.get_type::<ResourceLimit>()),
        ("Unsupported", py.get_type::<Unsupported>()),
        ("OutputTooLarge", py.get_type::<OutputTooLarge>()),
        ("Cancelled", py.get_type::<Cancelled>()),
    ] {
        ty.setattr("__module__", "processkit")?;
        m.add(name, ty)?;
    }
    // `Timeout`, `ProcessNotFound`, and `PermissionDenied` are dual-base (also
    // `TimeoutError` / `FileNotFoundError` / `PermissionError`); built and
    // registered here.
    init_dual_exceptions(m)
}

/// Build the dual-base exceptions and cache them for `map_err`.
fn init_dual_exceptions(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    let timeout = make_dual_exception(
        py,
        "Timeout",
        py.get_type::<PyTimeoutError>(),
        "A run exceeded its configured timeout. Also a builtin `TimeoutError`.",
    )?;
    // Class-level default: `map_err` skips the instance `setattr` when the
    // deadline is unknown (`Duration::ZERO`), so without this the attribute
    // would be missing entirely (`AttributeError`) instead of reading `None`.
    timeout.setattr("timeout_seconds", py.None())?;
    let not_found = make_dual_exception(
        py,
        "ProcessNotFound",
        py.get_type::<PyFileNotFoundError>(),
        "The program could not be found / spawned. Also a `FileNotFoundError`.",
    )?;
    let permission_denied = make_dual_exception(
        py,
        "PermissionDenied",
        py.get_type::<PyPermissionError>(),
        "The program could not be spawned because of insufficient permissions \
         (e.g. a non-executable file). Also a `PermissionError`.",
    )?;
    // Class-level default, mirroring `timeout_seconds` above: `program()`
    // returns `None` for the broader `Io`-sourced permission denial (no
    // program is named there), so `map_err`'s instance `setattr` is skipped
    // on that path. Without this, `.program` would be missing entirely
    // (`AttributeError`) instead of reading `None`, contradicting the stub's
    // `program: str | None`.
    permission_denied.setattr("program", py.None())?;
    m.add("Timeout", &timeout)?;
    m.add("ProcessNotFound", &not_found)?;
    m.add("PermissionDenied", &permission_denied)?;
    // First write wins; the module is initialized once per interpreter (abi3
    // extension-module), so the discarded-`Err` case is unreachable in practice.
    let _ = TIMEOUT.set(py, timeout.unbind());
    let _ = PROCESS_NOT_FOUND.set(py, not_found.unbind());
    let _ = PERMISSION_DENIED.set(py, permission_denied.unbind());
    Ok(())
}

/// Fetch a dual-base exception type cached at module init. The `expect` is
/// unreachable in practice: the module is initialized once per interpreter
/// before any `map_err` can run.
fn cached<'py>(lock: &PyOnceLock<Py<PyType>>, py: Python<'py>) -> Bound<'py, PyType> {
    lock.get(py)
        .expect("dual-base exception initialized at module init")
        .bind(py)
        .clone()
}

/// Map a crate `Error` onto the Python exception hierarchy and attach the
/// structured fields the variant carries (`code`, `stdout`, `stderr`,
/// `program`, `signal`, `timeout_seconds`, `diagnostic`, output-cap counters)
/// so callers can inspect a failure programmatically, not just read its
/// message.
///
/// Self-attaching: it acquires the GIL itself (a cheap re-entrant no-op when one
/// is already held), so both the sync surface and the async futures can map an
/// error with a uniform `.map_err(map_err)` — no caller-threaded `py` token.
///
/// Since crate 1.2.0, exception-type selection and field attachment are driven
/// by `Error`'s own accessors (`program()`/`stdout()`/`stderr()`/`code()`/
/// `signal()`/`is_timeout()`/`is_not_found()`/`is_permission_denied()`) instead
/// of hand-destructuring every `#[non_exhaustive]` variant — new variants (or
/// new stream-bearing/program-naming ones) are covered automatically as the
/// crate extends its accessors, rather than silently missing a field. Only the
/// handful of things with no accessor (`Timeout.timeout`'s `Duration`,
/// `OutputTooLarge`'s counters, `Unsupported.operation`) still need a direct
/// match on the variant.
pub(crate) fn map_err(error: processkit::Error) -> PyErr {
    use processkit::Error as E;

    Python::attach(|py| {
        let message = error.to_string();
        let err = if error.is_timeout() {
            PyErr::from_type(cached(&TIMEOUT, py), message)
        } else if error.is_not_found() {
            // A genuine missing program is *always* `is_not_found()` (the crate
            // funnels every program-not-found case into `E::NotFound`). A `Spawn`
            // carrying `io::ErrorKind::NotFound` is therefore NOT a missing program
            // — it's a bad `cwd` or a file that's on `PATH` but not directly
            // executable (a Windows `.cmd`/`.bat` needing `cmd.exe`) — `is_not_found`
            // correctly excludes it, so it falls through to the generic
            // `ProcessError` below rather than misleading an
            // `except FileNotFoundError` fallback.
            PyErr::from_type(cached(&PROCESS_NOT_FOUND, py), message)
        } else if error.is_permission_denied() {
            // `is_permission_denied()` is broader than the old hand-matched arm
            // (`Spawn` carrying `PermissionDenied` only): it also covers `Io`
            // carrying `PermissionDenied` (e.g. a group signal the OS refused).
            // Decided: upgrade every such case to `PermissionDenied` for stdlib
            // parity (`except PermissionError` should catch all of them, not just
            // the spawn-time subset) — there is no case where the broader
            // classification would mislead a caller.
            PyErr::from_type(cached(&PERMISSION_DENIED, py), message)
        } else {
            match &error {
                E::Exit { .. } => NonZeroExit::new_err(message),
                E::Signalled { .. } => Signalled::new_err(message),
                E::ResourceLimit { .. } => ResourceLimit::new_err(message),
                E::Unsupported { .. } => Unsupported::new_err(message),
                E::OutputTooLarge { .. } => OutputTooLarge::new_err(message),
                E::Cancelled { .. } => Cancelled::new_err(message),
                _ => ProcessError::new_err(message),
            }
        };

        // Attach structured fields via the accessors — variant-generic, so a
        // `Cancelled` error (previously omitted from the hand-matched
        // program-attaching arm) now gets `.program` for free, like every other
        // program-naming variant. `setattr` failures are ignored: the typed
        // exception with its message is already a faithful error.
        let value = err.value(py);
        if let Some(program) = error.program() {
            let _ = value.setattr("program", program);
        }
        if let Some(code) = error.code() {
            let _ = value.setattr("code", code);
        }
        if let Some(stdout) = error.stdout() {
            let _ = value.setattr("stdout", stdout);
        }
        if let Some(stderr) = error.stderr() {
            let _ = value.setattr("stderr", stderr);
        }

        // The handful of fields with no `Error` accessor still need a direct match.
        match &error {
            E::Signalled { signal, .. } => {
                // Unlike `program`/`stdout`/`stderr`/`code` (attached above via the
                // accessor block, `if let Some(...)`), `signal` must be set
                // UNCONDITIONALLY here: `error.signal()` returns `None` both when
                // this isn't a `Signalled` and when it IS one but the kernel/double
                // didn't report a number (a real Unix signal-kill can do this, and
                // `Reply.signalled()` with no argument always does) — the stub
                // promises `Signalled.signal: int | None` is always present, so a
                // conditional `setattr` would leave it missing (`AttributeError`)
                // for exactly that no-number case instead of reading `None`.
                let _ = value.setattr("signal", *signal);
                // Same reasoning for `diagnostic`: like `signal`, `error.diagnostic()`
                // is `None` both for a variant that carries no streams AND for a
                // stream-bearing one whose streams both happen to be blank — the stub
                // promises `diagnostic: str | None` is always present on the three
                // stream-bearing classes, so this must be unconditional too, not
                // folded into the generic `if let Some(...)` accessor block above.
                let _ = value.setattr("diagnostic", error.diagnostic());
            }
            E::Timeout { timeout, .. } => {
                // A zero `Duration` means the deadline wasn't known to the checking
                // verb (a scripted/cassette-replayed timeout with no `timeout()`
                // configured) — leave the attribute unset (reads `None`) rather than
                // reporting a misleading literal `0.0`.
                if !timeout.is_zero() {
                    let _ = value.setattr("timeout_seconds", timeout.as_secs_f64());
                }
                let _ = value.setattr("diagnostic", error.diagnostic());
            }
            E::Exit { .. } => {
                let _ = value.setattr("diagnostic", error.diagnostic());
            }
            E::OutputTooLarge {
                line_limit,
                byte_limit,
                total_lines,
                total_bytes,
                ..
            } => {
                // Python attr names mirror the `output_limit(max_bytes=, max_lines=)`
                // builder kwargs (the crate's struct fields are *_limit).
                let _ = value.setattr("max_lines", *line_limit);
                let _ = value.setattr("max_bytes", *byte_limit);
                let _ = value.setattr("total_lines", *total_lines);
                let _ = value.setattr("total_bytes", *total_bytes);
            }
            E::Unsupported { operation } => {
                let _ = value.setattr("operation", operation.as_str());
            }
            // Every other variant's fields are already covered by the accessor
            // block above, or (like `ResourceLimit`) carries no structured field
            // beyond its message (already available via `str(exc)`).
            _ => {}
        }
        err
    })
}
