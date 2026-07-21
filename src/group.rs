//! The `ProcessGroup` containment container and its `ProcessGroupStats`.

use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Duration;

use processkit::Mechanism;
use processkit::ProcessGroup as PkProcessGroup;
use processkit::ProcessGroupOptions;
use pyo3::prelude::*;

use crate::command::PyCommand;
use crate::convert::{nonnegative_duration, parse_signal};
use crate::errors::{map_err, ProcessError};
use crate::result::{PyBytesResult, PyProcessResult};
use crate::runner::{
    runner_aexit_code, runner_aoutput, runner_aoutput_bytes, runner_aprobe, runner_arun,
    runner_exit_code, runner_output, runner_output_bytes, runner_probe, runner_run,
};
use crate::running::PyRunningProcess;
use crate::runtime::{
    block_on, drive_async, drive_async_py, reject_reentrant_runtime, require_event_loop,
};

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

/// An enriched, point-in-time snapshot of one member of a `ProcessGroup`'s tree
/// — its pid plus best-effort metadata (parent pid, image name, start time).
///
/// The metadata-carrying companion to a bare pid from `members()`: *which*
/// members appear follows the same platform matrix as `members()`, and every
/// enriching field beyond `pid` is independently `None` wherever the platform
/// can't report it — never a fabricated value. A member that exits mid-snapshot
/// is silently omitted (never invented). The raw command line / environment is
/// deliberately never carried, on any platform. Like `ProcessGroupStats`, a plain
/// immutable point-in-time record — no lock/lifecycle.
#[pyclass(name = "MemberInfo", frozen, module = "processkit")]
pub(crate) struct PyMemberInfo {
    pid: u32,
    ppid: Option<u32>,
    exe_name: Option<String>,
    start_time: Option<u64>,
}

#[pymethods]
impl PyMemberInfo {
    /// The member's process id — always present. Point-in-time, like a pid from
    /// `members()`: pair it with `start_time` to tell a recycled number apart
    /// from the original process.
    #[getter]
    fn pid(&self) -> u32 {
        self.pid
    }

    /// The member's parent process id, or `None` where the platform can't report
    /// one (always `None` on the BSDs).
    #[getter]
    fn ppid(&self) -> Option<u32> {
        self.ppid
    }

    /// The member's short image (executable) *base name* — never a full path, and
    /// never a command line (the crate deliberately never exposes argv/env). `None`
    /// where the platform can't report one (always `None` on the BSDs).
    #[getter]
    fn exe_name(&self) -> Option<&str> {
        self.exe_name.as_deref()
    }

    /// An **opaque per-process identity token**, or `None` where the platform can't
    /// report one — **not** a wall-clock timestamp. Its unit and epoch are
    /// platform-specific (Windows creation `FILETIME`, 100ns intervals since 1601;
    /// Linux `/proc/<pid>/stat` field 22, clock ticks since boot; macOS microseconds
    /// since the Unix epoch; always `None` on the BSDs), so do not interpret it or
    /// compare it across platforms. Its sole use is pairing with `pid`: two snapshots
    /// whose `pid` **and** `start_time` both match name the same process instance,
    /// telling a recycled pid apart from the original.
    #[getter]
    fn start_time(&self) -> Option<u64> {
        self.start_time
    }

