//! The `Command` builder and shell-free `Pipeline`.

use std::collections::HashMap;
use std::path::PathBuf;

use processkit::Command as PkCommand;
use processkit::ParentDeathCleanup;
use processkit::Pipeline as PkPipeline;
use processkit::Stdin as PkStdin;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::cancellation::PyCancellationToken;
use crate::convert::{
    build_output_buffer_policy, build_retry_policy, is_python_writer, nonnegative_duration,
    open_tee_sink, parse_encoding, parse_line_terminator, parse_priority, parse_retry_if,
    parse_signal, parse_stdio_mode, positive_duration, PyWriterSink,
};
use crate::errors::map_err;
use crate::result::{PyBytesResult, PyProcessResult};
use crate::running::PyRunningProcess;
use crate::runtime::{block_on, drive_async};

/// A command builder. Builder methods return a new `Command`, so a configured
/// command is reusable and chains read left to right.
#[pyclass(name = "Command", module = "processkit")]
pub(crate) struct PyCommand {
    pub(crate) inner: PkCommand,
}

/// Wrap a Python callable `(str) -> None` as an `on_stdout_line`/
/// `on_stderr_line` handler. Mirrors `runner::make_invocation_callback`'s
/// infallible-bridge convention: the handler observes output as a
/// fire-and-forget side effect, so a raising callback is surfaced via the
/// unraisable hook (visible on stderr) rather than propagated across the FFI
/// boundary — a broken observer must not derail the run it was only watching.
fn make_line_callback(callback: Py<PyAny>) -> impl Fn(&str) + Send + Sync + 'static {
    move |line| {
        // `try_attach`, not `attach`: this fires from the tokio capture-pump
        // worker, which outlives the driving verb and is NOT joined at
        // `Py_Finalize` (the runtime is an immortal singleton). Once the
        // interpreter is finalizing `try_attach` returns `None`, so the line is
        // dropped as a no-op — a plain `attach` would panic/crash observing a
        // shutdown-time line. Same finalization guard as `logging.rs`'s bridge
        // (see its `try_attach` comment).
        let _ = Python::try_attach(|py| {
            if let Err(err) = callback.call1(py, (line,)) {
                err.write_unraisable(py, Some(callback.bind(py)));
            }
        });
    }
}

/// Reject `append=True` on a `stdout_tee`/`stderr_tee` call whose sink is a
/// Python writer object: `append` only tunes how a *file path* is opened
/// (truncate vs append), so it is meaningless for a writer. Rejecting it (rather
/// than silently ignoring it) keeps the option from being a confusing no-op.
fn reject_append_for_writer(append: bool) -> PyResult<()> {
    if append {
        return Err(PyValueError::new_err(
            "append=True is only meaningful for a file-path tee sink, not a Python writer object",
        ));
    }
    Ok(())
}

/// Render a `ParentDeathCleanup` capability report as a stable snake_case
/// string. Same enum-to-string convention this binding uses for the crate's
/// other `#[non_exhaustive]` enums (see `stop_reason_str` in `supervisor.rs`):
/// a private `match … -> &'static str` with every named variant spelled out and
/// pinned by a unit test, plus a catch-all so a future upstream variant can
/// never fail the build or panic at runtime.
///
/// The catch-all degrades to a distinct `"unknown"` sentinel rather than folding
/// an unrecognized scope into `"unsupported"`: the crate's enum doc flags a
/// *possible future whole-tree Linux mechanism*, so an unknown variant might
/// actually reach further than `"unsupported"` ("no cleanup at all") would
/// claim — reporting `"unknown"` refuses to under-promise a reach we can't name,
/// exactly as `stop_reason_str`'s `_ => "unknown"` does.
fn parent_death_cleanup_str(scope: ParentDeathCleanup) -> &'static str {
    match scope {
        ParentDeathCleanup::WholeTree => "whole_tree",
        ParentDeathCleanup::DirectChildOnly => "direct_child_only",
        ParentDeathCleanup::Unsupported => "unsupported",
        _ => "unknown",
    }
}

#[pymethods]
impl PyCommand {
    #[new]
    #[pyo3(signature = (program, args = None))]
    fn new(program: PathBuf, args: Option<Vec<PathBuf>>) -> Self {
        // `PathBuf` so a `str` or any `os.PathLike[str]` is accepted — for the
        // program and for each argument (so a `pathlib.Path` argument needs no
        // `str()`). `bytes` paths are not accepted (PyO3 decodes through `str`).
        let mut inner = PkCommand::new(program);
        if let Some(args) = args {
            inner = inner.args(args);
        }
        Self { inner }
    }

    fn arg(&self, arg: PathBuf) -> Self {
        Self {
            inner: self.inner.clone().arg(arg),
        }
    }

    fn args(&self, args: Vec<PathBuf>) -> Self {
        Self {
            inner: self.inner.clone().args(args),
        }
    }

    fn cwd(&self, path: PathBuf) -> Self {
        Self {
            inner: self.inner.clone().current_dir(path),
        }
    }

    /// Search this directory before `PATH` when resolving a bare-name program.
    ///
    /// Repeated calls accumulate in priority order. This only affects programs
    /// such as `"tool"`; path-form programs such as `"./tool"` or
    /// `"/opt/tool"` are left unchanged. The child's own `PATH` environment is
    /// not rewritten.
    fn prefer_local(&self, dir: PathBuf) -> Self {
        Self {
            inner: self.inner.clone().prefer_local(dir),
        }
    }

    fn env(&self, key: &str, value: &str) -> Self {
        Self {
            inner: self.inner.clone().env(key, value),
        }
    }

    /// Set several environment variables at once from a mapping.
    fn envs(&self, vars: HashMap<String, String>) -> Self {
        Self {
            inner: self.inner.clone().envs(vars),
        }
    }

    /// Remove a variable from the child's environment (drops any inherited value).
    fn env_remove(&self, key: &str) -> Self {
        Self {
            inner: self.inner.clone().env_remove(key),
        }
    }

    /// Start from an empty environment instead of inheriting the parent's; add
    /// back only what `env()` / `envs()` set. Use for reproducible or locked-down
    /// (sandboxed) children. `inherit_env()` already implies this, so pairing the
    /// two is only needed for its one extra effect: it also disables gap-filling
    /// non-allow-listed keys from the client's `default_env` / `default_env_fn`
    /// (see `inherit_env()`).
    fn env_clear(&self) -> Self {
        Self {
            inner: self.inner.clone().env_clear(),
        }
    }

    /// Inherit only the named variables from the parent's environment — this is
    /// an allow-list on top of an *implied* `env_clear()`, so a locked-down
    /// sandboxed child needs no separate `env_clear()` call. Pairing an explicit
    /// `env_clear()` with this has exactly one remaining effect: it also stops
    /// the `CliClient`'s `default_env` / `default_env_fn` from gap-filling
    /// non-allow-listed keys, which `inherit_env()` alone does not disable.
    fn inherit_env(&self, names: Vec<String>) -> Self {
        Self {
            inner: self.inner.clone().inherit_env(names),
        }
    }

