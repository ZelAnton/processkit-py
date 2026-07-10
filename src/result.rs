//! The captured-result value types: `ProcessResult`, `BytesResult`, `Outcome`,
//! `OutputEvent`, `Finished`, and `RunProfile`.
//!
//! ## Value semantics: `__eq__`/`__hash__`/pickle (task T-041)
//!
//! Every type here (bar `OutputEvent`, out of this task's scope) gets `__eq__`
//! delegating to the crate's own `PartialEq` (so equality tracks the crate's
//! notion of identity, not Python's default `object` identity-`__eq__`), plus a
//! `__hash__` consistent with it — all of their fields are exact (integers,
//! `Duration`, `bool`, text/bytes; no floats are *stored*, only derived as
//! `f64` getters), so hashing is semantically sound.
//!
//! Pickle is a harder call, and the answer differs per type. All of
//! `processkit::ProcessResult`/`Outcome`/`Finished`/`RunProfile`/
//! `SupervisionOutcome` are `#[non_exhaustive]` (or, for `ProcessResult`,
//! plain-field-private) with **no public constructor** — `ProcessResult::new`
//! is `pub(crate)`, and none of the others expose a builder either. So this
//! binding cannot fabricate one from arbitrary unpickled data by calling into
//! the crate directly; the *only* crate-sanctioned way to synthesize one
//! outside a real run is to drive its `testing::ScriptedRunner` double (the
//! same mechanism the crate's own cassette replay uses) through one in-memory,
//! no-subprocess "run" — see `scripted_outcome` below.
//!
//! That channel round-trips **`Outcome` and `Finished` exactly**: an `Outcome`
//! is fully determined by `(code, signal, timed_out)` (all Python-visible), and
//! a `Finished` adds only its `stderr` (carried through verbatim) — so a
//! reconstructed value compares `==` its original. They support pickle.
//!
//! It does **not** round-trip `ProcessResult` (nor, therefore,
//! `SupervisionOutcome` in `supervisor.rs`, whose identity includes a
//! `ProcessResult` `final_result`). `ProcessResult`'s equality — the crate's
//! own `PartialEq`, which `__eq__` delegates to — compares two fields the crate
//! exposes through **no accessor**: the configured `timeout` and the accepted
//! `ok_codes`. A `__reduce__` holding only `&self` cannot read them to
//! serialize them, and a scripted reconstruction would default them
//! (`timeout=None`, `ok_codes=[0]`), so a result from a command that set
//! `.timeout(...)` or `.success_codes(...)` would unpickle **unequal** to its
//! original (same visible fields and hash, but `!=`). These results are also
//! produced deep inside the crate (group/batch/supervisor/CLI-client runs)
//! where the binding never sees the originating command's config to stash a
//! reconstruction seed, so there is no faithful channel to add either. Rather
//! than hand back a value that silently breaks the pickle round-trip invariant,
//! `ProcessResult`/`SupervisionOutcome` refuse to pickle — the same explicit
//! `TypeError` `BytesResult`/`RunProfile` raise. Pickle `result.outcome` (an
//! `Outcome`), or persist the fields you need, to cross a process boundary.
//!
//! `BytesResult` and `RunProfile` likewise do not pickle (see their
//! `__reduce__`): `BytesResult`'s raw stdout may not be valid UTF-8 and `Reply`
//! is a text-only channel; `RunProfile` reports genuine OS resource-sampling
//! telemetry (`cpu_time_seconds`/`peak_memory_bytes`/`samples`) with no
//! synthesis path outside an actually-monitored run. Every non-picklable type
//! raises a clear `TypeError` rather than failing silently/confusingly.

use std::hash::{Hash, Hasher};

use processkit::testing::{Reply as PkReply, ScriptedRunner as PkScriptedRunner};
use processkit::Command as PkCommand;
use processkit::Finished as PkFinished;
use processkit::Outcome as PkOutcome;
use processkit::OutputEvent as PkOutputEvent;
use processkit::ProcessResult as PkProcessResult;
use processkit::ProcessRunner as _;
use processkit::RunProfile as PkRunProfile;
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::runtime::block_on;

