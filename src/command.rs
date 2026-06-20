//! The `Command` builder and shell-free `Pipeline`.

use std::collections::HashMap;
use std::path::PathBuf;

use processkit::Command as PkCommand;
use processkit::OutputBufferPolicy;
use processkit::OverflowMode;
use processkit::Pipeline as PkPipeline;
use processkit::Stdin as PkStdin;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use crate::convert::positive_duration;
use crate::errors::map_err;
use crate::result::{PyBytesResult, PyProcessResult};
use crate::running::PyRunningProcess;
use crate::runtime::block_on_interruptible;

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
    fn new(program: PathBuf, args: Option<Vec<String>>) -> Self {
        // `PathBuf` so a `str`, `bytes`, or any `os.PathLike` is accepted —
        // matching how Python's own subprocess APIs take a program.
        let mut inner = PkCommand::new(program);
        if let Some(args) = args {
            inner = inner.args(args);
        }
        Self { inner }
    }

    fn arg(&self, arg: &str) -> Self {
        Self {
            inner: self.inner.clone().arg(arg),
        }
    }

    fn args(&self, args: Vec<String>) -> Self {
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
