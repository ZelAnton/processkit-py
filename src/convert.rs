//! Small converters from Python-facing strings / numbers to crate types.

use std::future::Future;
use std::io;
use std::path::Path;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Duration;

use processkit::prelude::Encoding;
use processkit::Error as PkError;
use processkit::LineTerminator;
use processkit::OutputBufferPolicy;
use processkit::OverflowMode;
use processkit::Priority;
use processkit::RetryPolicy;
use processkit::Signal as PkSignal;
use processkit::StdioMode;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBool;
use tokio::io::AsyncWrite;
use tokio::task::{JoinError, JoinHandle};

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

/// Decide whether a `stdout_tee`/`stderr_tee` argument is a **Python writer**
/// object (dispatch it to [`PyWriterSink`]) or a **file path** (fall through to
/// [`open_tee_sink`]). A writer is anything exposing a callable `write`
/// attribute — an open file, `io.StringIO`, `sys.stderr`, a logger wrapper. The
/// discriminator is safe because neither of the path forms carries one: `str`
/// has no `write`, and `pathlib.Path` names its writers `write_text`/
/// `write_bytes`, never a bare `write`. Anything that is neither a writer nor a
/// path-like (e.g. an `int`) falls to the `open_tee_sink` branch, where the
/// `PathBuf` extraction raises the usual `TypeError`.
pub(crate) fn is_python_writer(sink: &Bound<'_, PyAny>) -> PyResult<bool> {
    match sink.getattr("write") {
        Ok(write) => Ok(write.is_callable()),
        // No `write` attribute at all → treat as a path. Only `AttributeError`
        // means "no such attribute"; anything else (a raising property,
        // `__getattr__` misbehaving, …) is a real error and must propagate
        // instead of being silently reinterpreted as "this is a path".
        Err(err) if err.is_instance_of::<pyo3::exceptions::PyAttributeError>(sink.py()) => {
            Ok(false)
        }
        Err(err) => Err(err),
    }
}

/// A `tokio::io::AsyncWrite` sink that mirrors the decoded line stream of
/// `stdout_tee`/`stderr_tee` into a caller-supplied Python object's `write()`
/// method — an `io.StringIO`, `sys.stderr`, an open text file, a logger wrapper.
///
/// **Why a bridge is needed.** The crate's `Command::stdout_tee<W: AsyncWrite +
/// Send + Unpin>` awaits each write **on the capture pump** (that await is the
/// backpressure point: a slow sink slows the pump, fills the OS pipe, and makes
/// the child block on its next write, rather than stalling the runtime). A
/// Python `write()` needs the GIL and may block arbitrarily long (a real file, a
/// socket, a logging handler), so calling it *inline on the pump task* would
/// pin a runtime worker for the duration and re-couple the async loop to the
/// writer's latency. Instead every write is dispatched to the runtime's
/// **blocking pool** (`spawn_blocking`), which re-acquires the GIL there; the
/// pump task only holds the returned `JoinHandle` and yields `Poll::Pending`
/// until it resolves — so backpressure is preserved without blocking the event
/// loop, and a slow (even sleeping) `write()` cannot deadlock the runtime.
///
/// **What `write()` receives.** The crate feeds this sink the *decoded* line
/// text (already run through the configured encoding) re-encoded as UTF-8: each
/// line's bytes, then `b"\n"`, per line. Each chunk is decoded back to `str` and
/// passed to `write()`, so this is a **text** sink — pass a text-mode writer
/// (`io.StringIO`, `sys.stderr`, a file opened in text mode, a logger wrapper),
/// not a binary one (`io.BytesIO`, a `"wb"` file), whose `write(str)` would
/// raise `TypeError`.
///
/// **Errors.** A `write()` (or `flush()`) exception is reported via
/// `sys.unraisablehook` (so it is never silent, even without `enable_logging()`)
/// and surfaced as an `io::Error`, which drives the crate's own tee-error
/// isolation: the tee is disabled for the rest of the run (a `tracing` warn
/// under `enable_logging()`) while the run and its captured result continue
/// unaffected — the same contract as the file-path tee, plus the Python
/// traceback via the unraisable hook.
///
/// We do **not** own the Python object (the caller keeps writing to their
/// `sys.stderr` / open file after the run), so this never closes it: shutdown
/// flushes but does not close.
pub(crate) struct PyWriterSink {
    /// The Python writer, refcounted so a `spawn_blocking` closure can hold its
    /// own clone without needing the GIL to bump the Python refcount (the `Arc`
    /// clone is GIL-free; the inner `Py` decref is deferred to a GIL point on
    /// drop, which PyO3 handles).
    writer: Arc<Py<PyAny>>,
    /// The single in-flight blocking op, if any. The crate drives one write (or
    /// the end-of-stream flush) to completion before starting the next, so a
    /// single slot suffices; it is polled to completion before a new op starts.
    pending: Option<Pending>,
}