/// Reconstruct a genuine `processkit::Outcome` for unpickling `Outcome`/
/// `Finished` — see the module doc above for *why* this goes through
/// `ScriptedRunner` rather than a direct constructor (the crate exposes no
/// public `Outcome` constructor).
///
/// An `Outcome` is fully determined by its `(code, signal, timed_out)` triple,
/// all Python-visible, so this reconstruction is **exact**: the resulting
/// `Outcome` compares `==` the original. (This is why `Outcome`/`Finished`
/// pickle while `ProcessResult` — whose identity also spans the accessor-less
/// `timeout`/`ok_codes` — does not; see the module doc.) The result's
/// program/stdout/stderr/`ok_codes` are irrelevant to the `Outcome` it yields,
/// so a bare command and empty streams suffice.
fn scripted_outcome(
    py: Python<'_>,
    code: Option<i32>,
    signal: Option<i32>,
    timed_out: bool,
) -> PyResult<PkOutcome> {
    let reply = if timed_out {
        PkReply::timeout()
    } else if let Some(code) = code {
        PkReply::fail(code, String::new())
    } else {
        PkReply::signalled(signal)
    };
    let command = PkCommand::new("");
    let runner = PkScriptedRunner::new().fallback(reply);
    let result = block_on(py, async move { runner.output_string(&command).await })?;
    Ok(result.outcome())
}

/// A resource-usage profile sampled across a run (from `RunningProcess.profile`).
#[pyclass(name = "RunProfile", frozen, module = "processkit")]
pub(crate) struct PyRunProfile {
    pub(crate) inner: PkRunProfile,
}

impl From<PkRunProfile> for PyRunProfile {
    fn from(inner: PkRunProfile) -> Self {
        Self { inner }
    }
}

#[pymethods]
impl PyRunProfile {
    /// The exit code, or `None` for a timeout / signal-kill. (Named `code` to
    /// match every other result type — `ProcessResult`, `Outcome`, ….)
    #[getter]
    fn code(&self) -> Option<i32> {
        self.inner.code()
    }

    /// Wall-clock time from start until the run finished, in seconds.
    #[getter]
    fn duration_seconds(&self) -> f64 {
        self.inner.duration.as_secs_f64()
    }

    /// Cumulative CPU time at the last sample, in seconds, if measurable.
    #[getter]
    fn cpu_time_seconds(&self) -> Option<f64> {
        self.inner.cpu_time.map(|d| d.as_secs_f64())
    }

    /// Peak resident memory observed across samples, in bytes, if measurable.
    #[getter]
    fn peak_memory_bytes(&self) -> Option<u64> {
        self.inner.peak_memory_bytes
    }

    /// How many sampling ticks ran.
    #[getter]
    fn samples(&self) -> usize {
        self.inner.samples
    }

    /// Average CPU cores used over the run (cpu_time / duration), if measurable.
    /// A value of `1.0` means one core fully saturated; `2.0`, two cores.
    #[getter]
    fn avg_cpu_cores(&self) -> Option<f64> {
        self.inner.avg_cpu_cores()
    }

    /// The signal that killed the run, if it was signal-killed; `None` otherwise.
    #[getter]
    fn signal(&self) -> Option<i32> {
        self.inner.signal()
    }

    /// Whether the run hit its timeout.
    #[getter]
    fn timed_out(&self) -> bool {
        self.inner.timed_out()
    }

    /// The full run outcome (`code` / `signal` / `timed_out`) — the same value a
    /// `wait()` would return. `profile()` computes it anyway, so it is a superset
    /// of `wait()`: telemetry **and** how the run actually ended.
    #[getter]
    fn outcome(&self) -> PyOutcome {
        PyOutcome::from(self.inner.outcome)
    }

    fn __repr__(&self) -> String {
        format!(
            "RunProfile(code={:?}, timed_out={}, duration_seconds={:.3}, peak_memory_bytes={:?}, samples={})",
            self.inner.code(),
            self.inner.timed_out(),
            self.inner.duration.as_secs_f64(),
            self.inner.peak_memory_bytes,
            self.inner.samples,
        )
    }

    /// Value equality over every field the crate's own `PartialEq` compares —
    /// not `object`'s identity comparison.
    fn __eq__(&self, other: &Self) -> bool {
        self.inner == other.inner
    }

