//! Small converters from Python-facing strings / numbers to crate types.

use std::time::Duration;

use processkit::RestartPolicy;
use processkit::Signal as PkSignal;
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