    /// Feed the given bytes to the child's stdin, then close it (EOF).
    fn stdin_bytes(&self, data: Vec<u8>) -> Self {
        Self {
            inner: self.inner.clone().stdin(PkStdin::from_bytes(data)),
        }
    }

    /// Feed the given text to the child's stdin, then close it (EOF).
    fn stdin_text(&self, text: String) -> Self {
        Self {
            inner: self.inner.clone().stdin(PkStdin::from_string(text)),
        }
    }

    /// Stream the file at `path` to the child's stdin, then close it (EOF).
    /// Unlike `stdin_bytes()`, the file is never read into a Python `bytes`
    /// object or buffered whole in memory — the crate forwards it to the
    /// child in chunks on a background task, so a multi-gigabyte input (a
    /// `psql` dump, a `tar` archive, a large log fed through a filter) costs
    /// O(chunk), not O(file size).
    ///
    /// **File lifecycle — deferred, at spawn time (unlike `stdout_tee()`).**
    /// This method does not touch the filesystem: it stores `path` and opens
    /// it lazily when the command actually runs, matching the rest of the
    /// builder (`stdout_tee()`/`stderr_tee()` are the deliberate exception,
    /// since they must fail fast on an unopenable sink before any output can
    /// be lost). A `path` that doesn't exist (yet) when `stdin_file()` is
    /// called is therefore not an error. If the file is still missing or
    /// unreadable once the command spawns, the run does **not** raise
    /// `FileNotFoundError`/`PermissionError`: the crate's own error
    /// classifiers deliberately don't treat a stdin-write failure as a launch
    /// condition (the child process already spawned successfully by then), so
    /// it surfaces as the generic `ProcessError` from the run/output verb
    /// instead, with the underlying OS error folded into its message. Like
    /// `stdin_bytes()`/`stdin_text()`, the source is reusable — a `path` that
    /// exists at retry/re-run time is read again from the start each time.
    fn stdin_file(&self, path: PathBuf) -> Self {
        Self {
            inner: self.inner.clone().stdin(PkStdin::from_file(path)),
        }
    }

    /// Keep stdin piped and open for interactive writing after the process
    /// starts, via `RunningProcess.take_stdin()`.
    fn keep_stdin_open(&self) -> Self {
        Self {
            inner: self.inner.clone().keep_stdin_open(),
        }
    }

    /// Give the child this process's **own** stdin — it reads directly from
    /// whatever the parent's stdin is connected to (a terminal, a file, a pipe)
    /// instead of a crate-managed pipe. The stdin counterpart of
    /// `stdout("inherit")`/`stderr("inherit")`: the child *shares* the parent's
    /// stream rather than the crate mediating it.
    ///
    /// Reach for it when a child must talk to the real terminal —
    /// `git commit` opening `$EDITOR`, a tool prompting for a password or a
    /// yes/no confirmation, or simply forwarding the parent's piped stdin
    /// straight through. Because the child reads the parent's stdin directly,
    /// the crate neither feeds nor captures that input and there is no writer to
    /// `RunningProcess.take_stdin()` (it raises, as for a non-`keep_stdin_open`
    /// run). stdout/stderr are unaffected — capturing and streaming the child's
    /// output keep working exactly as before, so `run()`/`output()` still return
    /// its stdout.
    ///
    /// **Mutually exclusive with a mediated stdin.** Inheriting the parent's
    /// stdin cannot be combined with either way the crate would otherwise
    /// *drive* stdin — a configured source (`stdin_bytes()`/`stdin_text()`/
    /// `stdin_file()`) or `keep_stdin_open()`'s interactive pipe. Setting
    /// `inherit_stdin()` **and** one of those is a contradiction (feed the child
    /// a source *and* let it read the terminal?), so it is rejected as a
    /// `ProcessError`. The rejection happens at the **launch boundary, not when
    /// you build the `Command`**: building the conflicting combination never
    /// raises — the error surfaces from the run/output verb (`run`/`output`/
    /// `exit_code`/etc.) when the command actually launches. The same guard fires
    /// identically on the live `Runner` and the test doubles (`ScriptedRunner`),
    /// since every runner routes stdin through one shared launch seam. Drop the
    /// other stdin knob to resolve it.
    fn inherit_stdin(&self) -> Self {
        Self {
            inner: self.inner.clone().inherit_stdin(),
        }
    }

    /// Set a wall-clock timeout. On expiry the whole tree is killed; `output()`
    /// reports it as `timed_out`, while `run()` / `exit_code()` raise `Timeout`.
    fn timeout(&self, seconds: f64) -> PyResult<Self> {
        let duration = positive_duration(seconds, "timeout")?;
        Ok(Self {
            inner: self.inner.clone().timeout(duration),
        })
    }

    /// On timeout, send the terminate signal and wait this grace period before
    /// hard-killing the tree (instead of an immediate kill).
    fn timeout_grace(&self, seconds: f64) -> PyResult<Self> {
        let grace = nonnegative_duration(seconds, "timeout_grace")?;
        Ok(Self {
            inner: self.inner.clone().timeout_grace(grace),
        })
    }

    /// The signal sent first on a graceful timeout (default `term`): one of
    /// `term`/`kill`/`int`/`hup`/`quit`/`usr1`/`usr2`, or a raw platform signal
    /// number (Unix only — the crate's `Signal::Other` escape hatch).
    ///
    /// A raw number is validated as a real, deliverable signal: on Unix it must
    /// be in `1..=SIGRTMAX` (`0`, the existence probe that delivers nothing,
    /// negatives, and out-of-range values raise `ValueError`); on Windows a raw
    /// number is never deliverable and raises `Unsupported` (only the named
    /// `"kill"` works there). A `bool` raises `TypeError` — it is an `int`
    /// subtype that would otherwise silently become raw signal `1`/`0`.
    fn timeout_signal(&self, name: &Bound<'_, PyAny>) -> PyResult<Self> {
        let signal = parse_signal(name)?;
        Ok(Self {
            inner: self.inner.clone().timeout_signal(signal),
        })
    }

    /// Run **without** a timeout, and — unlike simply leaving it unset — opt out
    /// of any client-wide `CliClient` `default_timeout` gap-fill. Use this to say
    /// "this one long-running command is *deliberately* unbounded" against a
    /// client that otherwise imposes a deadline on every call (a `tail -f`, a
    /// watch loop, an interactive session). A plain `Command` (no client) is
    /// already unbounded by default, so this only matters run through a
    /// `CliClient` with a `default_timeout`. Clears a prior `timeout()` — the
    /// last of the two wins.
    fn no_timeout(&self) -> Self {
        Self {
            inner: self.inner.clone().no_timeout(),
        }
    }

