//! The `ProcessGroup` containment container and its `ProcessGroupStats`.

use std::sync::Arc;
use std::time::Duration;

use processkit::Mechanism;
use processkit::ProcessGroup as PkProcessGroup;
use processkit::ProcessGroupOptions;
use pyo3::prelude::*;

use crate::command::PyCommand;
use crate::convert::{nonnegative_duration, parse_signal};
use crate::errors::{map_err, ProcessError};
use crate::running::PyRunningProcess;
use crate::runtime::{block_on, drive_async, reject_reentrant_runtime, require_event_loop};

/// A snapshot of a `ProcessGroup`'s resource usage.
#[pyclass(name = "ProcessGroupStats", frozen, module = "processkit")]
pub(crate) struct PyProcessGroupStats {
    active_process_count: usize,
    peak_memory_bytes: Option<u64>,
    total_cpu_time: Option<Duration>,
}

#[pymethods]
impl PyProcessGroupStats {
    /// Number of live processes currently in the group.
    #[getter]
    fn active_process_count(&self) -> usize {
        self.active_process_count
    }

    /// Peak resident memory across the tree in bytes, if measurable.
    #[getter]
    fn peak_memory_bytes(&self) -> Option<u64> {
        self.peak_memory_bytes
    }

    /// Total CPU time consumed by the tree in seconds, if measurable.
    #[getter]
    fn total_cpu_time_seconds(&self) -> Option<f64> {
        self.total_cpu_time.map(|d| d.as_secs_f64())
    }

    fn __repr__(&self) -> String {
        format!(
            "ProcessGroupStats(active_process_count={}, peak_memory_bytes={:?}, total_cpu_time_seconds={:?})",
            self.active_process_count,
            self.peak_memory_bytes,
            self.total_cpu_time.map(|d| d.as_secs_f64()),
        )
    }
}

/// Tear the group down gracefully (SIGTERM -> grace -> SIGKILL survivors). Uses
/// the crate's `shutdown_ref(&self)` (since 1.1.0), which borrows the group rather
/// than consuming it — so it works even while an `astart` future still holds an
/// `Arc` ref, with no `try_unwrap` and no downgrade to a hard kill. The owned `Arc`
/// passed in is the taken-out inner; dropping it afterwards is a no-op (the group
/// is already down).
async fn shutdown_group(group: Arc<PkProcessGroup>) -> processkit::Result<()> {
    group.shutdown_ref().await
}

/// A kill-on-drop container for a process *tree*. Use it as a context manager
/// (`with` or `async with`): every process started inside, and everything those
/// processes spawn, is torn down when the block exits.
///
/// The teardown asymmetry is load-bearing and honest: on Windows the Job Object
/// reaps the tree when the last handle closes (kernel-enforced); on Linux/macOS
/// teardown is driven from the `__exit__` path and is best-effort if the
/// interpreter is hard-killed.
#[pyclass(name = "ProcessGroup", module = "processkit")]
pub(crate) struct PyProcessGroup {
    // `None` after the group is shut down — every method then errors cleanly.
    // `Arc` so the async `astart` can hold the group across the await without
    // borrowing the pyclass.
    inner: Option<Arc<PkProcessGroup>>,
}

impl PyProcessGroup {
    fn group(&self) -> PyResult<&Arc<PkProcessGroup>> {
        self.inner
            .as_ref()
            .ok_or_else(|| ProcessError::new_err("ProcessGroup is already closed"))
    }
}

