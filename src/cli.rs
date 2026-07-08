//! A typed CLI wrapper: a program plus default timeout/env, with run verbs that
//! take just the per-call arguments. Convenient for wrapping a tool (git, docker)
//! you call repeatedly with the same defaults.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use processkit::CliClient as PkCliClient;
use processkit::Command as PkCommand;
use processkit::JobRunner;
use processkit::ProcessRunner;
use pyo3::prelude::*;

use crate::cancellation::PyCancellationToken;
use crate::command::PyCommand;
use crate::convert::{build_retry_policy, parse_retry_if, positive_duration};
use crate::result::{PyBytesResult, PyProcessResult};
use crate::runner::extract_runner;
use crate::runtime::{block_on, drive_async};

/// Either the per-call `args` list, or a fully-customized `Command` built via
/// `CliClient.command(args)` and further chained (`.timeout(...)`, `.stdin(...)`,
/// …) before being run — the Python-side dispatch for the crate's
/// `IntoCommand`, which our binding can't stay generic over across an FFI
/// boundary (PyO3 methods take concrete Python types, not a Rust trait
/// parameter). Either way the client's own defaults (timeout/env/retry/cancel)
/// still gap-fill in, exactly like the crate's `IntoCommand` impls: a fresh
/// `command()` (no settings) gets every default, while a caller-customized one
/// keeps its own explicit settings and only has the gaps filled.
enum ClientCall {
    // `PathBuf`, not `String` — unifies the argv element typing with
    // `Command`'s own `arg`/`args` (`str` or any `os.PathLike[str]`), instead
    // of a str-only surface here and a path-accepting one there.
    Args(Vec<PathBuf>),
    // Boxed: `PkCommand` is much larger than `Vec<PathBuf>`, and clippy's
    // `large_enum_variant` flags the resulting size gap otherwise.
    Cmd(Box<PkCommand>),
}

impl ClientCall {
    fn from_py(call: &Bound<'_, PyAny>) -> PyResult<Self> {
        if let Ok(cmd) = call.cast::<PyCommand>() {
            // `try_borrow`, not the panicking `borrow`: a concurrent access to
            // this `Command` handle from another thread surfaces as a clean
            // `PyErr`, not a `PanicException` across the FFI boundary.
            return Ok(Self::Cmd(Box::new(cmd.try_borrow()?.inner.clone())));
        }
        Ok(Self::Args(call.extract()?))
    }
}

/// Wrap a Python zero-arg callable as a `CliClient.default_env_fn` resolver.
/// The crate's resolver is infallible (`Fn() -> V`, no `Result`) and expected
/// to fall back internally rather than error — a raising or non-`str`-
/// returning callback can't honor that contract, so (like
/// `supervisor::make_stop_predicate`'s `stop_when`) the failure is surfaced via
/// the unraisable hook (visible on stderr, not silently swallowed) and the
/// resolved value falls back to an empty string rather than panicking the
/// command-build path.
fn make_env_resolver(callback: Py<PyAny>) -> impl Fn() -> String + Send + Sync + 'static {
    move || {
        Python::attach(|py| {
            match callback
                .call0(py)
                .and_then(|value| value.extract::<String>(py))
            {
                Ok(resolved) => resolved,
                Err(err) => {
                    err.write_unraisable(py, Some(callback.bind(py)));
                    String::new()
                }
            }
        })
    }
}

/// A program bound to default timeout/environment/retry, run with the real
/// `Runner` by default, or an injected `runner=` (a `ScriptedRunner` and
/// friends, for testable code with no real spawns).
#[pyclass(name = "CliClient", module = "processkit")]
pub(crate) struct PyCliClient {
    // `CliClient` is `Clone` (since 1.1.0), so the async verbs clone an owned
    // client to hold across the await — no extra indirection beyond the `Arc`
    // the type-erased runner already needs. A clone shares the same default
    // cancellation token (the correct shared-token semantic).
    inner: PkCliClient<Arc<dyn ProcessRunner + Send + Sync>>,
}