    /// Consistent with `__eq__`: hashes exactly the fields compared there. No
    /// field is a stored float (`duration_seconds`/`cpu_time_seconds` are `f64`
    /// *getters* over an exact `Duration`), so hashing is sound.
    fn __hash__(&self) -> u64 {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        self.inner.code().hash(&mut hasher);
        self.inner.signal().hash(&mut hasher);
        self.inner.timed_out().hash(&mut hasher);
        self.inner.duration.hash(&mut hasher);
        self.inner.cpu_time.hash(&mut hasher);
        self.inner.peak_memory_bytes.hash(&mut hasher);
        self.inner.samples.hash(&mut hasher);
        hasher.finish()
    }

    /// `RunProfile` reports genuine OS resource-sampling telemetry
    /// (`cpu_time_seconds`/`peak_memory_bytes`/`samples`) captured across a
    /// live, monitored run; `processkit` provides no way to synthesize that
    /// telemetry outside such a run (unlike `ProcessResult`/`Outcome`, there is
    /// no `ScriptedRunner`-equivalent double for it), so pickling is not
    /// supported — fail loud rather than silently drop/fabricate the numbers.
    fn __reduce__(&self) -> PyResult<()> {
        Err(PyTypeError::new_err(
            "RunProfile cannot be pickled: it reports live OS resource-sampling telemetry \
             (cpu_time_seconds/peak_memory_bytes/samples) that processkit has no way to \
             reconstruct outside an actual monitored run; read the fields you need before \
             crossing a process boundary instead",
        ))
    }
}

/// The captured result of a finished run. A non-zero exit, a timeout, and a
/// signal-kill are all *data* here — `output()` never raises on them.
#[pyclass(name = "ProcessResult", frozen, module = "processkit")]
pub(crate) struct PyProcessResult {
    pub(crate) inner: PkProcessResult<String>,
}

impl From<PkProcessResult<String>> for PyProcessResult {
    fn from(inner: PkProcessResult<String>) -> Self {
        Self { inner }
    }
}

#[pymethods]
impl PyProcessResult {
    #[getter]
    fn stdout(&self) -> &str {
        self.inner.stdout().as_str()
    }

    #[getter]
    fn stderr(&self) -> &str {
        self.inner.stderr()
    }

    /// The exit code, or `None` for a timeout / signal-kill (never a sentinel).
    #[getter]
    fn code(&self) -> Option<i32> {
        self.inner.code()
    }

    #[getter]
    fn is_success(&self) -> bool {
        self.inner.is_success()
    }

    #[getter]
    fn timed_out(&self) -> bool {
        self.inner.timed_out()
    }

    #[getter]
    fn signal(&self) -> Option<i32> {
        self.inner.signal()
    }

    #[getter]
    fn program(&self) -> &str {
        self.inner.program()
    }

    #[getter]
    fn duration_seconds(&self) -> f64 {
        self.inner.duration().as_secs_f64()
    }

    /// Whether captured output was truncated by an `output_limit(...)` cap.
    #[getter]
    fn truncated(&self) -> bool {
        self.inner.truncated()
    }

    /// stdout and stderr concatenated into one string (stdout first, then stderr).
    #[getter]
    fn combined(&self) -> String {
        self.inner.combined()
    }

    /// The best human-facing message from this result: stderr if it carries
    /// text, otherwise stdout, otherwise `None` if both are blank — the same
    /// preference order as `NonZeroExit`/`Timeout`/`Signalled.diagnostic` on
    /// the exceptions (`error.diagnostic()` in `src/errors.rs`), so a result
    /// held as data (rather than raised) can build the same message.
    #[getter]
    fn diagnostic(&self) -> Option<&str> {
        let text = self.inner.diagnostic();
        if text.is_empty() {
            None
        } else {
            Some(text)
        }
    }

    /// The full run outcome (`code` / `signal` / `timed_out`), the same value
    /// `RunProfile.outcome` and the checking-verb exceptions expose.
    #[getter]
    fn outcome(&self) -> PyOutcome {
        PyOutcome::from(self.inner.outcome())
    }