#[pymethods]
impl PyProcessGroup {
    #[new]
    #[pyo3(signature = (
        *,
        max_memory=None,
        max_processes=None,
        cpu_quota=None,
        shutdown_grace=None,
        escalate_to_kill=None,
    ))]
    fn new(
        max_memory: Option<u64>,
        max_processes: Option<u32>,
        cpu_quota: Option<f64>,
        shutdown_grace: Option<f64>,
        escalate_to_kill: Option<bool>,
    ) -> PyResult<Self> {
        // `ProcessGroup::new()` is exactly `with_options(default())`, so always
        // build from defaults and apply whatever was passed — no branch needed.
        let mut options = ProcessGroupOptions::default();
        if let Some(bytes) = max_memory {
            // Python kwarg `max_memory` mirrors the `max_*` convention used across
            // the surface; the crate builder method is `memory_max`.
            options = options.memory_max(bytes);
        }
        if let Some(n) = max_processes {
            options = options.max_processes(n);
        }
        if let Some(cores) = cpu_quota {
            // Forwarded raw (unlike the `Duration` knobs, validated locally): the
            // crate validates `cpu_quota` in `with_options` and surfaces
            // NaN/inf/non-positive as a `ResourceLimit` error, never a panic.
            options = options.cpu_quota(cores);
        }
        if let Some(seconds) = shutdown_grace {
            options = options.shutdown_timeout(nonnegative_duration(seconds, "shutdown_grace")?);
        }
        if let Some(escalate) = escalate_to_kill {
            options = options.escalate_to_kill(escalate);
        }
        let group = PkProcessGroup::with_options(options).map_err(map_err)?;
        Ok(Self {
            inner: Some(Arc::new(group)),
        })
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __exit__<'py>(
        &mut self,
        py: Python<'py>,
        _exc_type: Option<Bound<'py, PyAny>>,
        _exc_value: Option<Bound<'py, PyAny>>,
        _traceback: Option<Bound<'py, PyAny>>,
    ) -> PyResult<bool> {
        self.shutdown(py)?;
        // Never suppress an exception raised inside the `with` block.
        Ok(false)
    }

    fn __aenter__<'py>(slf: Py<Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        pyo3_async_runtimes::tokio::future_into_py(py, async move { Ok(slf) })
    }

    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __aexit__<'py>(
        &mut self,
        py: Python<'py>,
        _exc_type: Option<Bound<'py, PyAny>>,
        _exc_value: Option<Bound<'py, PyAny>>,
        _traceback: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Checked before taking: see the comment on `require_event_loop` in
        // running.rs for why the order matters (consume-then-fail).
        require_event_loop(py)?;
        let group = self.inner.take();
        drive_async(py, async move {
            if let Some(group) = group {
                shutdown_group(group).await?;
            }
            Ok::<bool, processkit::Error>(false)
        })
    }

    /// Start a command inside the group and return a handle (sync). The process
    /// runs concurrently; this does not wait for it to finish.
    fn start(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyRunningProcess> {
        let group = self.group()?.clone();
        block_on(py, group.start(&command.inner)).map(PyRunningProcess::from)
    }

    /// Async counterpart of `start()`.
    fn astart<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        let group = self.group()?.clone();
        let cmd = command.inner.clone();
        drive_async(py, async move {
            group.start(&cmd).await.map(PyRunningProcess::from)
        })
    }

    /// The containment mechanism in use: `"job_object"` (Windows),
    /// `"cgroup_v2"` (Linux), or `"process_group"` (POSIX fallback).
    #[getter]
    fn mechanism(&self) -> PyResult<&'static str> {
        let mechanism = match self.group()?.mechanism() {
            Mechanism::JobObject => "job_object",
            Mechanism::CgroupV2 => "cgroup_v2",
            Mechanism::ProcessGroup => "process_group",
            _ => "unknown",
        };
        Ok(mechanism)
    }

    /// The process ids currently contained by the group.
    fn members(&self) -> PyResult<Vec<u32>> {
        self.group()?.members().map_err(map_err)
    }

    /// Send a signal to every process in the tree. `name` is one of `term`,
    /// `kill`, `int`, `hup`, `quit`, `usr1`, `usr2` — but a Job Object has no
    /// POSIX signals, so on Windows only `kill` is deliverable; every other
    /// name raises `Unsupported` there.
    fn signal(&self, name: &str) -> PyResult<()> {
        let signal = parse_signal(name)?;
        self.group()?.signal(signal).map_err(map_err)
    }

    /// Suspend every process in the tree.
    fn suspend(&self) -> PyResult<()> {
        self.group()?.suspend().map_err(map_err)
    }

    /// Resume every previously-suspended process in the tree.
    fn resume(&self) -> PyResult<()> {
        self.group()?.resume().map_err(map_err)
    }

    /// Immediately kill the whole tree (a hard kill, no graceful window) — the
    /// group counterpart of `RunningProcess.kill()`. For a graceful teardown use
    /// `shutdown()` / `ashutdown()`.
    fn kill_all(&self) -> PyResult<()> {
        self.group()?.kill_all().map_err(map_err)
    }

    /// A snapshot of the group's resource usage.
    fn stats(&self) -> PyResult<PyProcessGroupStats> {
        let stats = self.group()?.stats().map_err(map_err)?;
        Ok(PyProcessGroupStats {
            active_process_count: stats.active_process_count,
            peak_memory_bytes: stats.peak_memory_bytes,
            total_cpu_time: stats.total_cpu_time,
        })
    }

    /// Tear down the whole tree gracefully (sync). Idempotent — a second call is
    /// a no-op.
    fn shutdown(&mut self, py: Python<'_>) -> PyResult<()> {
        // Checked before taking: see the comment on `require_event_loop` in
        // running.rs for why the order matters (consume-then-fail).
        reject_reentrant_runtime()?;
        if let Some(group) = self.inner.take() {
            block_on(py, shutdown_group(group))?;
        }
        Ok(())
    }

    /// Async counterpart of `shutdown()`. Idempotent.
    fn ashutdown<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        let group = self.inner.take();
        drive_async(py, async move {
            if let Some(group) = group {
                shutdown_group(group).await?;
            }
            Ok::<(), processkit::Error>(())
        })
    }

    fn __repr__(&self) -> String {
        match &self.inner {
            Some(_) => "ProcessGroup(open)".to_string(),
            None => "ProcessGroup(closed)".to_string(),
        }
    }
}
