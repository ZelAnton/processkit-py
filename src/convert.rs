//! Small converters from Python-facing strings / numbers to crate types.

use std::time::Duration;

use processkit::Encoding;
use processkit::OverflowMode;
use processkit::RestartPolicy;
use processkit::Signal as PkSignal;
use processkit::StdioMode;
use processkit::StopReason;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Validate and convert a positive number of seconds into a `Duration`.
pub(crate) fn positive_duration(seconds: f64, what: &str) -> PyResult<Duration> {
    if !seconds.is_finite() || seconds <= 0.0 {
        return Err(PyValueError::new_err(format!(
            "{what} must be a positive, finite number of seconds"
        )));
    }
    // `try_from_secs_f64` (not `from_secs_f64`) so a finite-but-huge value that
    // overflows `Duration` is a clean error, not a Rust panic.
    Duration::try_from_secs_f64(seconds)
        .map_err(|err| PyValueError::new_err(format!("invalid {what}: {err}")))
}

/// Validate and convert a non-negative number of seconds into a `Duration`
/// (`0` is allowed — e.g. a zero grace window means "kill immediately").
pub(crate) fn nonnegative_duration(seconds: f64, what: &str) -> PyResult<Duration> {
    if !seconds.is_finite() || seconds < 0.0 {
        return Err(PyValueError::new_err(format!(
            "{what} must be a non-negative, finite number of seconds"
        )));
    }
    Duration::try_from_secs_f64(seconds)
        .map_err(|err| PyValueError::new_err(format!("invalid {what}: {err}")))
}

/// Parse a restart policy name into a crate `RestartPolicy`.
pub(crate) fn parse_restart_policy(name: &str) -> PyResult<RestartPolicy> {
    match name.to_ascii_lowercase().as_str() {
        "always" => Ok(RestartPolicy::Always),
        "never" => Ok(RestartPolicy::Never),
        "on_crash" | "on-crash" | "oncrash" => Ok(RestartPolicy::OnCrash),
        _ => Err(PyValueError::new_err(format!(
            "unknown restart policy {name:?}; use one of: always, never, on_crash"
        ))),
    }
}

/// Render a `StopReason` as a stable lowercase string.
pub(crate) fn stop_reason_str(reason: StopReason) -> &'static str {
    match reason {
        StopReason::PolicySatisfied => "policy_satisfied",
        StopReason::Predicate => "predicate",
        StopReason::RestartsExhausted => "restarts_exhausted",
        _ => "unknown",
    }
}

/// Map a Python stdio-mode label to the crate `StdioMode`.
pub(crate) fn parse_stdio_mode(mode: &str) -> PyResult<StdioMode> {
    match mode {
        "pipe" | "piped" => Ok(StdioMode::Piped),
        "inherit" => Ok(StdioMode::Inherit),
        "null" | "discard" => Ok(StdioMode::Null),
        other => Err(PyValueError::new_err(format!(
            "unknown stdio mode {other:?}; use one of: pipe, inherit, null"
        ))),
    }
}

/// Map an `output_limit(on_overflow=...)` label to the crate `OverflowMode`.
pub(crate) fn parse_overflow_mode(on_overflow: &str) -> PyResult<OverflowMode> {
    match on_overflow {
        "drop_oldest" => Ok(OverflowMode::DropOldest),
        "drop_newest" => Ok(OverflowMode::DropNewest),
        "error" => Ok(OverflowMode::Error),
        other => Err(PyValueError::new_err(format!(
            "unknown on_overflow {other:?}; use one of: drop_oldest, drop_newest, error"
        ))),
    }
}

/// Resolve a label to an `Encoding`, accepting both WHATWG labels and the common
/// Python codec aliases (e.g. `"latin_1"`, `"utf_8"`, `"euc_jp"`) that the WHATWG
/// table doesn't spell the same way.
fn resolve_encoding(label: &str) -> Option<&'static Encoding> {
    // The WHATWG label table (encoding_rs) already accepts a lot — `utf-8`,
    // `windows-1252`, `cp1251`, `shift_jis`, `latin1`, `iso-8859-1`, … — and
    // matches case-insensitively. Try it verbatim first.
    if let Some(encoding) = Encoding::for_label(label.as_bytes()) {
        return Some(encoding);
    }
    // Fall back to common Python codec aliases the table doesn't contain.
    let lower = label.trim().to_ascii_lowercase();
    match lower.as_str() {
        // WHATWG's `iso-8859-1` *is* windows-1252; map the Python latin-1 family
        // (which the table only accepts as `latin1`) to it.
        "latin" | "latin-1" | "latin_1" => Encoding::for_label(b"iso-8859-1"),
        // Python spells many labels with `_` where WHATWG uses `-`
        // (`utf_8`->`utf-8`, `euc_jp`->`euc-jp`, `utf_16`->`utf-16le`, …).
        other => Encoding::for_label(other.replace('_', "-").as_bytes()),
    }
}

/// Resolve an encoding label (e.g. `"iso-8859-1"`, `"shift_jis"`, `"latin_1"`) to
/// an `Encoding`, raising `ValueError` with guidance when it can't be mapped.
pub(crate) fn parse_encoding(label: &str) -> PyResult<&'static Encoding> {
    resolve_encoding(label).ok_or_else(|| {
        PyValueError::new_err(format!(
            "unknown encoding label {label:?}. Labels follow the WHATWG Encoding \
             Standard — e.g. \"utf-8\", \"iso-8859-1\", \"windows-1252\", \
             \"windows-1251\", \"shift_jis\". Common Python codec aliases \
             (\"latin_1\", \"utf_8\", \"euc_jp\") are accepted too; the Windows ANSI \
             code page (\"mbcs\"/\"ansi\") has no portable label — pass it explicitly, \
             e.g. \"windows-1251\"."
        ))
    })
}

/// Parse a signal name (`"term"`, `"kill"`, `"int"`, `"hup"`, `"quit"`,
/// `"usr1"`, `"usr2"`; a `"sig"` prefix is accepted) into a crate `Signal`.
pub(crate) fn parse_signal(name: &str) -> PyResult<PkSignal> {
    let key = name.to_ascii_lowercase();
    let key = key.strip_prefix("sig").unwrap_or(&key);
    match key {
        "term" => Ok(PkSignal::Term),
        "kill" => Ok(PkSignal::Kill),
        "int" => Ok(PkSignal::Int),
        "hup" => Ok(PkSignal::Hup),
        "quit" => Ok(PkSignal::Quit),
        "usr1" => Ok(PkSignal::Usr1),
        "usr2" => Ok(PkSignal::Usr2),
        _ => Err(PyValueError::new_err(format!(
            "unknown signal {name:?}; use one of: term, kill, int, hup, quit, usr1, usr2"
        ))),
    }
}