    /// Like `timeout()`, but takes an `Optional[float]` — convenient when the
    /// timeout comes from config as `seconds | None`. `seconds` (a `float`) is
    /// equivalent to `timeout(seconds)` (validated the same way); `None` is
    /// equivalent to `no_timeout()` — it clears a prior `timeout()`, it does not
    /// leave the setting untouched. Last write wins against any earlier call
    /// from this family (`timeout`/`timeout_grace`/`no_timeout`).
    fn timeout_opt(&self, seconds: Option<f64>) -> PyResult<Self> {
        let timeout = match seconds {
            Some(seconds) => Some(positive_duration(seconds, "timeout_opt")?),
            None => None,
        };
        Ok(Self {
            inner: self.inner.clone().timeout_opt(timeout),
        })
    }

    /// Tear this run down (raising `Cancelled`) when `token` fires. A
    /// cancelled run is never retried — `retry()`/`Supervisor` both treat
    /// `Cancelled` as terminal, since another attempt could only fail the
    /// same way (the token stays cancelled forever). On a `Command` this
    /// **replaces** any previously set token (last write wins).
    fn cancel_on(&self, token: &PyCancellationToken) -> Self {
        Self {
            inner: self.inner.clone().cancel_on(token.inner.clone()),
        }
    }

    /// Set the exit codes treated as success — this **replaces** the default of
    /// just `0`, so pass every code you accept (e.g. `[0, 1]`). For tools whose
    /// non-zero exit is a normal result, like `grep` (`1` = no match) or `diff`
    /// (`1` = differs). Affects `run()` and the captured results' `is_success`
    /// (`ProcessResult` and `BytesResult`); `exit_code()` (raw) and `probe()`
    /// (0/1) are unchanged. An empty sequence raises `ValueError`: the crate
    /// itself treats an empty accept-set as a no-op (silently keeping the
    /// previous configuration), which would make this call a confusing silent
    /// no-op here too — reject it explicitly instead.
    fn success_codes(&self, codes: Vec<i32>) -> PyResult<Self> {
        if codes.is_empty() {
            return Err(PyValueError::new_err(
                "success_codes requires at least one code; pass the exit codes you \
                 accept (e.g. [0, 1])",
            ));
        }
        Ok(Self {
            inner: self.inner.clone().ok_codes(codes),
        })
    }

    /// Retry the run — exponential backoff, cap, and jitter — while `retry_if`
    /// accepts the resulting error. Honored only by the success-checking verbs
    /// (`run`/`exit_code`/`probe`); the non-erroring `output()`/`output_bytes()`
    /// never retry. `retry_if` is a named preset over the crate's own error
    /// accessors, not an arbitrary callable (kwargs, not a mirrored
    /// `RetryPolicy` object — see `AGENTS.md`'s config-struct convention):
    /// `"transient"` (a bare-retry-clears spawn/IO condition — interrupted,
    /// would-block, a busy resource) or `"transient_or_timeout"` (also retries
    /// a `.timeout()` expiry).
    ///
    /// `max_retries` counts retries **after** the first attempt (default `3` —
    /// up to 4 total attempts; `0` never retries). `initial_backoff` is the
    /// delay before the first retry (default 0.1s; `0` retries immediately).
    /// `multiplier` grows each successive delay (default `2.0`; `1.0` is fixed
    /// backoff — a non-finite/non-positive/sub-unit value is folded to `1.0`
    /// rather than rejected, matching the crate's own tolerance). `max_backoff`
    /// caps a single delay (default 30s). `jitter` (default `True`) spreads the
    /// actual wait uniformly over `[0, delay]` (AWS-style full jitter,
    /// decorrelating a fleet all backing off at once).
    ///
    /// Each attempt **re-executes the whole command from scratch** — only retry
    /// operations safe to repeat (a side effect that already landed before the
    /// failure would replay). A **one-shot** stdin source (`stdin_bytes()` /
    /// `stdin_text()`) can't survive a retry, so a command built with one is
    /// never retried at all — the first attempt's error returns as-is. Ignored
    /// by `Supervisor` (its own `RestartPolicy` governs keep-alive restarts —
    /// a different concern) and by `output_all`/`Pipeline`.
    #[pyo3(signature = (retry_if, *, max_retries=None, initial_backoff=None, multiplier=None, max_backoff=None, jitter=None))]
    fn retry(
        &self,
        retry_if: &str,
        max_retries: Option<u32>,
        initial_backoff: Option<f64>,
        multiplier: Option<f64>,
        max_backoff: Option<f64>,
        jitter: Option<bool>,
    ) -> PyResult<Self> {
        let policy = build_retry_policy(
            max_retries,
            initial_backoff,
            multiplier,
            max_backoff,
            jitter,
        )?;
        let classifier = parse_retry_if(retry_if)?;
        Ok(Self {
            inner: self.inner.clone().retry_with(policy, classifier),
        })
    }

    /// Explicitly opt this one command out of retrying — even when it runs
    /// through a `CliClient` configured with a `default_retry`. Use this when
    /// a specific call must never be retried (e.g. it has side effects unsafe
    /// to repeat) while the rest of the client's calls still get its default
    /// retry policy. Last write wins against any earlier `retry()`/`retry_with()`.
    fn retry_never(&self) -> Self {
        Self {
            inner: self.inner.clone().retry_never(),
        }
    }

    /// Where the child's stdout goes: `"pipe"` (capture — the default), `"inherit"`
    /// (the parent's stdout), or `"null"` (discard). Capture verbs and streaming
    /// see output only in `"pipe"` mode.
    fn stdout(&self, mode: &str) -> PyResult<Self> {
        Ok(Self {
            inner: self.inner.clone().stdout(parse_stdio_mode(mode)?),
        })
    }

    /// Where the child's stderr goes: `"pipe"` / `"inherit"` / `"null"`.
    fn stderr(&self, mode: &str) -> PyResult<Self> {
        Ok(Self {
            inner: self.inner.clone().stderr(parse_stdio_mode(mode)?),
        })
    }

    /// Decode captured stdout *and* stderr with the named encoding instead of
    /// UTF-8. `label` is a WHATWG Encoding label (e.g. `"iso-8859-1"`,
    /// `"shift_jis"`, `"windows-1251"`); common Python codec aliases (`"latin_1"`,
    /// `"utf_8"`, `"euc_jp"`, …) are accepted too and normalized to the WHATWG
    /// form. Note WHATWG `"iso-8859-1"` (and Python `"latin_1"`) decode as
    /// windows-1252. The Windows ANSI code page (`"mbcs"`/`"ansi"`) has no portable
    /// label — pass it explicitly (e.g. `"windows-1251"`). An unmappable label
    /// raises `ValueError`.
    fn encoding(&self, label: &str) -> PyResult<Self> {
        Ok(Self {
            inner: self.inner.clone().encoding(parse_encoding(label)?),
        })
    }

    /// Decode captured stdout with the named encoding (see `encoding`).
    fn stdout_encoding(&self, label: &str) -> PyResult<Self> {
        Ok(Self {
            inner: self.inner.clone().stdout_encoding(parse_encoding(label)?),
        })
    }