    fn __repr__(&self) -> String {
        format!(
            "MemberInfo(pid={}, ppid={:?}, exe_name={:?}, start_time={:?})",
            self.pid, self.ppid, self.exe_name, self.start_time,
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

/// Shared teardown for `ashutdown`/`__aexit__`: a no-op when the group is
/// already closed (`None`), otherwise the same graceful `shutdown_group`.
async fn shutdown_if_open(group: Option<Arc<PkProcessGroup>>) -> processkit::Result<()> {
    if let Some(group) = group {
        shutdown_group(group).await?;
    }
    Ok(())
}

/// A kill-on-drop container for a process *tree*. Use it as a context manager
/// (`with` or `async with`): every process started inside, and everything those
/// processes spawn, is torn down when the block exits.
///
/// The teardown asymmetry is load-bearing and honest: on Windows the Job Object
/// reaps the tree when the last handle closes (kernel-enforced); on Linux/macOS
/// teardown is driven from the `__exit__` path and is best-effort if the
/// interpreter is hard-killed.
///
/// Also usable directly as a runner: `group.output(cmd)` / `.run(cmd)` / …
/// run `cmd` as a *shared* member of this group (not a standalone tree) —
/// the same verb surface `Runner`/`ScriptedRunner`/… expose, for code
/// written against that seam that should route every spawn through one
/// shared group instead of a per-call private tree.
// `frozen` so every method takes `&self`: under free-threading a `&mut self`
// method would take an exclusive PyO3 borrow that a concurrent `&self` call
// from another thread rejects with a raw `RuntimeError("Already borrowed")`
// instead of a typed `ProcessError` — and worse, an `__exit__` that extracts
// its `&mut self` borrow *before* its body would fail there and skip the
// graceful teardown entirely. The interior `Mutex<Option<...>>` serializes the
// concurrent access instead, and a taken-out (closed) group reads back cleanly
// as `None`. The guard is always dropped *before* any `block_on`/await (the
// helpers below return owned values), so holding it never serializes the
// teardown window or risks a re-entrant deadlock.
#[pyclass(name = "ProcessGroup", module = "processkit", frozen)]
pub(crate) struct PyProcessGroup {
    // `None` after the group is shut down — every method then errors cleanly.
    // `Arc` so the async `astart` (and a concurrent teardown) can each hold the
    // group across their awaits without holding the lock.
    inner: Mutex<Option<Arc<PkProcessGroup>>>,
}

impl PyProcessGroup {
    /// Lock the inner slot, recovering from a (never-expected) poisoned mutex
    /// rather than panicking across the FFI boundary — the guarded critical
    /// sections below only clone/take an `Arc` and never panic, so poisoning
    /// cannot actually happen, but `unwrap()`ing a `PoisonError` would itself be
    /// a panic point PyO3 would surface as a `PanicException`.
    fn lock(&self) -> MutexGuard<'_, Option<Arc<PkProcessGroup>>> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Clone the live group `Arc` out from under the lock, or error if closed.
    /// The lock is released before this returns, so callers hold an owned `Arc`
    /// — never the lock — across any subsequent `block_on`/await.
    fn group(&self) -> PyResult<Arc<PkProcessGroup>> {
        self.lock()
            .as_ref()
            .cloned()
            .ok_or_else(|| ProcessError::new_err("ProcessGroup is already closed"))
    }

    /// Take the group out for teardown, returning `None` if already closed.
    /// Idempotent: a second call after a shutdown sees `None`.
    fn take(&self) -> Option<Arc<PkProcessGroup>> {
        self.lock().take()
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
            // the surface; the crate builder method is `max_memory`.
            options = options.max_memory(bytes);
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
            inner: Mutex::new(Some(Arc::new(group))),
        })
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __exit__<'py>(
        &self,
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
        drive_async_py(py, async move { Ok(slf) })
    }

    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __aexit__<'py>(
        &self,
        py: Python<'py>,
        _exc_type: Option<Bound<'py, PyAny>>,
        _exc_value: Option<Bound<'py, PyAny>>,
        _traceback: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Checked before taking: see the comment on `require_event_loop` in
        // running.rs for why the order matters (consume-then-fail).
        require_event_loop(py)?;
        let group = self.take();
        drive_async(py, async move {
            shutdown_if_open(group).await?;
            Ok::<bool, processkit::Error>(false)
        })
    }

    /// Start a command inside the group and return a handle (sync). The process
    /// runs concurrently; this does not wait for it to finish.
    fn start(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyRunningProcess> {
        let group = self.group()?;
        block_on(py, group.start(&command.inner)).map(PyRunningProcess::from)
    }

    /// Async counterpart of `start()`.
    fn astart<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        let group = self.group()?;
        let cmd = command.inner.clone();
        drive_async(py, async move {
            group.start(&cmd).await.map(PyRunningProcess::from)
        })
    }

    // `ProcessGroup` implements the crate's `ProcessRunner` (`output_string` +
    // `start`, with `output_bytes`/`run`/`exit_code`/`probe` from the trait's
    // own defaults/`ProcessRunnerExt`) — so it can run a *shared*-group member
    // command directly, the same verb surface as `Runner`/`ScriptedRunner`/…,
    // via the same generic `runner_*` helpers those use over `self.inner`
    // (`Arc<ProcessGroup>` itself satisfies `ProcessRunner` via the crate's
    // blanket `impl<R: ProcessRunner + ?Sized> ProcessRunner for Arc<R>`).
    // Not registered as an `extract_runner` target (unlike the four dedicated
    // runner pyclasses) — a `ProcessGroup` is a containment container first,
    // injectable directly by callers who already hold one, not through the
    // `runner=` kwarg seam.