/// The in-flight `spawn_blocking` op held across `Poll::Pending`. A `write`
/// remembers how many buffer bytes it consumed (reported back to the pump on
/// success); a `flush` has nothing to report.
enum Pending {
    Write { handle: BlockingOp, len: usize },
    Flush { handle: BlockingOp },
}

/// A dispatched blocking Python call: `Ok(())` on success, `Err(message)` when
/// `write()`/`flush()` raised (the exception was already sent to the unraisable
/// hook; the message rides along only to enrich the `io::Error`).
type BlockingOp = JoinHandle<Result<(), String>>;

impl PyWriterSink {
    pub(crate) fn new(writer: &Bound<'_, PyAny>) -> Self {
        Self {
            writer: Arc::new(writer.clone().unbind()),
            pending: None,
        }
    }
}

/// Call `writer.write(text)` under the GIL, decoding the crate's UTF-8 line
/// bytes back to `str`. Runs on a blocking-pool thread. A raising `write()` is
/// reported via the unraisable hook here (we hold the GIL) and its message
/// returned so the caller can build a matching `io::Error`.
fn call_py_write(writer: &Arc<Py<PyAny>>, data: Vec<u8>) -> Result<(), String> {
    // `try_attach`, not `attach`: this runs on a tokio blocking-pool worker that
    // is not joined at `Py_Finalize` (the runtime is an immortal singleton).
    // Once the interpreter is finalizing `try_attach` returns `None`; we reject
    // the write with an error (below), which drives the crate's own tee-error
    // isolation — the tee is disabled for the rest of the run — instead of the
    // panic/crash a plain `attach` would cause at shutdown. Same finalization
    // guard as `logging.rs`'s bridge.
    Python::try_attach(|py| {
        let bound = writer.bind(py);
        // The crate emits a whole decoded line, then `b"\n"`, so `data` is
        // always valid UTF-8; `from_utf8_lossy` is a panic-proof guard, not an
        // expected lossy path.
        let text = String::from_utf8_lossy(&data);
        match bound.call_method1("write", (text.as_ref(),)) {
            Ok(_) => Ok(()),
            Err(err) => {
                let message = err.to_string();
                err.write_unraisable(py, Some(bound));
                Err(message)
            }
        }
    })
    .unwrap_or_else(|| Err("tee write skipped: Python interpreter is finalizing".to_string()))
}