    /// Decode captured stderr with the named encoding (see `encoding`).
    fn stderr_encoding(&self, label: &str) -> PyResult<Self> {
        Ok(Self {
            inner: self.inner.clone().stderr_encoding(parse_encoding(label)?),
        })
    }

    /// Choose where the line pump splits **both** streams into lines. The
    /// default is `"newline"` (alias `"lf"`) — split on `\n` only, the crate's
    /// pre-1.0 behavior. Pass `"carriage_return"` (alias `"cr"`) to also treat a
    /// bare `\r` (one not immediately followed by `\n`) as a frame terminator,
    /// delivered live — the mode carriage-return progress output
    /// (`curl`/`pip`/`apt`: a bar redrawn in place with `\r`, no `\n` until the
    /// end) needs to stream one frame at a time instead of piling up into a
    /// single line that only surfaces at EOF. A `\r\n` pair still counts as one
    /// terminator (no spurious empty line), so ordinary CRLF text reads
    /// identically either way. This is the one shared notion of "a line" for
    /// `stdout_lines()`/`output_events()`, the per-line handlers, `stdout_tee`/
    /// `stderr_tee`, and `output_string` alike — set both streams at once here,
    /// or independently with `stdout_line_terminator`/`stderr_line_terminator`
    /// when only one stream carries progress output. Unknown preset raises
    /// `ValueError`.
    fn line_terminator(&self, mode: &str) -> PyResult<Self> {
        Ok(Self {
            inner: self
                .inner
                .clone()
                .line_terminator(parse_line_terminator(mode)?),
        })
    }

    /// Choose where the line pump splits **stdout** into lines (see
    /// `line_terminator`); stderr framing is left untouched.
    fn stdout_line_terminator(&self, mode: &str) -> PyResult<Self> {
        Ok(Self {
            inner: self
                .inner
                .clone()
                .stdout_line_terminator(parse_line_terminator(mode)?),
        })
    }

    /// Choose where the line pump splits **stderr** into lines (see
    /// `line_terminator`); stdout framing is left untouched. Handy when
    /// progress output lands on stderr while stdout stays newline-structured.
    fn stderr_line_terminator(&self, mode: &str) -> PyResult<Self> {
        Ok(Self {
            inner: self
                .inner
                .clone()
                .stderr_line_terminator(parse_line_terminator(mode)?),
        })
    }

    /// Tee every decoded stdout line to `sink` as it is produced — the line
    /// **plus** a trailing `\n` — while the run *also* keeps capturing the full
    /// output: the sink does not steal output from `ProcessResult.stdout`. The
    /// one-line way to "stream a log somewhere and still get the captured
    /// result", without a manual loop over `stdout_lines()`.
    ///
    /// **Two sink forms, chosen by the argument type.**
    ///
    /// - A **file path** (`str` or `os.PathLike[str]`) — teed as raw UTF-8 bytes
    ///   to that file. **Opened now, at build time** (the crate takes a concrete
    ///   async sink, not a lazy factory): created if absent and, by default,
    ///   **truncated**; pass ``append=True`` to open in append mode instead. A
    ///   path that can't be opened for writing raises immediately — the matching
    ///   `OSError` subclass (`FileNotFoundError` for a missing parent directory,
    ///   `PermissionError`, `IsADirectoryError`, …). Because the open handle is
    ///   shared across clones and re-runs (the crate holds it in an
    ///   `Arc<Mutex<…>>`), sequential re-runs of the same built command —
    ///   retries, a reused `Command`, `Supervisor` incarnations — **append** to
    ///   the one file with no delimiter; concurrent clones (pipeline stages)
    ///   **interleave**. For per-run separation, build a fresh `Command` per run.
    ///
    /// - A **Python writer** — any object with a callable `write()`
    ///   (`io.StringIO`, `sys.stderr`, a text-mode file, a logger wrapper). Each
    ///   decoded line (then `"\n"`) is passed to `write()` as a **`str`**, so this
    ///   is a text sink — a binary writer (`io.BytesIO`, a `"wb"` file) whose
    ///   `write(str)` raises `TypeError` is the wrong sink here (open it in text
    ///   mode / wrap it in `io.TextIOWrapper`). The object is discriminated by
    ///   having a callable `write` (neither `str` nor `pathlib.Path` does), and it
    ///   is **not** owned — it is never closed for you, so you keep writing to
    ///   your `sys.stderr` / open file after the run. `append` is meaningless for
    ///   a writer; passing ``append=True`` with one raises `ValueError` rather
    ///   than being silently ignored.
    ///
    /// **Async-write bridge.** Each write to a Python writer is dispatched to the
    /// runtime's blocking pool (re-acquiring the GIL there) and awaited on the
    /// capture pump — so a slow (even sleeping) `write()` applies backpressure
    /// (the pump slows, the OS pipe fills, the child blocks on its next write)
    /// without blocking the async event loop or deadlocking the runtime, exactly
    /// like the file sink.
    ///
    /// **No-op conditions (inherited from the crate).** The tee fires from the
    /// line-capture pump, so it is inert under ``stdout("inherit")`` /
    /// ``stdout("null")`` (no pump runs) and under `output_bytes()` (raw capture,
    /// no line pump). Use it with the line verbs — `output()` / `aoutput()`,
    /// `run()`, or `start()` + `stdout_lines()` / `output_events()`. A write error
    /// disables the tee for the rest of the run — the run and its captured result
    /// are unaffected — surfaced as a `tracing` warning under `enable_logging()`;
    /// a Python writer's `write()` exception is additionally reported via
    /// `sys.unraisablehook` (visible even without `enable_logging()`).
    #[pyo3(signature = (sink, *, append = false))]
    fn stdout_tee(&self, sink: &Bound<'_, PyAny>, append: bool) -> PyResult<Self> {
        let inner = if is_python_writer(sink)? {
            reject_append_for_writer(append)?;
            self.inner.clone().stdout_tee(PyWriterSink::new(sink))
        } else {
            let path: PathBuf = sink.extract()?;
            self.inner.clone().stdout_tee(open_tee_sink(&path, append)?)
        };
        Ok(Self { inner })
    }

    /// Tee every decoded stderr line to `sink` as it is produced. Same contract
    /// as `stdout_tee` — a file path (opened at build time, truncated by default
    /// or ``append``) **or** a Python writer object with a callable `write()`
    /// (fed each decoded line as a `str`, via the same blocking-pool async-write
    /// bridge, never closed for you), coexisting with capture, and inert unless
    /// stderr is piped through the line pump.
    #[pyo3(signature = (sink, *, append = false))]
    fn stderr_tee(&self, sink: &Bound<'_, PyAny>, append: bool) -> PyResult<Self> {
        let inner = if is_python_writer(sink)? {
            reject_append_for_writer(append)?;
            self.inner.clone().stderr_tee(PyWriterSink::new(sink))
        } else {
            let path: PathBuf = sink.extract()?;
            self.inner.clone().stderr_tee(open_tee_sink(&path, append)?)
        };
        Ok(Self { inner })
    }