    /// Run `command` as a member of this group and capture output (a non-zero
    /// exit is data, not an error) — the `ProcessRunner` verb surface.
    fn output(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyProcessResult> {
        runner_output(py, self.group()?.as_ref(), command)
    }

    /// Run `command` as a member of this group and capture raw-bytes stdout.
    fn output_bytes(&self, py: Python<'_>, command: &PyCommand) -> PyResult<PyBytesResult> {
        runner_output_bytes(py, self.group()?.as_ref(), command)
    }

    /// Run `command` as a member of this group; require a zero exit and
    /// return trimmed stdout.
    fn run(&self, py: Python<'_>, command: &PyCommand) -> PyResult<String> {
        runner_run(py, self.group()?.as_ref(), command)
    }

    /// Run `command` as a member of this group and return the exit code.
    fn exit_code(&self, py: Python<'_>, command: &PyCommand) -> PyResult<i32> {
        runner_exit_code(py, self.group()?.as_ref(), command)
    }

    /// Run a predicate command as a member of this group and read its exit
    /// code as a bool.
    fn probe(&self, py: Python<'_>, command: &PyCommand) -> PyResult<bool> {
        runner_probe(py, self.group()?.as_ref(), command)
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aoutput(py, self.group()?, command)
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(
        &self,
        py: Python<'py>,
        command: &PyCommand,
    ) -> PyResult<Bound<'py, PyAny>> {
        runner_aoutput_bytes(py, self.group()?, command)
    }

    /// Async counterpart of `run()`.
    fn arun<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_arun(py, self.group()?, command)
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aexit_code(py, self.group()?, command)
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(&self, py: Python<'py>, command: &PyCommand) -> PyResult<Bound<'py, PyAny>> {
        runner_aprobe(py, self.group()?, command)
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

    /// An enriched, point-in-time snapshot of the group's members — the same set
    /// as `members()`, but each pid carried in a `MemberInfo` alongside
    /// best-effort parent pid, image name, and start time. Synchronous only
    /// (the crate offers no async twin). A member that exits mid-snapshot is
    /// silently omitted by the crate — the fields are never fabricated.
    fn members_info(&self) -> PyResult<Vec<PyMemberInfo>> {
        let infos = self.group()?.members_info().map_err(map_err)?;
        Ok(infos
            .into_iter()
            .map(|info| PyMemberInfo {
                pid: info.pid(),
                ppid: info.ppid(),
                exe_name: info.exe_name().map(str::to_owned),
                start_time: info.start_time(),
            })
            .collect())
    }

    /// Send a signal to every process in the tree. `name` is one of `term`,
    /// `kill`, `int`, `hup`, `quit`, `usr1`, `usr2`, or a raw platform signal
    /// number (Unix only) — but a Job Object has no POSIX signals, so on
    /// Windows only `kill` is deliverable; every other name/number raises
    /// `Unsupported` there.
    ///
    /// A raw number is validated up front as a real, deliverable signal
    /// (`1..=SIGRTMAX` on Unix), so a `0` (the existence probe), a negative, or
    /// an out-of-range value raises `ValueError` instead of reaching the backend
    /// as a silent no-op. A `bool` raises `TypeError` (it is an `int` subtype
    /// that would otherwise become raw signal `1`/`0`).
    fn signal(&self, name: &Bound<'_, PyAny>) -> PyResult<()> {
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
    fn shutdown(&self, py: Python<'_>) -> PyResult<()> {
        // Checked before taking: see the comment on `require_event_loop` in
        // running.rs for why the order matters (consume-then-fail). `take()`
        // releases the lock before `block_on`, so the whole graceful-teardown
        // window runs unlocked — a concurrent `start()`/`stats()`/… on another
        // thread sees `None` and returns a clean `ProcessError`, never blocks.
        reject_reentrant_runtime()?;
        if let Some(group) = self.take() {
            block_on(py, shutdown_group(group))?;
        }
        Ok(())
    }

    /// Async counterpart of `shutdown()`. Idempotent.
    fn ashutdown<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        let group = self.take();
        drive_async(py, shutdown_if_open(group))
    }

    fn __repr__(&self) -> String {
        match self.lock().as_ref() {
            Some(_) => "ProcessGroup(open)".to_string(),
            None => "ProcessGroup(closed)".to_string(),
        }
    }
}

/// Register this module's pyclasses (`ProcessGroup`, `ProcessGroupStats`,
/// `MemberInfo`) on `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyProcessGroup>()?;
    m.add_class::<PyProcessGroupStats>()?;
    m.add_class::<PyMemberInfo>()?;
    Ok(())
}