/// Call `writer.flush()` under the GIL if the object exposes a callable `flush`
/// (a bare write-only object — some logger wrappers — may not). Best-effort,
/// like the crate's end-of-stream file flush; a raising flush goes to the
/// unraisable hook.
fn call_py_flush(writer: &Arc<Py<PyAny>>) -> Result<(), String> {
    // `try_attach`, not `attach`: like `call_py_write`, this runs on a tokio
    // blocking-pool worker not joined at `Py_Finalize`. A finalizing interpreter
    // yields `None` -> reject with an error, which drives the crate's tee-error
    // isolation (the tee is disabled), instead of the panic/crash a plain
    // `attach` would cause at shutdown. Same finalization guard as `logging.rs`.
    Python::try_attach(|py| {
        let bound = writer.bind(py);
        match bound.getattr("flush") {
            Ok(flush) if flush.is_callable() => match flush.call0() {
                Ok(_) => Ok(()),
                Err(err) => {
                    let message = err.to_string();
                    err.write_unraisable(py, Some(bound));
                    Err(message)
                }
            },
            // No callable `flush` — nothing to do, not an error.
            _ => Ok(()),
        }
    })
    .unwrap_or_else(|| Err("tee flush skipped: Python interpreter is finalizing".to_string()))
}

/// Map a finished blocking-write `JoinHandle` result to what `poll_write`
/// returns: the consumed byte count on success, an `io::Error` on a `write()`
/// exception or a task panic.
fn finish_write(joined: Result<Result<(), String>, JoinError>, len: usize) -> io::Result<usize> {
    match joined {
        Ok(Ok(())) => Ok(len),
        Ok(Err(message)) => Err(io::Error::other(message)),
        Err(join_err) => Err(io::Error::other(format!(
            "tee writer task failed: {join_err}"
        ))),
    }
}

/// Map a finished blocking-flush `JoinHandle` result to `poll_flush`'s return.
fn finish_flush(joined: Result<Result<(), String>, JoinError>) -> io::Result<()> {
    match joined {
        Ok(Ok(())) => Ok(()),
        Ok(Err(message)) => Err(io::Error::other(message)),
        Err(join_err) => Err(io::Error::other(format!(
            "tee flush task failed: {join_err}"
        ))),
    }
}

impl AsyncWrite for PyWriterSink {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        // `PyWriterSink` is `Unpin` (all fields are), so `get_mut` is sound and
        // lets the state machine mutate `pending` freely.
        let this = self.get_mut();
        loop {
            match this.pending.take() {
                Some(Pending::Write { mut handle, len }) => match Pin::new(&mut handle).poll(cx) {
                    Poll::Pending => {
                        this.pending = Some(Pending::Write { handle, len });
                        return Poll::Pending;
                    }
                    Poll::Ready(joined) => return Poll::Ready(finish_write(joined, len)),
                },
                // A flush is in flight (the crate never interleaves this before a
                // write, but the `AsyncWrite` contract allows it): drain it, then
                // loop round to start the write.
                Some(Pending::Flush { mut handle }) => match Pin::new(&mut handle).poll(cx) {
                    Poll::Pending => {
                        this.pending = Some(Pending::Flush { handle });
                        return Poll::Pending;
                    }
                    Poll::Ready(_) => {}
                },
                None => {
                    // Never report `Ok(0)` for a non-empty buffer — that signals
                    // "wrote nothing" and `write_all` turns it into `WriteZero`.
                    if buf.is_empty() {
                        return Poll::Ready(Ok(0));
                    }
                    let writer = Arc::clone(&this.writer);
                    let data = buf.to_vec();
                    let handle = tokio::task::spawn_blocking(move || call_py_write(&writer, data));
                    this.pending = Some(Pending::Write {
                        handle,
                        len: buf.len(),
                    });
                }
            }
        }
    }

    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        let this = self.get_mut();
        loop {
            match this.pending.take() {
                // Drain any in-flight write first; a write error propagates out
                // of flush too (the crate disables the tee either way).
                Some(Pending::Write { mut handle, len }) => match Pin::new(&mut handle).poll(cx) {
                    Poll::Pending => {
                        this.pending = Some(Pending::Write { handle, len });
                        return Poll::Pending;
                    }
                    Poll::Ready(joined) => {
                        if let Err(err) = finish_write(joined, len) {
                            return Poll::Ready(Err(err));
                        }
                    }
                },
                Some(Pending::Flush { mut handle }) => match Pin::new(&mut handle).poll(cx) {
                    Poll::Pending => {
                        this.pending = Some(Pending::Flush { handle });
                        return Poll::Pending;
                    }
                    Poll::Ready(joined) => return Poll::Ready(finish_flush(joined)),
                },
                None => {
                    let writer = Arc::clone(&this.writer);
                    let handle = tokio::task::spawn_blocking(move || call_py_flush(&writer));
                    this.pending = Some(Pending::Flush { handle });
                }
            }
        }
    }

    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        // We don't own the Python object — flush what's pending, never close it.
        // (The crate's pump never calls this; implemented for contract
        // completeness.)
        self.poll_flush(cx)
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