    /// Redirect the child's stdout **straight to a file**, opened at spawn time —
    /// the child writes to the file's own descriptor, with no parent-side pump,
    /// tee, or capture buffer in between. This is the direct-redirect cousin of
    /// `stdout_tee()`: where the tee *also* captures and mirrors every decoded
    /// line, this simply hands the child the file and steps out of the way (a `>`
    /// / `>>` shell redirect, minus the shell).
    ///
    /// **API shape — one `append=` kwarg, not the crate's three spellings.** The
    /// core exposes `stdout_file` / `stdout_file_append` / `stdout_file_truncate`;
    /// this binding folds them into a single `stdout_file(path, *, append=False)`,
    /// mirroring the sibling `stdout_tee(sink, *, append=False)` it already ships.
    /// Keeping the two file sinks consistent with the tee pair — the binding's own
    /// established convention — beats a 1:1 mirror of the crate's truncate/append
    /// convenience aliases. `append=False` (the default) **creates or truncates**
    /// the file on every spawn; `append=True` **creates or appends** — the mode
    /// for a shared log across `Supervisor` incarnations / `retry()` attempts,
    /// which write to the one file with no separator.
    ///
    /// **Opened at spawn, not now (unlike `stdout_tee`).** This only stores the
    /// path — the file is opened when the command actually launches, so a path
    /// that doesn't exist yet is not an error at build time, and every re-run /
    /// retry reopens it (truncating or appending per the mode). An unopenable path
    /// (a missing parent directory, a permission denial) surfaces from the run
    /// verb when it launches, not from this builder call.
    ///
    /// **No capture — drive it with a non-capturing verb.** With stdout going to
    /// the file there is no pipe for the parent to read, so the capture/streaming
    /// verbs (`output()` / `run()` / `output_bytes()` / their `a`-twins, and
    /// `start()` + `stdout_lines()` / `output_events()`) raise `ProcessError`
    /// ("stdout is not piped … so the capture verbs have nothing to read") rather
    /// than returning silently-empty output — use `exit_code()` / `probe()` (or
    /// their async twins) instead. A later `stdout("pipe"/"inherit"/"null")`
    /// **clears** this redirect and restores the ordinary stdio mode (the crate
    /// documents the reset explicitly), keeping the builder chain composable.
    #[pyo3(signature = (path, *, append = false))]
    fn stdout_file(&self, path: PathBuf, append: bool) -> Self {
        let inner = self.inner.clone();
        Self {
            inner: if append {
                inner.stdout_file_append(path)
            } else {
                inner.stdout_file(path)
            },
        }
    }

    /// Redirect the child's stderr **straight to a file**, opened at spawn time.
    /// Same contract as `stdout_file` — the child owns the descriptor with no
    /// parent-side pump/tee/buffer, the path is opened lazily at launch (a missing
    /// path is not a build-time error), `append=False` truncates on every spawn
    /// while `append=True` appends (the shared-`Supervisor`-log mode), and a later
    /// `stderr("pipe"/"inherit"/"null")` clears the redirect and restores the
    /// normal stdio mode.
    ///
    /// Unlike `stdout_file`, this does **not** disable the capture verbs: only a
    /// non-piped *stdout* gates them, so `output()` / `run()` keep working and
    /// still return the child's stdout — stderr is simply diverted to the file and
    /// `result.stderr` comes back empty. Redirect stdout with `stdout_file` when
    /// you need the capture verbs gated too.
    #[pyo3(signature = (path, *, append = false))]
    fn stderr_file(&self, path: PathBuf, append: bool) -> Self {
        let inner = self.inner.clone();
        Self {
            inner: if append {
                inner.stderr_file_append(path)
            } else {
                inner.stderr_file(path)
            },
        }
    }

    /// Call `callback` with every decoded stdout line as it is produced — the
    /// one way to give the **synchronous** surface (`.output()`/`.run()`) live
    /// progress observation during an otherwise-blocking call, without giving
    /// up the full capture: `callback` observes the same decoded lines that
    /// land in `ProcessResult.stdout`, it does not replace or consume them.
    /// Also fires on the async verbs (`.aoutput()`/`.arun()`) and on streamed
    /// runs (`start()`/`astart()` + `stdout_lines()`/`output_events()`) — one
    /// callback, every path; it does not turn the sync surface async-only.
    ///
    /// `callback` is infallible from this binding's perspective: an exception
    /// raised inside it is surfaced via the unraisable hook
    /// (`sys.unraisablehook`) rather than propagated — a broken observer must
    /// not derail the run it only watches, and the captured result is
    /// unaffected either way.
    ///
    /// At most one handler per stream: a repeat call **replaces** the previous
    /// one (builder semantics, like `timeout()`) — compose inside a single
    /// Python callable to fan out to more than one observer.
    ///
    /// **No-op conditions (inherited from the crate, same family as
    /// `stdout_tee`).** Fires from the line-capture pump, so it is inert under
    /// `stdout("inherit")` / `stdout("null")` (no pump runs) and under
    /// `output_bytes()` (stdout is captured raw there, bypassing the line
    /// pump entirely).
    fn on_stdout_line(&self, callback: Py<PyAny>) -> Self {
        Self {
            inner: self
                .inner
                .clone()
                .on_stdout_line(make_line_callback(callback)),
        }
    }

    /// Call `callback` with every decoded stderr line as it is produced. Same
    /// contract as `on_stdout_line` — full capture unaffected, fires on sync,
    /// async, and streamed paths alike, infallible (a raising callback goes to
    /// the unraisable hook, never propagates or aborts the run), and at most
    /// one handler per stream (a repeat call replaces the previous one).
    ///
    /// Inert under `stderr("inherit")` / `stderr("null")` (no pump runs for
    /// that stream). Unlike `on_stdout_line`, this one is **not** silenced by
    /// `output_bytes()`: that verb only bypasses the *stdout* line pump for
    /// its raw-bytes capture — stderr keeps decoding through the line pump
    /// exactly as it does under `output()`, so this callback still fires.
    fn on_stderr_line(&self, callback: Py<PyAny>) -> Self {
        Self {
            inner: self
                .inner
                .clone()
                .on_stderr_line(make_line_callback(callback)),
        }
    }

    /// Tie the child's lifetime to this process: if the parent dies, the OS kills
    /// the child too (Linux `PR_SET_PDEATHSIG`; folded into the job elsewhere).
    /// Reinforces the no-orphan guarantee even without explicit teardown.
    fn kill_on_parent_death(&self) -> Self {
        Self {
            inner: self.inner.clone().kill_on_parent_death(),
        }
    }