    /// Raise the same exception a checking verb (`run`/`exit_code`/`probe`)
    /// would if this result's exit isn't in `success_codes` — for turning an
    /// already-captured `output()`/`output_bytes()` result into an error after
    /// the fact (some code paths need the data either way, others should fail
    /// loud only sometimes). Returns `self` unchanged on success (the very
    /// same object, not a copy), so it composes into a call chain:
    /// `cmd.output().ensure_success().stdout`.
    fn ensure_success(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<Self>> {
        if slf.borrow(py).inner.is_success() {
            return Ok(slf);
        }
        // Only the (rare) failure path needs an owned `inner` — the crate's
        // `ensure_success()` consumes `self` to build the error, and this
        // clone is never reached on success.
        let inner = slf.borrow(py).inner.clone();
        match inner.ensure_success() {
            Ok(_) => Ok(slf),
            Err(err) => Err(crate::errors::map_err(err)),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "ProcessResult(program={:?}, code={:?}, success={})",
            self.inner.program(),
            self.inner.code(),
            self.inner.is_success(),
        )
    }

    /// Value equality over the crate's own `PartialEq` for `ProcessResult`
    /// (program/stdout/stderr/outcome/timeout/ok_codes — deliberately *not*
    /// `duration`/`truncated`/the overflow totals, which the crate excludes as
    /// incidental telemetry) — not `object`'s identity comparison.
    fn __eq__(&self, other: &Self) -> bool {
        self.inner == other.inner
    }

    /// Consistent with `__eq__`: hashes a subset of the fields compared there
    /// (program/stdout/stderr/code/signal/timed_out — `timeout`/`ok_codes` have
    /// no accessor on this binding to hash, but omitting them from the hash
    /// while `__eq__` still compares them is safe: equal objects necessarily
    /// agree on this subset too, just with more hash collisions than a hash
    /// over every compared field would have). No stored float.
    fn __hash__(&self) -> u64 {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        self.inner.program().hash(&mut hasher);
        self.inner.stdout().hash(&mut hasher);
        self.inner.stderr().hash(&mut hasher);
        self.inner.code().hash(&mut hasher);
        self.inner.signal().hash(&mut hasher);
        self.inner.timed_out().hash(&mut hasher);
        hasher.finish()
    }

    /// Unlike `Outcome`/`Finished`, `ProcessResult` is **not** picklable. Its
    /// equality — the crate's own `ProcessResult` `PartialEq`, which `__eq__`
    /// delegates to — compares the configured `timeout` and the accepted
    /// `ok_codes`, and `processkit` exposes no accessor for either. A
    /// `__reduce__` holding only `&self` cannot read them to serialize them, and
    /// the scripted reconstruction channel would default them
    /// (`timeout=None`/`ok_codes=[0]`), so a result from a command that set
    /// `.timeout(...)`/`.success_codes(...)` would unpickle **unequal** to its
    /// original (same visible fields and hash, but `!=`). Refuse loudly rather
    /// than silently break the round-trip invariant — the same call
    /// `BytesResult`/`RunProfile` make. Pickle `result.outcome` (an `Outcome`,
    /// which round-trips exactly), or persist `result.stdout`/`.stderr`/`.code`
    /// yourself, to cross a process boundary.
    fn __reduce__(&self) -> PyResult<()> {
        Err(PyTypeError::new_err(
            "ProcessResult cannot be pickled: its equality (the processkit crate's own \
             ProcessResult comparison) also spans the configured timeout and accepted \
             success_codes, which processkit exposes no accessor to read back, so a pickled \
             result would unpickle unequal to its original for any command that set .timeout(...) \
             or .success_codes(...); pickle result.outcome (an Outcome, which round-trips \
             exactly), or persist result.stdout/.stderr/.code yourself",
        ))
    }
}

/// The captured result of a finished run with **raw bytes** stdout (produced by
/// `Command.output_bytes()`); stderr stays decoded text. As with `ProcessResult`,
/// a non-zero exit, a timeout, and a signal-kill are all *data* here.
#[pyclass(name = "BytesResult", frozen, module = "processkit")]
pub(crate) struct PyBytesResult {
    pub(crate) inner: PkProcessResult<Vec<u8>>,
}

impl From<PkProcessResult<Vec<u8>>> for PyBytesResult {
    fn from(inner: PkProcessResult<Vec<u8>>) -> Self {
        Self { inner }
    }
}

#[pymethods]
impl PyBytesResult {
    #[getter]
    fn stdout<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.inner.stdout().as_slice())
    }

    #[getter]
    fn stderr(&self) -> &str {
        self.inner.stderr()
    }

    /// The exit code, or `None` for a timeout / signal-kill.
    #[getter]
    fn code(&self) -> Option<i32> {
        self.inner.code()
    }

    #[getter]
    fn is_success(&self) -> bool {
        self.inner.is_success()
    }

    #[getter]
    fn timed_out(&self) -> bool {
        self.inner.timed_out()
    }

    #[getter]
    fn signal(&self) -> Option<i32> {
        self.inner.signal()
    }

    #[getter]
    fn program(&self) -> &str {
        self.inner.program()
    }

    #[getter]
    fn duration_seconds(&self) -> f64 {
        self.inner.duration().as_secs_f64()
    }

    /// Whether captured output was truncated by an `output_limit(...)` cap — the
    /// line-captured stderr under any cap, and (since processkit 2.1.0) the raw
    /// stdout too when an `output_limit(max_bytes=...)` byte ceiling bounds it to
    /// a head/tail. A `max_lines` cap never truncates raw stdout (bytes have no
    /// line count); only a `max_bytes` cap does.
    #[getter]
    fn truncated(&self) -> bool {
        self.inner.truncated()
    }

    /// The best human-facing message from this result: stderr if it carries
    /// text, otherwise stdout (lossily decoded, since raw stdout may not be
    /// valid UTF-8), otherwise `None` if both are blank — see
    /// `ProcessResult.diagnostic`. The crate's own `ProcessResult::diagnostic`
    /// is only implemented for `ProcessResult<String>`, so this mirrors its
    /// stderr-then-stdout preference by hand for the `Vec<u8>` stdout here.
    #[getter]
    fn diagnostic(&self) -> Option<String> {
        let stderr = self.inner.stderr().trim();
        if !stderr.is_empty() {
            return Some(stderr.to_string());
        }
        let stdout = String::from_utf8_lossy(self.inner.stdout().as_slice());
        let stdout = stdout.trim();
        if stdout.is_empty() {
            None
        } else {
            Some(stdout.to_string())
        }
    }

    /// The full run outcome (`code` / `signal` / `timed_out`) — see
    /// `ProcessResult.outcome`.
    #[getter]
    fn outcome(&self) -> PyOutcome {
        PyOutcome::from(self.inner.outcome())
    }

    /// Raise the same exception a checking verb would if this result's exit
    /// isn't in `success_codes` — see `ProcessResult.ensure_success()`. Returns
    /// `self` unchanged on success (the very same object, not a copy).
    fn ensure_success(slf: Py<Self>, py: Python<'_>) -> PyResult<Py<Self>> {
        if slf.borrow(py).inner.is_success() {
            return Ok(slf);
        }
        // Only the (rare) failure path needs an owned `inner` — the crate's
        // `ensure_success()` consumes `self` to build the error, and this
        // clone is never reached on success.
        let inner = slf.borrow(py).inner.clone();
        match inner.ensure_success() {
            Ok(_) => Ok(slf),
            Err(err) => Err(crate::errors::map_err(err)),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "BytesResult(program={:?}, code={:?}, success={}, stdout_len={})",
            self.inner.program(),
            self.inner.code(),
            self.inner.is_success(),
            self.inner.stdout().len(),
        )
    }

    /// See `ProcessResult.__eq__` — same crate `PartialEq`, raw-bytes stdout.
    fn __eq__(&self, other: &Self) -> bool {
        self.inner == other.inner
    }

    /// See `ProcessResult.__hash__`.
    fn __hash__(&self) -> u64 {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        self.inner.program().hash(&mut hasher);
        self.inner.stdout().hash(&mut hasher);
        self.inner.stderr().hash(&mut hasher);
        self.inner.code().hash(&mut hasher);
        self.inner.signal().hash(&mut hasher);
        self.inner.timed_out().hash(&mut hasher);
        hasher.finish()
    }

    /// Unlike `ProcessResult`, `BytesResult` is not picklable: its raw stdout
    /// may not be valid UTF-8 (that is the entire point of `output_bytes()`),
    /// while the only crate-sanctioned reconstruction channel
    /// (`testing::Reply`) is text-only, so a faithful round trip is not always
    /// possible — fail loud rather than lossily reencode/mangle binary output.
    fn __reduce__(&self) -> PyResult<()> {
        Err(PyTypeError::new_err(
            "BytesResult cannot be pickled: its raw stdout may not be valid UTF-8, and \
             processkit has no public way to reconstruct a ProcessResult<bytes> from arbitrary \
             bytes outside a real run; pickle a text ProcessResult (Command.output()) instead, \
             or persist result.stdout/.stderr/.code yourself",
        ))
    }
}

