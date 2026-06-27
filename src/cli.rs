//! A typed CLI wrapper: a program plus default timeout/env, with run verbs that
//! take just the per-call arguments. Convenient for wrapping a tool (git, docker)
//! you call repeatedly with the same defaults.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use processkit::CliClient as PkCliClient;
use processkit::JobRunner;
use processkit::ProcessRunner;
use pyo3::prelude::*;

use crate::convert::positive_duration;
use crate::result::{PyBytesResult, PyProcessResult};
use crate::runner::extract_runner;
use crate::runtime::{block_on, drive_async};

/// A program bound to default timeout/environment, run with the real `Runner`
/// by default, or an injected `runner=` (a `ScriptedRunner` and friends, for
/// testable code with no real spawns).
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
    #[pyo3(signature = (program, *, default_timeout=None, default_env=None, default_env_remove=None, runner=None))]
    fn new(
        program: PathBuf,
        default_timeout: Option<f64>,
        default_env: Option<HashMap<String, String>>,
        default_env_remove: Option<Vec<String>>,
        runner: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
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
        Ok(Self { inner: client })
    }

    /// Run with the given args; require a zero exit and return trimmed stdout.
    fn run(&self, py: Python<'_>, args: Vec<String>) -> PyResult<String> {
        block_on(py, self.inner.run(args))
    }

    /// Run with the given args and capture output (a non-zero exit is data).
    fn output(&self, py: Python<'_>, args: Vec<String>) -> PyResult<PyProcessResult> {
        block_on(py, self.inner.output_string(args)).map(PyProcessResult::from)
    }

    /// Run with the given args and capture raw-bytes stdout.
    fn output_bytes(&self, py: Python<'_>, args: Vec<String>) -> PyResult<PyBytesResult> {
        block_on(py, self.inner.output_bytes(args)).map(PyBytesResult::from)
    }

    /// Run with the given args and return the exit code.
    fn exit_code(&self, py: Python<'_>, args: Vec<String>) -> PyResult<i32> {
        block_on(py, self.inner.exit_code(args))
    }

    /// Run a predicate call and read its exit code as a bool.
    fn probe(&self, py: Python<'_>, args: Vec<String>) -> PyResult<bool> {
        block_on(py, self.inner.probe(args))
    }

    /// Async counterpart of `run()`.
    fn arun<'py>(&self, py: Python<'py>, args: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        drive_async(py, async move { client.run(args).await })
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>, args: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        drive_async(py, async move {
            client.output_string(args).await.map(PyProcessResult::from)
        })
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(
        &self,
        py: Python<'py>,
        args: Vec<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        drive_async(py, async move {
            client.output_bytes(args).await.map(PyBytesResult::from)
        })
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>, args: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        drive_async(py, async move { client.exit_code(args).await })
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>, args: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        drive_async(py, async move { client.probe(args).await })
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