    /// The scope of parent-death cleanup this build's platform actually achieves
    /// when the owner dies **abruptly** (a `SIGKILL` or crash, where graceful
    /// `Drop` teardown never runs), as a stable string:
    ///
    /// - `"whole_tree"` — Windows: the kernel closes the Job Object handle on
    ///   owner death and kill-on-close reaps the direct child and every
    ///   descendant.
    /// - `"direct_child_only"` — Linux: `PR_SET_PDEATHSIG` reaches only the
    ///   direct child; with the owner gone nothing tears the surviving
    ///   grandchildren down.
    /// - `"unsupported"` — macOS / the BSDs: no `pdeathsig` equivalent, so an
    ///   abrupt owner death triggers no cleanup at all.
    ///
    /// An honest capability report, not a request — it lets a caller state the
    /// real reach of `kill_on_parent_death()` (best-effort on Unix) instead of
    /// overpromising a whole-tree guarantee the OS cannot keep. It covers only
    /// the abrupt-death path: ordinary graceful teardown still kills the whole
    /// tree on every platform regardless.
    ///
    /// Exposed as a `staticmethod` because it mirrors the crate's associated
    /// function `Command::kill_on_parent_death_scope()` 1:1: the value is fixed
    /// per target at build time and does **not** depend on instance/config or on
    /// whether `kill_on_parent_death()` was called, so call it on the class or
    /// any instance for the same answer.
    #[staticmethod]
    fn kill_on_parent_death_scope() -> &'static str {
        parent_death_cleanup_str(PkCommand::kill_on_parent_death_scope())
    }

    /// Windows: don't allocate a console window for the child. No-op elsewhere.
    fn create_no_window(&self) -> Self {
        Self {
            inner: self.inner.clone().create_no_window(),
        }
    }

    /// Windows: opt in to a **graceful teardown** — at a graceful timeout
    /// (`timeout_grace`) or a `ProcessGroup` shutdown, send the direct child a
    /// console `CTRL_BREAK` before the grace window, giving a console child (a
    /// CLI, Node, Python, or Go service that installs a `CTRL_BREAK` handler) a
    /// chance to flush and exit cleanly ahead of the hard `TerminateJobObject`
    /// fallback. Without it Windows has no soft-signal tier and a graceful
    /// timeout collapses straight to an atomic Job Object kill; any survivor
    /// past the grace is still hard-killed, so containment is never weakened.
    ///
    /// **Boundaries (from the crate).** *Console-only* — the event travels the
    /// console this process shares with the child, so a child spawned
    /// `create_no_window()` (or otherwise detached) shares no console, never
    /// receives it, and simply rides the grace to the hard kill; a GUI/service
    /// parent with no console of its own can't deliver it either. It is
    /// `CTRL_BREAK`, **not** `CTRL_C` (the new process group disables `CTRL_C`),
    /// and `timeout_signal` (the Unix signal choice) does not apply. Only the
    /// **direct child** is addressed — its own descendants receive it via the
    /// shared console/group, but an `adopt`ed process (not spawned here) is not,
    /// and falls back to the hard kill. **No-op off Windows**: Unix's graceful
    /// tier already sends a real signal, so this builder does nothing there
    /// (unlike the POSIX-only `uid`/`gid`/`groups`/`setsid`/`umask`, which raise
    /// `Unsupported` off-platform rather than silently no-op'ing).
    fn windows_graceful_ctrl_break(&self) -> Self {
        Self {
            inner: self.inner.clone().windows_graceful_ctrl_break(),
        }
    }

    /// POSIX: run the child as this user id (drop privileges). On a non-POSIX
    /// platform the run raises `Unsupported` — a requested privilege drop is
    /// never silently skipped.
    fn uid(&self, uid: u32) -> Self {
        Self {
            inner: self.inner.clone().uid(uid),
        }
    }

    /// POSIX: run the child as this group id. On a non-POSIX platform the run
    /// raises `Unsupported`.
    fn gid(&self, gid: u32) -> Self {
        Self {
            inner: self.inner.clone().gid(gid),
        }
    }

    /// POSIX: set the child's supplementary group ids. On a non-POSIX platform
    /// the run raises `Unsupported`.
    fn groups(&self, gids: Vec<u32>) -> Self {
        Self {
            inner: self.inner.clone().groups(gids),
        }
    }

    /// POSIX: start the child in a new session (`setsid`). On a non-POSIX
    /// platform the run raises `Unsupported`.
    fn setsid(&self) -> Self {
        Self {
            inner: self.inner.clone().setsid(),
        }
    }

    /// POSIX: set the child's file-mode creation mask (`umask`). On a
    /// non-POSIX platform the run raises `Unsupported`.
    fn umask(&self, mask: u32) -> Self {
        Self {
            inner: self.inner.clone().umask(mask),
        }
    }

    /// Set the child's CPU-scheduling priority: one of `"idle"`,
    /// `"below_normal"`, `"normal"`, `"above_normal"`, `"high"` — a direct
    /// snake_case mirror of the crate's `Priority` variants. Unix: applied via
    /// `setpriority`/`nice` through the same `pre_exec` seam as `uid`/`gid`/
    /// `groups`/`setsid`/`umask`. Windows: OR'd into the process-creation
    /// priority class, alongside `create_no_window`.
    ///
    /// Unlike the privilege/POSIX-only knobs above, `priority` is supported on
    /// **both** platform families and never raises `Unsupported`. On Unix,
    /// `"high"`, `"above_normal"`, and `"normal"` under a positive-niced parent
    /// raise priority relative to the inherited value. Lowering `nice` below
    /// its inherited value needs `CAP_SYS_NICE` (Linux), root, or an equivalent
    /// privilege elsewhere;
    /// without it the OS refuses the change and the run raises
    /// `PermissionDenied` (never a silent downgrade to a lower priority) —
    /// Windows needs no special privilege for its `HIGH_PRIORITY_CLASS`.
    /// Last-write-wins, like `timeout`.
    fn priority(&self, level: &str) -> PyResult<Self> {
        let priority = parse_priority(level)?;
        Ok(Self {
            inner: self.inner.clone().priority(priority),
        })
    }

    /// Cap how much captured output is retained. Pass at least one of
    /// `max_bytes` / `max_lines`. To bound the parent's *memory* against an
    /// untrusted child, use `max_bytes` — a `max_lines`-only cap does not, since
    /// a single newline-free flood is one (unbounded) line. `on_overflow`
    /// decides what happens at the cap: `"drop_oldest"` keeps the most recent
    /// output, `"drop_newest"` keeps the earliest, `"error"` raises
    /// `OutputTooLarge`.
    ///
    /// A `max_lines` cap applies to line-captured output (`output()` / streamed
    /// `finish()`) only — raw bytes have no line count, so it never bounds the
    /// stdout of `output_bytes()`. A `max_bytes` cap applies to *both* that
    /// line-captured output **and** the raw stdout of `output_bytes()` /
    /// `aoutput_bytes()` (since processkit 2.1.0 — earlier the byte ceiling
    /// bounded only the line-pumped stderr and raw stdout was always unbounded).
    /// Under `on_overflow="error"` an `output_bytes()` run over the byte cap
    /// raises `OutputTooLarge` (with `max_lines=None`); under a drop mode its
    /// retained bytes are bounded to a head/tail with `BytesResult.truncated`
    /// set. This carries through every inherited `output_bytes` consumer
    /// (`CliClient`, `Pipeline`, `RunningProcess`, `ProcessGroup`, the runner
    /// doubles) that runs a `Command` built with this policy.
    #[pyo3(signature = (*, max_bytes=None, max_lines=None, on_overflow="drop_oldest"))]
    fn output_limit(
        &self,
        max_bytes: Option<usize>,
        max_lines: Option<usize>,
        on_overflow: &str,
    ) -> PyResult<Self> {
        let policy = build_output_buffer_policy(max_bytes, max_lines, on_overflow, "output_limit")?;
        Ok(Self {
            inner: self.inner.clone().output_buffer(policy),
        })
    }

    /// Run to completion and capture output. A non-zero exit is data, not an
    /// error — inspect `code` / `is_success` on the result.
    fn output(&self, py: Python<'_>) -> PyResult<PyProcessResult> {
        block_on(py, self.inner.output_string()).map(PyProcessResult::from)
    }

    /// Run to completion and capture **raw bytes** stdout (stderr stays decoded
    /// text). Use for binary output that isn't valid UTF-8. A non-zero exit is
    /// data, returned as a `BytesResult`.
    fn output_bytes(&self, py: Python<'_>) -> PyResult<PyBytesResult> {
        block_on(py, self.inner.output_bytes()).map(PyBytesResult::from)
    }

    /// Require a zero exit and return stdout, trailing whitespace trimmed.
    /// Raises `NonZeroExit` (or `Timeout` / `Signalled`) otherwise.
    fn run(&self, py: Python<'_>) -> PyResult<String> {
        block_on(py, self.inner.run())
    }

    /// The exit code; a timeout / signal-kill raises rather than returning a
    /// sentinel.
    fn exit_code(&self, py: Python<'_>) -> PyResult<i32> {
        block_on(py, self.inner.exit_code())
    }

    /// Run a predicate command and read its exit code as a bool: `0` → `True`,
    /// `1` → `False`, anything else raises.
    fn probe(&self, py: Python<'_>) -> PyResult<bool> {
        block_on(py, self.inner.probe())
    }

    /// Resolve this command's `program` to a concrete executable path **without
    /// launching it** — a spawn-free preflight ("is this tool installed?") with
    /// no side effects. Unlike `probe()` (which actually runs the tool), this
    /// only *locates* it: no process is ever started.
    ///
    /// Resolution reuses the crate's own launch-path logic — not a second copy —
    /// so it is byte-for-byte what a real run of this same command would spawn: a
    /// bare name is searched in this command's `prefer_local()` directories first
    /// (in priority order), then the effective `PATH`, honoring PATHEXT on
    /// Windows and the execute bit on Unix; a path-form program (`"./tool"`, an
    /// absolute path) is probed directly. When the command has relocated the
    /// child's `PATH` (`env()`/`env_remove()` of `PATH`, `env_clear()`,
    /// `inherit_env()`), the lookup runs against that *effective child* `PATH`,
    /// so the preflight never disagrees with what the spawn would actually find.
    ///
    /// Returns the resolved **absolute** path as a `str`. Synchronous and cheap
    /// (a few `stat`s); no tokio runtime is required, so — unlike the run verbs —
    /// it takes no `py` handle. On a miss raises `ProcessNotFound` (also a
    /// `FileNotFoundError`), whose `searched` field lists the directories checked
    /// (`prefer_local` first, then `PATH`) — the same error, with the same
    /// diagnostic, a real run would raise. There is deliberately no
    /// `a`-prefixed async twin: the probe is synchronous and needs no runtime.
    fn resolve_program(&self) -> PyResult<String> {
        self.inner
            .resolve_program()
            .map(|path| path.to_string_lossy().into_owned())
            .map_err(map_err)
    }

    /// Async counterpart of `output()`. Awaitable under asyncio; cancelling the
    /// awaiting task tears down the process tree (the run's transient job is
    /// dropped) and raises `asyncio.CancelledError`.
    fn aoutput<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        drive_async(py, async move {
            cmd.output_string().await.map(PyProcessResult::from)
        })
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        drive_async(py, async move {
            cmd.output_bytes().await.map(PyBytesResult::from)
        })
    }

    /// Async counterpart of `run()`. See `aoutput` for cancellation semantics.
    fn arun<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        drive_async(py, async move { cmd.run().await })
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        drive_async(py, async move { cmd.exit_code().await })
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        drive_async(py, async move { cmd.probe().await })
    }

    /// Start the command and return a `RunningProcess` for streaming and
    /// interactive I/O. The process runs concurrently — this returns as soon as
    /// it has spawned, not when it finishes. Sync counterpart of `astart()`.
    fn start(&self, py: Python<'_>) -> PyResult<PyRunningProcess> {
        block_on(py, self.inner.start()).map(PyRunningProcess::from)
    }

    /// Start the command and return a `RunningProcess` for streaming and
    /// interactive I/O. The process runs concurrently — this resolves as soon as
    /// it has spawned, not when it finishes.
    fn astart<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        drive_async(
            py,
            async move { cmd.start().await.map(PyRunningProcess::from) },
        )
    }

    /// Exempt this command, **as a pipeline stage**, from pipefail attribution:
    /// its unclean exit (non-zero code, signal kill — including `SIGPIPE` — or
    /// its own per-stage `timeout()` kill) is skipped when the chain decides
    /// what to report, and never shields a *checked* stage's failure. The
    /// motivating pattern is `producer | head -1`: the consumer exits early,
    /// the producer dies of `SIGPIPE`, and without this marker strict pipefail
    /// reports that perfectly normal death as the chain's failure. Outside a
    /// `Pipeline` this is a no-op: a single run's status is already plain data
    /// in its `ProcessResult`, and `ensure_success()` stays opt-in.
    fn unchecked_in_pipe(&self) -> Self {
        Self {
            inner: self.inner.clone().unchecked_in_pipe(),
        }
    }

    /// The program to launch.
    #[getter]
    fn program(&self) -> String {
        self.inner.program().to_string_lossy().into_owned()
    }

    /// The arguments, in order. Named `arguments`, not `args` — that name is
    /// already the builder method that *appends* args.
    #[getter]
    fn arguments(&self) -> Vec<String> {
        self.inner
            .arguments()
            .iter()
            .map(|arg| arg.to_string_lossy().into_owned())
            .collect()
    }

    /// Render this command as a single shell-quoted line for **display** — logs,
    /// error messages, a dry-run echo. Quoting is per-platform (POSIX
    /// single-quote / Windows double-quote) and is for readability, **not
    /// execution**: this never invokes a shell, and the rendering is not
    /// guaranteed to round-trip through one. Do **not** feed the output back to
    /// a shell to re-run the command. Includes the arguments, which may carry
    /// secrets (a `--token=…` flag) — unlike `__repr__` (redacted), this is
    /// opt-in: render it only into a sink you control.
    fn command_line(&self) -> String {
        self.inner.command_line()
    }

    /// Pipe this command's stdout into `other`'s stdin, returning a `Pipeline`.
    /// Equivalent to `self | other`.
    fn pipe(&self, other: &PyCommand) -> PyPipeline {
        PyPipeline {
            inner: self.inner.clone().pipe(other.inner.clone()),
        }
    }

    fn __or__(&self, other: &PyCommand) -> PyPipeline {
        self.pipe(other)
    }

    fn __repr__(&self) -> String {
        // Use the crate's redacted `Debug` (program + arg COUNT + env NAMES, never
        // argv/env values) — a repr is emitted everywhere (logging `%r`, f-strings,
        // tracebacks), so it must not leak secrets passed as arguments. The full
        // command line stays behind the crate's explicit `command_line()` escape
        // hatch, not the default repr.
        format!("{:?}", self.inner)
    }
}