/// How a process ended: a clean exit code, a signal-kill, or a timeout.
#[pyclass(name = "Outcome", frozen, module = "processkit")]
pub(crate) struct PyOutcome {
    pub(crate) inner: PkOutcome,
}

impl From<PkOutcome> for PyOutcome {
    fn from(inner: PkOutcome) -> Self {
        Self { inner }
    }
}

#[pymethods]
impl PyOutcome {
    /// The exit code, or `None` for a signal-kill / timeout.
    #[getter]
    fn code(&self) -> Option<i32> {
        self.inner.code()
    }

    /// The terminating signal number (Unix), or `None`.
    #[getter]
    fn signal(&self) -> Option<i32> {
        self.inner.signal()
    }

    #[getter]
    fn timed_out(&self) -> bool {
        self.inner.timed_out()
    }

    /// Whether the process exited with code `0`. Named `exited_zero` (not
    /// `is_success`) because an `Outcome` carries no `success_codes` context — for
    /// the command's own success verdict use `ProcessResult.is_success`, or test
    /// `code` against your accepted set.
    #[getter]
    fn exited_zero(&self) -> bool {
        self.inner.code() == Some(0)
    }

    fn __repr__(&self) -> String {
        format!(
            "Outcome(code={:?}, signal={:?}, timed_out={})",
            self.inner.code(),
            self.inner.signal(),
            self.inner.timed_out(),
        )
    }

