//! Small converters from Python-facing strings / numbers to crate types.

use std::path::Path;
use std::time::Duration;

use processkit::prelude::Encoding;
use processkit::Error as PkError;
use processkit::OutputBufferPolicy;
use processkit::OverflowMode;
use processkit::RetryPolicy;
use processkit::Signal as PkSignal;
use processkit::StdioMode;
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

/// Open a file to receive a `stdout_tee`/`stderr_tee` line stream, converting it
/// into the crate-required async sink (`W: tokio::io::AsyncWrite + Send + Unpin +
/// 'static`, which `tokio::fs::File` satisfies).
///
/// The file is opened **now**, from the synchronous builder-method context — the
/// crate takes a concrete `W: AsyncWrite` on `stdout_tee()`, not a lazy factory
/// invoked at spawn, so there is no "open on run" hook to defer to. It is created
/// if absent; an existing file is **truncated** by default (`open(path, "w")`
/// semantics), or **appended** to when `append` is set (`"a"`). A path that can't
/// be opened for writing — a missing parent directory, a directory, a permission
/// denial — surfaces as the matching stdlib `OSError` subclass (PyO3 maps
/// `std::io::Error` for us: `FileNotFoundError`, `IsADirectoryError`,
/// `PermissionError`, …), not a panic.
///
/// `from_std` only wraps the already-open handle, so it needs no active runtime
/// and is safe to call from the sync builder; the actual line writes happen later
/// on the capture pump, dispatched to the managed runtime's blocking pool.
pub(crate) fn open_tee_sink(path: &Path, append: bool) -> PyResult<tokio::fs::File> {
    let std_file = std::fs::OpenOptions::new()
        .write(true)
        .create(true)
        // `truncate` and `append` are mutually exclusive here (exactly one is
        // true), so this never trips the platforms that reject truncate+append.
        .truncate(!append)
        .append(append)
        .open(path)?;
    Ok(tokio::fs::File::from_std(std_file))
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

/// Build an `OutputBufferPolicy` from an `output_limit(...)`-shaped set of
/// kwargs — shared by `Command.output_limit` and `Supervisor`'s
/// `capture_max_bytes=`/`capture_max_lines=`/`capture_on_overflow=`
/// constructor kwargs (the crate's `Supervisor.capture(policy)`, flattened to
/// kwargs like every other config-struct binding). Requires at least one of
/// `max_bytes`/`max_lines`: the crate itself treats an all-`None` policy
/// build as a confusing silent no-op, so this rejects it explicitly instead.
pub(crate) fn build_output_buffer_policy(
    max_bytes: Option<usize>,
    max_lines: Option<usize>,
    on_overflow: &str,
    what: &str,
) -> PyResult<OutputBufferPolicy> {
    if max_bytes.is_none() && max_lines.is_none() {
        return Err(PyValueError::new_err(format!(
            "{what} requires at least one of max_bytes or max_lines"
        )));
    }
    let overflow = parse_overflow_mode(on_overflow)?;
    let mut policy = match max_lines {
        Some(n) => OutputBufferPolicy::bounded(n),
        None => OutputBufferPolicy::unbounded(),
    };
    if let Some(bytes) = max_bytes {
        policy = policy.with_max_bytes(bytes);
    }
    Ok(policy.with_overflow(overflow))
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
fn parse_signal_name(name: &str) -> PyResult<PkSignal> {
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

/// Parse a signal argument that is either a portable name (see
/// `parse_signal_name`) or a raw platform signal number — the crate's
/// `Signal::Other(i32)` escape hatch, passed through verbatim (Unix only; a
/// raw number is `Unsupported` on Windows like every non-`Kill` signal). An
/// `int` (Python `bool` included, since `bool` is a Python `int` subtype) takes
/// this path; anything else is extracted as a name string.
pub(crate) fn parse_signal(obj: &Bound<'_, PyAny>) -> PyResult<PkSignal> {
    if let Ok(raw) = obj.extract::<i32>() {
        return Ok(PkSignal::Other(raw));
    }
    parse_signal_name(&obj.extract::<String>()?)
}

fn is_transient_classifier(error: &PkError) -> bool {
    error.is_transient()
}

fn is_transient_or_timeout_classifier(error: &PkError) -> bool {
    error.is_transient() || error.is_timeout()
}

/// Map a `retry_if` preset name to the crate's own documented error-classifier
/// composition (`Command::retry`'s doc example: `e.is_transient() ||
/// e.is_timeout()`). A named preset over the 1.2.0 accessors, not an arbitrary
/// Python callable: plain (non-capturing) `fn` pointers, not closures, so both
/// arms share one concrete return type and trivially satisfy `Fn(&Error) ->
/// bool + Send + Sync + 'static` with no boxing.
pub(crate) fn parse_retry_if(name: &str) -> PyResult<fn(&PkError) -> bool> {
    match name {
        "transient" => Ok(is_transient_classifier as fn(&PkError) -> bool),
        "transient_or_timeout" => Ok(is_transient_or_timeout_classifier as fn(&PkError) -> bool),
        other => Err(PyValueError::new_err(format!(
            "unknown retry_if {other:?}; use one of: transient, transient_or_timeout"
        ))),
    }
}

/// Build a `RetryPolicy` from the optional Python-facing tuning knobs, layered
/// over the crate's own `RetryPolicy::default()` (3 retries, 100ms initial
/// backoff, ×2 growth, 30s cap, jitter on) — the same defaults `Command.retry`
/// and `CliClient`'s `default_retry_if=` fall back to when a knob is omitted.
/// `multiplier` is passed through unvalidated: the crate itself already folds
/// a non-finite/non-positive/sub-unit value to `1.0` (fixed backoff) rather
/// than erroring, and duplicating stricter validation here would only create
/// a second, inconsistent notion of "invalid".
pub(crate) fn build_retry_policy(
    max_retries: Option<u32>,
    initial_backoff: Option<f64>,
    multiplier: Option<f64>,
    max_backoff: Option<f64>,
    jitter: Option<bool>,
) -> PyResult<RetryPolicy> {
    let mut policy = RetryPolicy::default();
    if let Some(retries) = max_retries {
        policy = policy.max_retries(retries);
    }
    if let Some(seconds) = initial_backoff {
        policy = policy.initial_backoff(nonnegative_duration(seconds, "initial_backoff")?);
    }
    if let Some(factor) = multiplier {
        policy = policy.multiplier(factor);
    }
    if let Some(seconds) = max_backoff {
        policy = policy.max_backoff(nonnegative_duration(seconds, "max_backoff")?);
    }
    if let Some(enabled) = jitter {
        policy = policy.jitter(enabled);
    }
    Ok(policy)
}
