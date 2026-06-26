//! The `Command` builder and shell-free `Pipeline`.

use std::collections::HashMap;
use std::path::PathBuf;

use processkit::Command as PkCommand;
use processkit::Encoding;
use processkit::OutputBufferPolicy;
use processkit::OverflowMode;
use processkit::Pipeline as PkPipeline;
use processkit::Stdin as PkStdin;
use processkit::StdioMode;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::convert::{nonnegative_duration, parse_signal, positive_duration};
use crate::errors::map_err;
use crate::result::{PyBytesResult, PyProcessResult};
use crate::running::PyRunningProcess;
use crate::runtime::block_on_interruptible;

/// Map a Python stdio-mode label to the crate `StdioMode`.
fn parse_stdio_mode(mode: &str) -> PyResult<StdioMode> {
    match mode {
        "pipe" | "piped" => Ok(StdioMode::Piped),
        "inherit" => Ok(StdioMode::Inherit),
        "null" | "discard" => Ok(StdioMode::Null),
        other => Err(PyValueError::new_err(format!(
            "unknown stdio mode {other:?}; use one of: pipe, inherit, null"
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
fn parse_encoding(label: &str) -> PyResult<&'static Encoding> {
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
    /// `term`/`kill`/`int`/`hup`/`quit`/`usr1`/`usr2`.
    fn timeout_signal(&self, name: &str) -> PyResult<Self> {
        let signal = parse_signal(name)?;
        Ok(Self {
            inner: self.inner.clone().timeout_signal(signal),
        })
    }

    /// Set the exit codes treated as success — this **replaces** the default of
    /// just `0`, so pass every code you accept (e.g. `[0, 1]`). For tools whose
    /// non-zero exit is a normal result, like `grep` (`1` = no match) or `diff`
    /// (`1` = differs). Affects `run()` and `ProcessResult.is_success`;
    /// `exit_code()` (raw) and `probe()` (0/1) are unchanged. An empty sequence
    /// raises `ValueError` (it would accept nothing, which is never intended).
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
        if max_bytes.is_none() && max_lines.is_none() {
            return Err(PyValueError::new_err(
                "output_limit requires at least one of max_bytes or max_lines",
            ));
        }
        let overflow = match on_overflow {
            "drop_oldest" => OverflowMode::DropOldest,
            "drop_newest" => OverflowMode::DropNewest,
            "error" => OverflowMode::Error,
            other => {
                return Err(PyValueError::new_err(format!(
                    "unknown on_overflow {other:?}; use one of: drop_oldest, drop_newest, error"
                )))
            }
        };
        let mut policy = match max_lines {
            Some(n) => OutputBufferPolicy::bounded(n),
            None => OutputBufferPolicy::unbounded(),
        };
        if let Some(bytes) = max_bytes {
            policy = policy.with_max_bytes(bytes);
        }
        policy = policy.with_overflow(overflow);
        Ok(Self {
            inner: self.inner.clone().output_buffer(policy),
        })
    }

    /// Run to completion and capture output. A non-zero exit is data, not an
    /// error — inspect `code` / `is_success` on the result.
    fn output(&self, py: Python<'_>) -> PyResult<PyProcessResult> {
        match block_on_interruptible(py, self.inner.output_string())? {
            Ok(inner) => Ok(PyProcessResult { inner }),
            Err(err) => Err(map_err(err)),
        }
    }

    /// Run to completion and capture **raw bytes** stdout (stderr stays decoded
    /// text). Use for binary output that isn't valid UTF-8. A non-zero exit is
    /// data, returned as a `BytesResult`.
    fn output_bytes(&self, py: Python<'_>) -> PyResult<PyBytesResult> {
        match block_on_interruptible(py, self.inner.output_bytes())? {
            Ok(inner) => Ok(PyBytesResult { inner }),
            Err(err) => Err(map_err(err)),
        }
    }

    /// Require a zero exit and return stdout, trailing whitespace trimmed.
    /// Raises `NonZeroExit` (or `Timeout` / `Signalled`) otherwise.
    fn run(&self, py: Python<'_>) -> PyResult<String> {
        block_on_interruptible(py, self.inner.run())?.map_err(map_err)
    }

    /// The exit code; a timeout / signal-kill raises rather than returning a
    /// sentinel.
    fn exit_code(&self, py: Python<'_>) -> PyResult<i32> {
        block_on_interruptible(py, self.inner.exit_code())?.map_err(map_err)
    }

    /// Run a predicate command and read its exit code as a bool: `0` → `True`,
    /// `1` → `False`, anything else raises.
    fn probe(&self, py: Python<'_>) -> PyResult<bool> {
        block_on_interruptible(py, self.inner.probe())?.map_err(map_err)
    }

    /// Async counterpart of `output()`. Awaitable under asyncio; cancelling the
    /// awaiting task tears down the process tree (the run's transient job is
    /// dropped) and raises `asyncio.CancelledError`.
    fn aoutput<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match cmd.output_string().await {
                Ok(inner) => Ok(PyProcessResult { inner }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match cmd.output_bytes().await {
                Ok(inner) => Ok(PyBytesResult { inner }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    /// Async counterpart of `run()`. See `aoutput` for cancellation semantics.
    fn arun<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(
            py,
            async move { cmd.run().await.map_err(map_err) },
        )
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            cmd.exit_code().await.map_err(map_err)
        })
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(
            py,
            async move { cmd.probe().await.map_err(map_err) },
        )
    }

    /// Start the command and return a `RunningProcess` for streaming and
    /// interactive I/O. The process runs concurrently — this resolves as soon as
    /// it has spawned, not when it finishes.
    fn astart<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let cmd = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match cmd.start().await {
                Ok(running) => Ok(PyRunningProcess {
                    inner: Some(running),
                }),
                Err(err) => Err(map_err(err)),
            }
        })
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
        format!("Command({:?})", self.inner.command_line())
    }
}

/// A shell-free pipeline `a | b | c`: each stage's stdout feeds the next's
/// stdin, all in one process group, with pipefail outcome semantics.
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

    /// Set a wall-clock timeout for the whole pipeline.
    fn timeout(&self, seconds: f64) -> PyResult<Self> {
        let duration = positive_duration(seconds, "timeout")?;
        Ok(Self {
            inner: self.inner.clone().timeout(duration),
        })
    }

    /// Run the pipeline and capture the last stage's output (sync).
    fn output(&self, py: Python<'_>) -> PyResult<PyProcessResult> {
        match block_on_interruptible(py, self.inner.output_string())? {
            Ok(inner) => Ok(PyProcessResult { inner }),
            Err(err) => Err(map_err(err)),
        }
    }

    /// Run the pipeline and capture the last stage's **raw bytes** stdout (sync);
    /// for a pipeline ending in a binary producer (e.g. `... | gzip`).
    fn output_bytes(&self, py: Python<'_>) -> PyResult<PyBytesResult> {
        match block_on_interruptible(py, self.inner.output_bytes())? {
            Ok(inner) => Ok(PyBytesResult { inner }),
            Err(err) => Err(map_err(err)),
        }
    }

    /// Require success and return the last stage's trimmed stdout (sync).
    fn run(&self, py: Python<'_>) -> PyResult<String> {
        block_on_interruptible(py, self.inner.run())?.map_err(map_err)
    }

    /// The pipeline's exit code (sync).
    fn exit_code(&self, py: Python<'_>) -> PyResult<i32> {
        block_on_interruptible(py, self.inner.exit_code())?.map_err(map_err)
    }

    /// Run a predicate pipeline and read its exit code as a bool (sync).
    fn probe(&self, py: Python<'_>) -> PyResult<bool> {
        block_on_interruptible(py, self.inner.probe())?.map_err(map_err)
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match pipeline.output_string().await {
                Ok(inner) => Ok(PyProcessResult { inner }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match pipeline.output_bytes().await {
                Ok(inner) => Ok(PyBytesResult { inner }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    /// Async counterpart of `run()`.
    fn arun<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            pipeline.run().await.map_err(map_err)
        })
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            pipeline.exit_code().await.map_err(map_err)
        })
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let pipeline = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            pipeline.probe().await.map_err(map_err)
        })
    }

    fn __repr__(&self) -> String {
        format!("{:?}", self.inner)
    }
}