    /// Value equality over the crate's derived `PartialEq` for `Outcome` — not
    /// `object`'s identity comparison.
    fn __eq__(&self, other: &Self) -> bool {
        self.inner == other.inner
    }

    /// Consistent with `__eq__`: `(code, signal, timed_out)` fully determines
    /// which of the three variants an `Outcome` is and its payload.
    fn __hash__(&self) -> u64 {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        self.inner.code().hash(&mut hasher);
        self.inner.signal().hash(&mut hasher);
        self.inner.timed_out().hash(&mut hasher);
        hasher.finish()
    }

    /// Pickle support: see the module doc — reconstructed via
    /// `scripted_outcome` (a scripted, no-subprocess run), since
    /// `processkit::Outcome` has no public constructor.
    #[allow(clippy::type_complexity)]
    fn __reduce__<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<(Py<PyAny>, (Option<i32>, Option<i32>, bool))> {
        let factory = py.get_type::<Self>().getattr("_unpickle")?.unbind();
        Ok((
            factory,
            (
                self.inner.code(),
                self.inner.signal(),
                self.inner.timed_out(),
            ),
        ))
    }

    /// `__reduce__`'s factory: a private (leading-underscore) staticmethod
    /// rather than a module-level function, so it rides along with the class in
    /// the stub/API-surface checks instead of needing its own module-level stub
    /// entry. Reconstructs the `Outcome` via `scripted_outcome` (see its doc).
    #[staticmethod]
    fn _unpickle(
        py: Python<'_>,
        code: Option<i32>,
        signal: Option<i32>,
        timed_out: bool,
    ) -> PyResult<Self> {
        Ok(Self {
            inner: scripted_outcome(py, code, signal, timed_out)?,
        })
    }
}

/// One captured line and the stream it came from (`stdout` or `stderr`).
#[pyclass(name = "OutputEvent", frozen, module = "processkit")]
pub(crate) struct PyOutputEvent {
    is_stderr: bool,
    text: String,
}

impl PyOutputEvent {
    pub(crate) fn from_event(event: PkOutputEvent) -> Self {
        match event {
            PkOutputEvent::Stdout(line) => Self {
                is_stderr: false,
                text: line.into_text(),
            },
            PkOutputEvent::Stderr(line) => Self {
                is_stderr: true,
                text: line.into_text(),
            },
            // `OutputEvent` is `#[non_exhaustive]`; degrade gracefully.
            other => Self {
                is_stderr: false,
                text: other.text().unwrap_or_default().to_string(),
            },
        }
    }
}