#[pymethods]
impl PyCliClient {
    #[new]
    #[pyo3(signature = (
        program,
        *,
        default_timeout=None,
        default_env=None,
        default_env_remove=None,
        default_env_fn=None,
        default_retry_if=None,
        default_max_retries=None,
        default_initial_backoff=None,
        default_multiplier=None,
        default_max_backoff=None,
        default_jitter=None,
        default_cancel_on=None,
        runner=None,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        py: Python<'_>,
        program: PathBuf,
        default_timeout: Option<f64>,
        default_env: Option<HashMap<String, String>>,
        default_env_remove: Option<Vec<String>>,
        default_env_fn: Option<HashMap<String, Py<PyAny>>>,
        default_retry_if: Option<&str>,
        default_max_retries: Option<u32>,
        default_initial_backoff: Option<f64>,
        default_multiplier: Option<f64>,
        default_max_backoff: Option<f64>,
        default_jitter: Option<bool>,
        default_cancel_on: Option<&PyCancellationToken>,
        runner: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        // Reject a non-callable `default_env_fn` value up front, before any
        // other constructor side effect (runner creation, `PkCliClient`
        // construction): a typo'd `default_env_fn={"X": "not a callback"}`
        // would otherwise only surface as a silently-empty env var, once per
        // command build, via `make_env_resolver`'s unraisable-hook fallback
        // (that fallback stays for genuine runtime failures of a valid
        // callable — this is strictly an earlier, louder rejection of an
        // invalid one).
        if let Some(resolvers) = &default_env_fn {
            for (key, callback) in resolvers {
                let bound = callback.bind(py);
                if !bound.is_callable() {
                    let described = bound
                        .repr()
                        .map(|repr| repr.to_string())
                        .unwrap_or_else(|_| "<unrepr-able value>".to_string());
                    return Err(pyo3::exceptions::PyTypeError::new_err(format!(
                        "default_env_fn[{key:?}] is not callable: {described}"
                    )));
                }
            }
        }
        // `CliClient::new` only exists for `CliClient<JobRunner>`; since this
        // binding's field is always the type-erased `Arc<dyn ProcessRunner +
        // Send + Sync>`, build the runner value first (real by default) and
        // always go through `with_runner`.
        let runner: Arc<dyn ProcessRunner + Send + Sync> = match runner {
            Some(obj) => extract_runner(obj)?,
            None => Arc::new(JobRunner::new()),
        };
        let mut client = PkCliClient::with_runner(program.as_os_str(), runner);
        if let Some(seconds) = default_timeout {
            client = client.default_timeout(positive_duration(seconds, "default_timeout")?);
        }
        if let Some(env) = default_env {
            for (key, value) in env {
                client = client.default_env(key, value);
            }
        }
        if let Some(keys) = default_env_remove {
            for key in keys {
                client = client.default_env_remove(key);
            }
        }
        if let Some(resolvers) = default_env_fn {
            for (key, callback) in resolvers {
                client = client.default_env_fn(key, make_env_resolver(callback));
            }
        }
        if let Some(token) = default_cancel_on {
            client = client.default_cancel_on(token.inner.clone());
        }
        // `default_retry_if` is the opt-in gate — the retry-tuning knobs below
        // only apply when it's set (matching `Command.retry()`'s own required
        // `retry_if`); setting a tuning knob without it is a clear misuse, not
        // a silently-ignored no-op.
        match default_retry_if {
            Some(retry_if) => {
                let policy = build_retry_policy(
                    default_max_retries,
                    default_initial_backoff,
                    default_multiplier,
                    default_max_backoff,
                    default_jitter,
                )?;
                let classifier = parse_retry_if(retry_if)?;
                client = client.default_retry(policy, classifier);
            }
            None => {
                if default_max_retries.is_some()
                    || default_initial_backoff.is_some()
                    || default_multiplier.is_some()
                    || default_max_backoff.is_some()
                    || default_jitter.is_some()
                {
                    return Err(pyo3::exceptions::PyValueError::new_err(
                        "default_retry_if is required when tuning the retry policy \
                         (default_max_retries=/default_initial_backoff=/default_multiplier=/\
                         default_max_backoff=/default_jitter=) — pass \"transient\" or \
                         \"transient_or_timeout\"",
                    ));
                }
            }
        }
        Ok(Self { inner: client })
    }

    /// A `Command` for `program <args>`, the client's defaults (timeout/env/
    /// retry/cancel) pre-applied — chain more builders (`.timeout(...)`,
    /// `.stdin_text(...)`, …) for a customized one-off call, then pass it to
    /// `run()`/`output()`/… instead of a plain arg list. An explicit setting on
    /// the returned `Command` always wins over the client's default; only the
    /// gaps are filled either way.
    fn command(&self, args: Vec<PathBuf>) -> PyCommand {
        PyCommand {
            inner: self.inner.command(args),
        }
    }

    /// Run with the given args, or a `Command` from `command()`; require a
    /// zero exit and return trimmed stdout.
    fn run(&self, py: Python<'_>, call: &Bound<'_, PyAny>) -> PyResult<String> {
        match ClientCall::from_py(call)? {
            ClientCall::Args(args) => block_on(py, self.inner.run(args)),
            ClientCall::Cmd(cmd) => block_on(py, self.inner.run(*cmd)),
        }
    }

    /// Run with the given args, or a `Command` from `command()`, and capture
    /// output (a non-zero exit is data).
    fn output(&self, py: Python<'_>, call: &Bound<'_, PyAny>) -> PyResult<PyProcessResult> {
        match ClientCall::from_py(call)? {
            ClientCall::Args(args) => block_on(py, self.inner.output_string(args)),
            ClientCall::Cmd(cmd) => block_on(py, self.inner.output_string(*cmd)),
        }
        .map(PyProcessResult::from)
    }

    /// Run with the given args, or a `Command` from `command()`, and capture
    /// raw-bytes stdout.
    fn output_bytes(&self, py: Python<'_>, call: &Bound<'_, PyAny>) -> PyResult<PyBytesResult> {
        match ClientCall::from_py(call)? {
            ClientCall::Args(args) => block_on(py, self.inner.output_bytes(args)),
            ClientCall::Cmd(cmd) => block_on(py, self.inner.output_bytes(*cmd)),
        }
        .map(PyBytesResult::from)
    }

    /// Run with the given args, or a `Command` from `command()`, and return
    /// the exit code.
    fn exit_code(&self, py: Python<'_>, call: &Bound<'_, PyAny>) -> PyResult<i32> {
        match ClientCall::from_py(call)? {
            ClientCall::Args(args) => block_on(py, self.inner.exit_code(args)),
            ClientCall::Cmd(cmd) => block_on(py, self.inner.exit_code(*cmd)),
        }
    }

    /// Run a predicate call (args, or a `Command` from `command()`) and read
    /// its exit code as a bool.
    fn probe(&self, py: Python<'_>, call: &Bound<'_, PyAny>) -> PyResult<bool> {
        match ClientCall::from_py(call)? {
            ClientCall::Args(args) => block_on(py, self.inner.probe(args)),
            ClientCall::Cmd(cmd) => block_on(py, self.inner.probe(*cmd)),
        }
    }

    /// Async counterpart of `run()`.
    fn arun<'py>(&self, py: Python<'py>, call: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        match ClientCall::from_py(call)? {
            ClientCall::Args(args) => drive_async(py, async move { client.run(args).await }),
            ClientCall::Cmd(cmd) => drive_async(py, async move { client.run(*cmd).await }),
        }
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(
        &self,
        py: Python<'py>,
        call: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        match ClientCall::from_py(call)? {
            ClientCall::Args(args) => drive_async(py, async move {
                client.output_string(args).await.map(PyProcessResult::from)
            }),
            ClientCall::Cmd(cmd) => drive_async(py, async move {
                client.output_string(*cmd).await.map(PyProcessResult::from)
            }),
        }
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(
        &self,
        py: Python<'py>,
        call: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        match ClientCall::from_py(call)? {
            ClientCall::Args(args) => drive_async(py, async move {
                client.output_bytes(args).await.map(PyBytesResult::from)
            }),
            ClientCall::Cmd(cmd) => drive_async(py, async move {
                client.output_bytes(*cmd).await.map(PyBytesResult::from)
            }),
        }
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(
        &self,
        py: Python<'py>,
        call: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        match ClientCall::from_py(call)? {
            ClientCall::Args(args) => drive_async(py, async move { client.exit_code(args).await }),
            ClientCall::Cmd(cmd) => drive_async(py, async move { client.exit_code(*cmd).await }),
        }
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(
        &self,
        py: Python<'py>,
        call: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        match ClientCall::from_py(call)? {
            ClientCall::Args(args) => drive_async(py, async move { client.probe(args).await }),
            ClientCall::Cmd(cmd) => drive_async(py, async move { client.probe(*cmd).await }),
        }
    }

    fn __repr__(&self) -> String {
        "CliClient()".to_string()
    }
}

/// Register this module's pyclass (`CliClient`) on `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCliClient>()?;
    Ok(())
}