/// Map a `Command.priority(level)` preset name to the crate `Priority` — a
/// direct snake_case mirror of the crate's enum variant names (`Idle` ->
/// `"idle"`, `BelowNormal` -> `"below_normal"`, `Normal` -> `"normal"`,
/// `AboveNormal` -> `"above_normal"`, `High` -> `"high"`). The crate's
/// `Priority` is `#[non_exhaustive]`, so this match keeps a `_ =>` fallback
/// (unreachable today) rather than assuming these five variants are
/// exhaustive forever.
pub(crate) fn parse_priority(level: &str) -> PyResult<Priority> {
    match level {
        "idle" => Ok(Priority::Idle),
        "below_normal" => Ok(Priority::BelowNormal),
        "normal" => Ok(Priority::Normal),
        "above_normal" => Ok(Priority::AboveNormal),
        "high" => Ok(Priority::High),
        other => Err(PyValueError::new_err(format!(
            "unknown priority {other:?}; use one of: idle, below_normal, normal, above_normal, high"
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

/// Map a `line_terminator`/`stdout_line_terminator`/`stderr_line_terminator`
/// preset name to the crate's `LineTerminator` — the crate enum has exactly
/// two variants (`Newline`, the default, and `CarriageReturn`), so there is no
/// third preset to invent here. `"newline"` (alias `"lf"`) keeps the pre-1.0
/// behavior of splitting on `\n` only; `"carriage_return"` (alias `"cr"`)
/// additionally treats a bare `\r` (one not immediately followed by `\n`) as
/// a frame terminator, delivered live — the mode `curl`/`pip`/`apt`-style
/// `\r`-redrawn progress bars need to stream one frame at a time instead of
/// piling up into a single line that only surfaces at EOF.
pub(crate) fn parse_line_terminator(mode: &str) -> PyResult<LineTerminator> {
    match mode {
        "newline" | "lf" => Ok(LineTerminator::Newline),
        "carriage_return" | "cr" => Ok(LineTerminator::CarriageReturn),
        other => Err(PyValueError::new_err(format!(
            "unknown line_terminator {other:?}; use one of: newline, lf, carriage_return, cr"
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

/// The highest raw signal number that is actually deliverable on the current
/// Unix platform — the upper bound of the crate's documented `Other(1..=SIGRTMAX)`
/// escape-hatch range, used to reject numbers that would otherwise be a silent
/// no-op on the process-group backend.
#[cfg(any(target_os = "linux", target_os = "android"))]
fn max_deliverable_signal() -> i32 {
    // glibc/musl compute the real-time signal ceiling at runtime (a few low RT
    // numbers are reserved for the C library / NPTL), so `SIGRTMAX` is a
    // function, not a compile-time constant.
    libc::SIGRTMAX()
}

/// macOS/BSD have no POSIX real-time signals in the `libc` binding; the highest
/// standard signal is `SIGUSR2` (31) and `NSIG` is 32, so `1..=SIGUSR2` is the
/// deliverable range. A conservative ceiling: a platform with extra high-numbered
/// RT signals the `libc` crate doesn't name would reject them — an acceptable
/// trade for a raw escape hatch whose portable alternative is a signal *name*.
#[cfg(all(unix, not(any(target_os = "linux", target_os = "android"))))]
fn max_deliverable_signal() -> i32 {
    libc::SIGUSR2
}

/// Validate a raw platform signal number and wrap it in the crate's
/// `Signal::Other` escape hatch. On Unix the number must be a real, deliverable
/// signal (`1..=SIGRTMAX`): `0` (the POSIX existence probe that delivers
/// nothing), negatives, and out-of-range values are rejected up front rather
/// than reaching the backend as a silent no-op (the process-group mechanism
/// swallows the `EINVAL` a bad number would raise).
#[cfg(unix)]
fn validate_raw_signal(raw: i32) -> PyResult<PkSignal> {
    let max = max_deliverable_signal();
    if (1..=max).contains(&raw) {
        Ok(PkSignal::Other(raw))
    } else {
        Err(PyValueError::new_err(format!(
            "invalid signal number {raw}: a raw signal must be a real, deliverable \
             signal in 1..={max} on this platform. 0 is the POSIX existence probe \
             (kill(pid, 0)) that delivers nothing, and an out-of-range number is \
             silently dropped by the process-group backend instead of erroring — \
             either way the send would be a no-op. Pass a valid signal number, or \
             a portable name: term, kill, int, hup, quit, usr1, usr2."
        )))
    }
}

/// On Windows a Job Object has no POSIX signals, so a raw number can never be
/// delivered. Surface that immediately and consistently — the same `Unsupported`
/// the crate raises at delivery time — from both `Command.timeout_signal` and
/// `ProcessGroup.signal`, instead of storing a number that only fails much later
/// when the timeout fires. The named `"kill"` still works: it takes the
/// `parse_signal_name` path, not this one.
#[cfg(not(unix))]
fn validate_raw_signal(raw: i32) -> PyResult<PkSignal> {
    Err(crate::errors::Unsupported::new_err(format!(
        "raw signal number {raw} is not supported on this platform: a Job Object \
         has no POSIX signals, so only the named signal \"kill\" (which maps to a \
         Job Object terminate) is deliverable on Windows."
    )))
}

/// Parse a signal argument that is either a portable name (see
/// `parse_signal_name`) or a raw platform signal number — the crate's
/// `Signal::Other(i32)` escape hatch (Unix only; a raw number is `Unsupported`
/// on Windows like every non-`Kill` signal). An `int` takes the raw-number path
/// (validated by [`validate_raw_signal`]); anything else is extracted as a name
/// string.
///
/// `bool` is rejected **before** the number path: it is a Python `int` subtype,
/// so `True`/`False` would otherwise slip through as raw signals `1`/`0` — and
/// raw `0` is the existence probe that delivers nothing, turning a boolean-config
/// typo into a silent no-op send. A bool is never a meaningful signal, so this is
/// a `TypeError`, not a value-range error.
pub(crate) fn parse_signal(obj: &Bound<'_, PyAny>) -> PyResult<PkSignal> {
    if obj.is_instance_of::<PyBool>() {
        return Err(PyTypeError::new_err(
            "signal must be a name (str) or a raw signal number (int), not a bool: \
             a bool is an int subtype that would silently become raw signal 1 (True) \
             or 0 (False), and raw 0 delivers nothing. Pass an explicit signal number \
             or a portable name (term, kill, int, hup, quit, usr1, usr2).",
        ));
    }
    if let Ok(raw) = obj.extract::<i32>() {
        return validate_raw_signal(raw);
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

// Rust-level unit tests for the pure helpers above (chiefly the boundary
// values Python-side integration tests can't easily reach in every
// combination — NaN/infinite durations, unknown preset names, the
// `Signal`/bool-as-int extraction order). See `docs/internals.md`'s testing
// section for the intended split between this module and `tests/`.
#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::{PyBool, PyInt, PyString};

    // --- positive_duration / nonnegative_duration --------------------------

    #[test]
    fn positive_duration_rejects_nan() {
        assert!(positive_duration(f64::NAN, "timeout").is_err());
    }

    #[test]
    fn positive_duration_rejects_positive_infinity() {
        assert!(positive_duration(f64::INFINITY, "timeout").is_err());
    }

    #[test]
    fn positive_duration_rejects_negative_infinity() {
        assert!(positive_duration(f64::NEG_INFINITY, "timeout").is_err());
    }

    #[test]
    fn positive_duration_rejects_negative_value() {
        assert!(positive_duration(-1.0, "timeout").is_err());
    }

    #[test]
    fn positive_duration_rejects_zero() {
        // Unlike `nonnegative_duration`, `0.0` is not a *positive* duration.
        assert!(positive_duration(0.0, "timeout").is_err());
    }

    #[test]
    fn positive_duration_rejects_value_overflowing_duration() {
        // Finite but far beyond `Duration::MAX` (~5.85e11 seconds): must be a
        // clean error, not a panic in `try_from_secs_f64`.
        assert!(positive_duration(f64::MAX, "timeout").is_err());
    }

    #[test]
    fn positive_duration_accepts_valid_value() {
        assert_eq!(
            positive_duration(1.5, "timeout").unwrap(),
            Duration::from_secs_f64(1.5)
        );
    }

    #[test]
    fn nonnegative_duration_rejects_nan() {
        assert!(nonnegative_duration(f64::NAN, "grace").is_err());
    }

    #[test]
    fn nonnegative_duration_rejects_positive_infinity() {
        assert!(nonnegative_duration(f64::INFINITY, "grace").is_err());
    }

    #[test]
    fn nonnegative_duration_rejects_negative_infinity() {
        assert!(nonnegative_duration(f64::NEG_INFINITY, "grace").is_err());
    }

    #[test]
    fn nonnegative_duration_rejects_negative_value() {
        assert!(nonnegative_duration(-0.001, "grace").is_err());
    }

    #[test]
    fn nonnegative_duration_accepts_zero() {
        // Unlike `positive_duration`, `0.0` means "immediately" and is allowed.
        assert_eq!(nonnegative_duration(0.0, "grace").unwrap(), Duration::ZERO);
    }

    #[test]
    fn nonnegative_duration_rejects_value_overflowing_duration() {
        assert!(nonnegative_duration(f64::MAX, "grace").is_err());
    }

    #[test]
    fn nonnegative_duration_accepts_valid_value() {
        assert_eq!(
            nonnegative_duration(2.5, "grace").unwrap(),
            Duration::from_secs_f64(2.5)
        );
    }

    // --- parse_signal_name / parse_signal -----------------------------------

    #[test]
    fn parse_signal_name_accepts_every_named_variant() {
        let cases = [
            ("term", PkSignal::Term),
            ("kill", PkSignal::Kill),
            ("int", PkSignal::Int),
            ("hup", PkSignal::Hup),
            ("quit", PkSignal::Quit),
            ("usr1", PkSignal::Usr1),
            ("usr2", PkSignal::Usr2),
        ];
        for (name, expected) in cases {
            assert_eq!(parse_signal_name(name).unwrap(), expected, "{name}");
        }
    }

    #[test]
    fn parse_signal_name_accepts_sig_prefix() {
        assert_eq!(parse_signal_name("sigterm").unwrap(), PkSignal::Term);
        assert_eq!(parse_signal_name("sigkill").unwrap(), PkSignal::Kill);
    }

    #[test]
    fn parse_signal_name_is_case_insensitive() {
        assert_eq!(parse_signal_name("TERM").unwrap(), PkSignal::Term);
        assert_eq!(parse_signal_name("SigTerm").unwrap(), PkSignal::Term);
        assert_eq!(parse_signal_name("SIGKILL").unwrap(), PkSignal::Kill);
    }

    #[test]
    fn parse_signal_name_rejects_unknown_name() {
        assert!(parse_signal_name("bogus").is_err());
    }

    /// `Python::attach` panics unless the interpreter is initialized — normally
    /// done by the embedding Python process, but nothing does that for a plain
    /// `cargo test` binary (built without the `extension-module` feature, so
    /// `pyo3`'s `auto-initialize` isn't assumed either). `Python::initialize()`
    /// is a no-op if already initialized, so this is safe to call from every
    /// test that needs the GIL.
    fn ensure_python_initialized() {
        Python::initialize();
    }

    #[cfg(unix)]
    #[test]
    fn parse_signal_accepts_valid_raw_number_on_unix() {
        // 10 is a real, deliverable signal on every Unix (SIGUSR1 on Linux,
        // SIGBUS on macOS) — inside `1..=SIGRTMAX` everywhere, so it passes
        // validation and rides the `Signal::Other` escape hatch verbatim.
        ensure_python_initialized();
        Python::attach(|py| {
            let obj = PyInt::new(py, 10i32).into_any();
            assert_eq!(parse_signal(&obj).unwrap(), PkSignal::Other(10));
        });
    }

    #[cfg(unix)]
    #[test]
    fn parse_signal_rejects_zero_on_unix() {
        // Signal 0 is the POSIX existence probe — `kill(pid, 0)` delivers
        // nothing, so a `0` send is a silent no-op, not a real signal.
        ensure_python_initialized();
        Python::attach(|py| {
            let obj = PyInt::new(py, 0i32).into_any();
            assert!(parse_signal(&obj).is_err());
        });
    }

    #[cfg(unix)]
    #[test]
    fn parse_signal_rejects_negative_on_unix() {
        ensure_python_initialized();
        Python::attach(|py| {
            let obj = PyInt::new(py, -1i32).into_any();
            assert!(parse_signal(&obj).is_err());
        });
    }

    #[cfg(unix)]
    #[test]
    fn parse_signal_rejects_out_of_range_on_unix() {
        // Far above any real SIGRTMAX (64 on Linux, 31 on macOS): the
        // process-group backend would silently drop it (EINVAL swallowed), so
        // reject it up front instead of letting the send be a no-op.
        ensure_python_initialized();
        Python::attach(|py| {
            let obj = PyInt::new(py, 100_000i32).into_any();
            assert!(parse_signal(&obj).is_err());
        });
    }

    #[cfg(not(unix))]
    #[test]
    fn parse_signal_rejects_raw_number_off_unix() {
        // No POSIX signals on Windows — a raw number can never be delivered, so
        // it is rejected immediately (only the named "kill" works there).
        ensure_python_initialized();
        Python::attach(|py| {
            let obj = PyInt::new(py, 10i32).into_any();
            assert!(parse_signal(&obj).is_err());
        });
    }

    #[test]
    fn parse_signal_rejects_bool() {
        // `bool` is a Python `int` subtype but is never a meaningful signal; it
        // must be rejected before the raw-number path on every platform, so a
        // `False`/`True` config typo cannot silently become the no-op existence
        // probe (signal 0) or raw signal 1.
        ensure_python_initialized();
        Python::attach(|py| {
            let true_obj = PyBool::new(py, true).to_owned().into_any();
            assert!(parse_signal(&true_obj).is_err());
            let false_obj = PyBool::new(py, false).to_owned().into_any();
            assert!(parse_signal(&false_obj).is_err());
        });
    }

    #[test]
    fn parse_signal_accepts_name_string() {
        ensure_python_initialized();
        Python::attach(|py| {
            let obj = PyString::new(py, "hup").into_any();
            assert_eq!(parse_signal(&obj).unwrap(), PkSignal::Hup);
        });
    }

    #[test]
    fn parse_signal_rejects_unknown_name_string() {
        ensure_python_initialized();
        Python::attach(|py| {
            let obj = PyString::new(py, "bogus").into_any();
            assert!(parse_signal(&obj).is_err());
        });
    }

    // --- parse_priority ------------------------------------------------------

    #[test]
    fn parse_priority_accepts_every_variant() {
        let cases = [
            ("idle", Priority::Idle),
            ("below_normal", Priority::BelowNormal),
            ("normal", Priority::Normal),
            ("above_normal", Priority::AboveNormal),
            ("high", Priority::High),
        ];
        for (name, expected) in cases {
            assert_eq!(parse_priority(name).unwrap(), expected, "{name}");
        }
    }

    #[test]
    fn parse_priority_rejects_unknown_name() {
        assert!(parse_priority("realtime").is_err());
    }

    // --- parse_overflow_mode -------------------------------------------------

    #[test]
    fn parse_overflow_mode_accepts_every_variant() {
        let cases = [
            ("drop_oldest", OverflowMode::DropOldest),
            ("drop_newest", OverflowMode::DropNewest),
            ("error", OverflowMode::Error),
        ];
        for (name, expected) in cases {
            assert_eq!(parse_overflow_mode(name).unwrap(), expected, "{name}");
        }
    }

    #[test]
    fn parse_overflow_mode_rejects_unknown_name() {
        assert!(parse_overflow_mode("bogus").is_err());
    }

    // --- parse_line_terminator -----------------------------------------------

    #[test]
    fn parse_line_terminator_accepts_every_variant_and_alias() {
        let cases = [
            ("newline", LineTerminator::Newline),
            ("lf", LineTerminator::Newline),
            ("carriage_return", LineTerminator::CarriageReturn),
            ("cr", LineTerminator::CarriageReturn),
        ];
        for (name, expected) in cases {
            assert_eq!(parse_line_terminator(name).unwrap(), expected, "{name}");
        }
    }

    #[test]
    fn parse_line_terminator_rejects_unknown_mode() {
        assert!(parse_line_terminator("bogus").is_err());
    }

    // --- build_output_buffer_policy ------------------------------------------

    #[test]
    fn build_output_buffer_policy_rejects_both_caps_unset() {
        assert!(build_output_buffer_policy(None, None, "drop_oldest", "output_limit").is_err());
    }

    #[test]
    fn build_output_buffer_policy_accepts_only_max_bytes() {
        let policy =
            build_output_buffer_policy(Some(1024), None, "drop_oldest", "output_limit").unwrap();
        assert_eq!(policy.max_bytes, Some(1024));
        assert_eq!(policy.max_lines, None);
        assert_eq!(policy.overflow, OverflowMode::DropOldest);
    }

    #[test]
    fn build_output_buffer_policy_accepts_only_max_lines() {
        let policy =
            build_output_buffer_policy(None, Some(10), "drop_oldest", "output_limit").unwrap();
        assert_eq!(policy.max_lines, Some(10));
        assert_eq!(policy.max_bytes, None);
    }

    #[test]
    fn build_output_buffer_policy_accepts_both_caps() {
        let policy =
            build_output_buffer_policy(Some(2048), Some(20), "drop_newest", "output_limit")
                .unwrap();
        assert_eq!(policy.max_bytes, Some(2048));
        assert_eq!(policy.max_lines, Some(20));
        assert_eq!(policy.overflow, OverflowMode::DropNewest);
    }

    #[test]
    fn build_output_buffer_policy_applies_every_overflow_mode() {
        for (name, expected) in [
            ("drop_oldest", OverflowMode::DropOldest),
            ("drop_newest", OverflowMode::DropNewest),
            ("error", OverflowMode::Error),
        ] {
            let policy = build_output_buffer_policy(Some(1), None, name, "output_limit").unwrap();
            assert_eq!(policy.overflow, expected, "{name}");
        }
    }

    #[test]
    fn build_output_buffer_policy_rejects_unknown_overflow_mode() {
        assert!(build_output_buffer_policy(Some(1), None, "bogus", "output_limit").is_err());
    }
}