#[pymethods]
impl PyOutputEvent {
    /// `"stdout"` or `"stderr"`.
    #[getter]
    fn stream(&self) -> &'static str {
        if self.is_stderr {
            "stderr"
        } else {
            "stdout"
        }
    }

    #[getter]
    fn is_stderr(&self) -> bool {
        self.is_stderr
    }

    #[getter]
    fn text(&self) -> &str {
        &self.text
    }

    fn __repr__(&self) -> String {
        format!(
            "OutputEvent(stream={:?}, text={:?})",
            self.stream(),
            self.text
        )
    }
}

/// The result of `RunningProcess.finish()`: the outcome plus captured stderr,
/// without buffering stdout (which you consumed by streaming).
#[pyclass(name = "Finished", frozen, module = "processkit")]
pub(crate) struct PyFinished {
    pub(crate) outcome: PkOutcome,
    pub(crate) stderr: String,
}

impl From<PkFinished> for PyFinished {
    fn from(finished: PkFinished) -> Self {
        Self {
            outcome: finished.outcome,
            stderr: finished.stderr,
        }
    }
}

#[pymethods]
impl PyFinished {
    #[getter]
    fn outcome(&self) -> PyOutcome {
        PyOutcome {
            inner: self.outcome,
        }
    }

    #[getter]
    fn stderr(&self) -> &str {
        &self.stderr
    }

    #[getter]
    fn code(&self) -> Option<i32> {
        self.outcome.code()
    }

    /// Whether the process exited with code `0` (see `Outcome.exited_zero`).
    #[getter]
    fn exited_zero(&self) -> bool {
        self.outcome.code() == Some(0)
    }

    #[getter]
    fn timed_out(&self) -> bool {
        self.outcome.timed_out()
    }

    #[getter]
    fn signal(&self) -> Option<i32> {
        self.outcome.signal()
    }

    fn __repr__(&self) -> String {
        format!(
            "Finished(code={:?}, timed_out={})",
            self.outcome.code(),
            self.outcome.timed_out(),
        )
    }

    /// Value equality — the same fields (`outcome`, `stderr`) the crate's own
    /// derived `PartialEq` for `Finished` compares — not `object`'s identity
    /// comparison.
    fn __eq__(&self, other: &Self) -> bool {
        self.outcome == other.outcome && self.stderr == other.stderr
    }

    /// Consistent with `__eq__`.
    fn __hash__(&self) -> u64 {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        self.outcome.code().hash(&mut hasher);
        self.outcome.signal().hash(&mut hasher);
        self.outcome.timed_out().hash(&mut hasher);
        self.stderr.hash(&mut hasher);
        hasher.finish()
    }

    /// Pickle support: see the module doc — the `outcome` half is
    /// reconstructed via `scripted_outcome`, `stderr` carried through as-is.
    #[allow(clippy::type_complexity)]
    fn __reduce__<'py>(
        &self,
        py: Python<'py>,
    ) -> PyResult<(Py<PyAny>, (String, Option<i32>, Option<i32>, bool))> {
        let factory = py.get_type::<Self>().getattr("_unpickle")?.unbind();
        Ok((
            factory,
            (
                self.stderr.clone(),
                self.outcome.code(),
                self.outcome.signal(),
                self.outcome.timed_out(),
            ),
        ))
    }

    /// `__reduce__`'s factory: a private (leading-underscore) staticmethod, as
    /// on `Outcome` (see `PyOutcome::_unpickle`). Reconstructs the `outcome` half
    /// via `scripted_outcome`; `stderr` is carried through as-is.
    #[staticmethod]
    fn _unpickle(
        py: Python<'_>,
        stderr: String,
        code: Option<i32>,
        signal: Option<i32>,
        timed_out: bool,
    ) -> PyResult<Self> {
        let outcome = scripted_outcome(py, code, signal, timed_out)?;
        Ok(Self { outcome, stderr })
    }
}

/// Register this module's pyclasses (`ProcessResult`, `BytesResult`,
/// `RunProfile`, `Outcome`, `OutputEvent`, `Finished`) on `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyProcessResult>()?;
    m.add_class::<PyBytesResult>()?;
    m.add_class::<PyRunProfile>()?;
    m.add_class::<PyOutcome>()?;
    m.add_class::<PyOutputEvent>()?;
    m.add_class::<PyFinished>()?;
    Ok(())
}