/// A shell-free pipeline `a | b | c`: each stage's stdout feeds the next's
/// stdin, all in one process group, with pipefail outcome semantics.
///
/// By design, no `start`/`astart`: the crate's own `Pipeline` has no such
/// method — a pipeline is inherently a *whole-chain* verb (the outcome/
/// attribution logic only makes sense once every stage has run), so there is
/// no natural "handle to a live, still-running chain" to hand back the way a
/// single `Command.start()` returns a `RunningProcess`. Stream an individual
/// stage's own output by `start()`ing that one `Command` directly instead.
#[pyclass(name = "Pipeline", module = "processkit")]
pub(crate) struct PyPipeline {
    inner: PkPipeline,
}

#[pymethods]
impl PyPipeline {
    /// Extend the pipeline with another stage. Equivalent to `self | other`.
    fn pipe(&self, other: &PyCommand) -> Self {
        Self {
            inner: self.inner.clone().pipe(other.inner.clone()),
        }
    }

    fn __or__(&self, other: &PyCommand) -> Self {
        self.pipe(other)
    }

    /// Tear the whole chain down (raising `Cancelled`) when `token` fires.
    /// **Gap-fill**, not override (unlike `Command.cancel_on`): a stage that
    /// already has its own explicit token keeps it; this only fills stages
    /// that don't.
    fn cancel_on(&self, token: &PyCancellationToken) -> Self {
        Self {
            inner: self.inner.clone().cancel_on(token.inner.clone()),
        }
    }

