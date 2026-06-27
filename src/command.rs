//! The `Command` builder and shell-free `Pipeline`.

use std::collections::HashMap;
use std::path::PathBuf;

use processkit::Command as PkCommand;
use processkit::Pipeline as PkPipeline;
use processkit::Stdin as PkStdin;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::cancellation::PyCancellationToken;
use crate::convert::{
    build_output_buffer_policy, build_retry_policy, nonnegative_duration, parse_encoding,
    parse_retry_if, parse_signal, parse_stdio_mode, positive_duration,
};
use crate::result::{PyBytesResult, PyProcessResult};
use crate::running::PyRunningProcess;
use crate::runtime::{block_on, drive_async};

/// A command builder. Builder methods return a new `Command`, so a configured
/// command is reusable and chains read left to right.
#[pyclass(name = "Command", module = "processkit")]
pub(crate) struct PyCommand {
    pub(crate) inner: PkCommand,
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
    /// (sandboxed) children.
    fn env_clear(&self) -> Self {
        Self {
            inner: self.inner.clone().env_clear(),
        }
    }

    /// Inherit only the named variables from the parent's environment — pair with
    /// `env_clear()` to build a locked-down allowlist for a sandboxed child.
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

    /// Keep stdin piped and open for interactive writing after the process
    /// starts, via `RunningProcess.take_stdin()`.
    fn keep_stdin_open(&self) -> Self {
        Self {
            inner: self.inner.clone().keep_stdin_open(),
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

    /// Tie the child's lifetime to this process: if the parent dies, the OS kills
    /// the child too (Linux `PR_SET_PDEATHSIG`; folded into the job elsewhere).
    /// Reinforces the no-orphan guarantee even without explicit teardown.
    fn kill_on_parent_death(&self) -> Self {
        Self {
            inner: self.inner.clone().kill_on_parent_death(),
        }
    }

    /// Windows: don't allocate a console window for the child. No-op elsewhere.
    fn create_no_window(&self) -> Self {
        Self {
            inner: self.inner.clone().create_no_window(),
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

    /// Cap how much captured output is retained. Pass at least one of
    /// `max_bytes` / `max_lines`. To bound the parent's *memory* against an
    /// untrusted child, use `max_bytes` — a `max_lines`-only cap does not, since
    /// a single newline-free flood is one (unbounded) line. `on_overflow`
    /// decides what happens at the cap: `"drop_oldest"` keeps the most recent
    /// output, `"drop_newest"` keeps the earliest, `"error"` raises
    /// `OutputTooLarge`. The cap applies to line-captured output (`output()` /
    /// streamed `finish()`); raw `output_bytes()` stdout is never line-capped
    /// (only its stderr is) — bound a flooding child with a `timeout` instead.
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

/// Register this module's pyclasses (`Command`, `Pipeline`) on `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCommand>()?;
    m.add_class::<PyPipeline>()?;
    Ok(())
}
