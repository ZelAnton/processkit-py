//! A typed CLI wrapper: a program plus default timeout/env, with run verbs that
//! take just the per-call arguments. Convenient for wrapping a tool (git, docker)
//! you call repeatedly with the same defaults.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use processkit::CliClient as PkCliClient;
use processkit::JobRunner;
use pyo3::prelude::*;

use crate::convert::positive_duration;
use crate::errors::map_err;
use crate::result::{PyBytesResult, PyProcessResult};
use crate::runtime::block_on_interruptible;

/// A program bound to default timeout/environment, run with the real `Runner`.
///
/// For testable code, compose a `Command` with an injected `Runner` /
/// `ScriptedRunner` instead — this client always uses the real runner.
#[pyclass(name = "CliClient", module = "processkit")]
pub(crate) struct PyCliClient {
    // `Arc` so the async verbs can hold the client across the await.
    inner: Arc<PkCliClient<JobRunner>>,
}

#[pymethods]
impl PyCliClient {
    #[new]
    #[pyo3(signature = (program, *, default_timeout=None, default_env=None, default_env_remove=None))]
    fn new(
        program: PathBuf,
        default_timeout: Option<f64>,
        default_env: Option<HashMap<String, String>>,
        default_env_remove: Option<Vec<String>>,
    ) -> PyResult<Self> {
        let mut client = PkCliClient::new(program.as_os_str());
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
        Ok(Self {
            inner: Arc::new(client),
        })
    }

    /// Run with the given args; require a zero exit and return trimmed stdout.
    fn run(&self, py: Python<'_>, args: Vec<String>) -> PyResult<String> {
        block_on_interruptible(py, self.inner.run(args))?.map_err(map_err)
    }

    /// Run with the given args and capture output (a non-zero exit is data).
    fn output(&self, py: Python<'_>, args: Vec<String>) -> PyResult<PyProcessResult> {
        match block_on_interruptible(py, self.inner.output_string(args))? {
            Ok(inner) => Ok(PyProcessResult { inner }),
            Err(err) => Err(map_err(err)),
        }
    }

    /// Run with the given args and capture raw-bytes stdout.
    fn output_bytes(&self, py: Python<'_>, args: Vec<String>) -> PyResult<PyBytesResult> {
        match block_on_interruptible(py, self.inner.output_bytes(args))? {
            Ok(inner) => Ok(PyBytesResult { inner }),
            Err(err) => Err(map_err(err)),
        }
    }

    /// Run with the given args and return the exit code.
    fn exit_code(&self, py: Python<'_>, args: Vec<String>) -> PyResult<i32> {
        block_on_interruptible(py, self.inner.exit_code(args))?.map_err(map_err)
    }

    /// Run a predicate call and read its exit code as a bool.
    fn probe(&self, py: Python<'_>, args: Vec<String>) -> PyResult<bool> {
        block_on_interruptible(py, self.inner.probe(args))?.map_err(map_err)
    }

    /// Run with the given args; require a zero exit, discard output.
    fn run_unit(&self, py: Python<'_>, args: Vec<String>) -> PyResult<()> {
        block_on_interruptible(py, self.inner.run_unit(args))?.map_err(map_err)
    }

    /// Async counterpart of `run()`.
    fn arun<'py>(&self, py: Python<'py>, args: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            client.run(args).await.map_err(map_err)
        })
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>, args: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match client.output_string(args).await {
                Ok(inner) => Ok(PyProcessResult { inner }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(
        &self,
        py: Python<'py>,
        args: Vec<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            match client.output_bytes(args).await {
                Ok(inner) => Ok(PyBytesResult { inner }),
                Err(err) => Err(map_err(err)),
            }
        })
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>, args: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            client.exit_code(args).await.map_err(map_err)
        })
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>, args: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            client.probe(args).await.map_err(map_err)
        })
    }

    /// Async counterpart of `run_unit()`.
    fn arun_unit<'py>(&self, py: Python<'py>, args: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            client.run_unit(args).await.map_err(map_err)
        })
    }

    fn __repr__(&self) -> String {
        "CliClient()".to_string()
    }
}