    /// Set a wall-clock timeout for the whole pipeline.
    fn timeout(&self, seconds: f64) -> PyResult<Self> {
        let duration = positive_duration(seconds, "timeout")?;
        Ok(Self {
            inner: self.inner.clone().timeout(duration),
        })
    }

    /// Run the pipeline and capture the last stage's output (sync).
    fn output(&self, py: Python<'_>) -> PyResult<PyProcessResult> {
        block_on(py, self.inner.output_string()).map(PyProcessResult::from)
    }

    /// Run the pipeline and capture the last stage's **raw bytes** stdout (sync);
    /// for a pipeline ending in a binary producer (e.g. `... | gzip`).
    fn output_bytes(&self, py: Python<'_>) -> PyResult<PyBytesResult> {
        block_on(py, self.inner.output_bytes()).map(PyBytesResult::from)
    }

    /// Require success and return the last stage's trimmed stdout (sync).
    fn run(&self, py: Python<'_>) -> PyResult<String> {
        block_on(py, self.inner.run())
    }

    /// The pipeline's exit code (sync).
    fn exit_code(&self, py: Python<'_>) -> PyResult<i32> {
        block_on(py, self.inner.exit_code())
    }

    /// Run a predicate pipeline and read its exit code as a bool (sync).
    fn probe(&self, py: Python<'_>) -> PyResult<bool> {
        block_on(py, self.inner.probe())
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        drive_async(py, async move {
            pipeline.output_string().await.map(PyProcessResult::from)
        })
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        drive_async(py, async move {
            pipeline.output_bytes().await.map(PyBytesResult::from)
        })
    }

    /// Async counterpart of `run()`.
    fn arun<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        drive_async(py, async move { pipeline.run().await })
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        drive_async(py, async move { pipeline.exit_code().await })
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        drive_async(py, async move { pipeline.probe().await })
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.inner)
    }
}

/// Resolve `program` to a concrete executable path **without launching it** — a
/// spawn-free, side-effect-free preflight ("is this tool installed?"), the
/// module-level shim over `Command(program).resolve_program()`.
///
/// A bare name is looked up on `PATH`, honoring PATHEXT on Windows and the
/// execute bit on Unix; a path-form `program` (`"./tool"`, an absolute path) is
/// probed directly. The lookup reuses the crate's own launch-path logic, so a
/// hit is exactly what a real run would spawn and a miss is exactly the
/// `ProcessNotFound` (also a `FileNotFoundError`) a real run would raise, with
/// the same `searched` diagnostic. Returns the resolved **absolute** path as a
/// `str`.
///
/// This module function searches only the process `PATH`. To honor a
/// `prefer_local()` directory or a relocated child `PATH`, build a `Command`
/// (or a `CliClient`) and call its `resolve_program()` instead. Synchronous and
/// cheap (a few `stat`s); no tokio runtime is required.
#[pyfunction]
fn which(program: PathBuf) -> PyResult<String> {
    // Fully-qualified `processkit::which` (not a `use`) to avoid clashing with
    // this local `#[pyfunction] which`. `PathBuf` satisfies the crate's
    // `impl AsRef<OsStr>`, and accepts a `str` or any `os.PathLike[str]` from
    // Python, matching `Command`'s own program argument.
    processkit::which(program)
        .map(|path| path.to_string_lossy().into_owned())
        .map_err(map_err)
}

/// Register this module's pyclasses (`Command`, `Pipeline`) and the module-level
/// `which` function on `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCommand>()?;
    m.add_class::<PyPipeline>()?;
    m.add_function(pyo3::wrap_pyfunction!(which, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    // Mirrors `supervisor.rs`'s `stop_reason_str_covers_every_variant`: pin the
    // enum-to-string mapping so a renamed/repurposed variant string is caught
    // here, and the `#[non_exhaustive]` catch-all can never silently swallow one
    // of the three variants that exist today.
    #[test]
    fn parent_death_cleanup_str_covers_every_variant() {
        let cases = [
            (ParentDeathCleanup::WholeTree, "whole_tree"),
            (ParentDeathCleanup::DirectChildOnly, "direct_child_only"),
            (ParentDeathCleanup::Unsupported, "unsupported"),
        ];
        for (scope, expected) in cases {
            assert_eq!(parent_death_cleanup_str(scope), expected, "{scope:?}");
        }
    }
}
