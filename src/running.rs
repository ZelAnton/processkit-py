//! The async streaming/interactive handles: `RunningProcess` plus its
//! `ProcessStdin`, `StdoutLines`, `JsonLines`, `StderrLines`, and `OutputEvents`.

use std::future::Future;
use std::sync::{Arc, Mutex as StdMutex, MutexGuard as StdMutexGuard, PoisonError};
use std::task::{Context, Poll, Waker};
use std::time::Duration;

use processkit::prelude::StreamExt;
use processkit::Finished as PkFinished;
// Crate 3.0.0 renamed `OutputEvents` -> `ProcessEvents` (and the verb
// `output_events()` -> `events()`) as the merged stream widened from output to
// the whole process lifecycle. The Python names are unchanged — see
// `PyOutputEvents` below.
use processkit::JsonLines as PkJsonLines;
use processkit::ProcessEvent as PkProcessEvent;
use processkit::ProcessEvents as PkProcessEvents;
use processkit::ProcessStdin as PkProcessStdin;
use processkit::RunningProcess as PkRunningProcess;
use processkit::StdoutLines as PkStdoutLines;
use pyo3::exceptions::{PyOSError, PyStopAsyncIteration, PyValueError};
use pyo3::prelude::*;
use serde_json::value::RawValue;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;

use crate::convert::{nonnegative_duration, positive_duration};
use crate::errors::{
    idle_timeout_err, invalid_json_line_err, invalid_json_stream_err, map_err, ProcessError,
};
use crate::result::{
    PyBytesResult, PyFinished, PyLifecycleEvent, PyOutcome, PyOutputEvent, PyProcessResult,
    PyRunProfile,
};
use crate::runtime::{
    block_on, block_on_interruptible, drive_async, drive_async_py, drive_async_py_convert,
    reject_reentrant_runtime, require_event_loop, runtime,
};

/// The shared process slot: `None` once a consuming verb has taken ownership.
/// Shared (via `Arc`) between the `RunningProcess` handle and any idle-timeout
/// watchdog or events drive living in one of its streams, so all of them address
/// the one process through the one `StdMutex` (no second, racing kill channel).
///
/// Shared for *reach*, never for ownership: the handle empties this slot as it is
/// dropped, so a stream object that outlives its handle cannot extend the child's
/// life (see `impl Drop for PyRunningProcess`).
type SharedProcess = Arc<StdMutex<Option<PkRunningProcess>>>;

/// The idle-timeout watchdog carried by a process output stream: the inactivity
/// window plus a shared handle to the process to kill on
/// silence. Enforcement rides the existing per-line output channel — the
/// stream's own `.next()` — rather than a separate process-supervision loop:
/// each `__anext__` bounds the wait for the next line by `window`, and a lapse
/// is treated as "the child went silent". Cheap to clone (an `Arc` bump + a
/// `Copy` `Duration`).
#[derive(Clone)]
struct IdleGuard {
    window: Duration,
    process: SharedProcess,
}

impl IdleGuard {
    /// Hard-kill the child on an idle lapse. Locks the shared slot briefly (no
    /// await held across it) and starts the kill if the process is still there;
    /// a `None` slot (a consuming verb already took it) is a no-op. `start_kill`
    /// runs inside the tokio runtime here — `__anext__`'s future is polled on a
    /// runtime worker — so no explicit `runtime().enter()` is needed (unlike the
    /// synchronous `RunningProcess.kill()`). A kill error is ignored: the child
    /// may already be gone, and the caller is about to raise `IdleTimeout`
    /// regardless.
    fn kill(&self) {
        let mut guard = self.process.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some(running) = guard.as_mut() {
            let _ = running.start_kill();
        }
    }
}

/// The state of the finisher an `output_events()` stream may have started on the
/// caller's behalf — see [`PyOutputEvents`] for *why* it exists. Shared (via
/// `Arc`) between the `RunningProcess` handle and its events stream, so the
/// handle's consuming verb reports the run this finisher actually observed
/// instead of raising "already consumed".
enum JointFinish {
    /// No joint finisher: the handle still owns the process (the normal state,
    /// and the only one a run that never calls `output_events()` ever reaches).
    NotStarted,
    /// The events stream handed the run to this background `finish()` task.
    Running(JoinHandle<processkit::Result<PkFinished>>),
    /// The joint finisher is no longer this slot's to give: a consuming verb took
    /// it to report the run, or a context-manager exit took it to tear the tree
    /// down (see [`teardown`]). Either way the handle is spent from here on.
    Taken,
}

type FinishSlot = Arc<StdMutex<JointFinish>>;

/// What a consuming verb (`finish`/`outcome`/`shutdown` & co.) — or a context
/// manager's teardown — found when it claimed the run: either the live process,
/// or the joint finisher the events stream started.
enum Claimed {
    // Boxed: `RunningProcess` is a few hundred bytes while a `JoinHandle` is one
    // pointer, so an unboxed enum would make every `claim()` return path pay the
    // larger size (clippy's `large_enum_variant`). This value is created once per
    // consuming verb and immediately destructured, so the extra allocation is not
    // on any hot path.
    Process(Box<PkRunningProcess>),
    Joint(JoinHandle<processkit::Result<PkFinished>>),
}

/// Await the joint finisher's `Finished`, mapping a task-level failure (the
/// background task panicked, or was aborted by the handle's `Drop`) to a clear
/// `ProcessError` rather than a bare `JoinError` no Python caller can act on.
async fn joint_finished(task: JoinHandle<processkit::Result<PkFinished>>) -> PyResult<PyFinished> {
    match task.await {
        Ok(result) => result.map(PyFinished::from).map_err(map_err),
        Err(join) => Err(ProcessError::new_err(format!(
            "the run's finisher, started by output_events() so the event stream \
             could complete, did not finish: {join}"
        ))),
    }
}

/// What the non-consuming exit probe observed.
enum ProbeVerdict {
    /// The child has exited (and been reaped by the probe): its output pipes are
    /// at EOF, so the event stream is heading for its terminal park.
    Exited,
    /// The child is still running — nothing to do but keep reading output and
    /// ask again on the next tick.
    Running,
    /// There is no process to probe — a consuming verb (or a concurrent joint
    /// finisher) already owns the reap, so it will publish the terminal event.
    NoProcess,
}

/// Ask, **without consuming the handle and without moving the process anywhere
/// the rest of the binding cannot see it**, whether the child has exited *yet*.
///
/// `RunningProcess::wait_for` is the crate's own readiness driver: it polls the
/// caller's predicate and, between polls, fails fast the moment the child is seen
/// to have exited ("An exited child can never become ready"). With a predicate
/// that is never ready and a horizon far past any real run (`Duration::MAX`,
/// clamped by the crate to ~10 years), that fail-fast path is the *only* way it
/// can return — and it takes that path **on its first poll**, without suspending
/// on the way: the predicate future is already-ready, and the exit check runs
/// before the loop's first `sleep`. So polling that future exactly once answers
/// "has the child exited *now*?" — `Ready` is yes, `Pending` is not yet — with no
/// dependence on timing, and identically for a real child and a scripted double
/// (whose `pid` is `None` from the start, so no pid-based inference could work).
///
/// Answering in a single poll is what lets the probe run **under the same
/// `StdMutex` every other method on this handle takes, with the process left in
/// the slot**. An earlier shape borrowed the process *out* of the slot for as
/// long as the `__anext__` future was parked — for a quiet child, an arbitrarily
/// long stretch — during which `pid`/the live line counters read `None`,
/// `kill()`/`take_stdin()` raised "the process handle has been consumed" for a
/// perfectly live handle, and, worst of all, the context manager's deterministic
/// teardown found an empty slot and became a silent no-op (an orphaned tree until
/// the objects were collected). Here the slot is never observably empty: a
/// concurrent getter, `kill()`, or `__exit__` on another thread waits microseconds
/// on the mutex and then sees the live process, exactly as it would with no events
/// stream in play at all.
///
/// The probe takes `&mut RunningProcess`, never `self`, and while an `events()`
/// stream is live its background-drain setup is a no-op (stdout is already
/// consumed by the stream, stderr's drain is idempotent), so it cannot steal a
/// line from the stream. It *does* reap the child once it finds it exited — which
/// is the point: the joint finisher armed right afterwards reports that run.
///
/// The one assumption to re-check on a crate upgrade is the "first poll reaches
/// the exit check" one above: were the check ever moved behind an await, this
/// would stop observing exits and the documented drain-then-finish order would
/// park forever. That is why every test of that order in `tests/test_streaming.py`
/// carries an explicit deadline — a regression there fails the suite instead of
/// hanging it.
fn probe_exit_now(slot: &SharedProcess) -> ProbeVerdict {
    let mut guard = slot.lock().unwrap_or_else(PoisonError::into_inner);
    let Some(running) = guard.as_mut() else {
        return ProbeVerdict::NoProcess;
    };
    let mut probe = std::pin::pin!(running.wait_for(|| std::future::ready(false), Duration::MAX));
    // A no-op waker is sound here because nothing waits to be woken: the future
    // is dropped at the end of this call and built afresh on the next tick, so
    // there is no wakeup to lose. Dropping it is likewise harmless — the only
    // thing it may have set up is the crate's idempotent background drain, which
    // lives in its own spawned task.
    match probe.as_mut().poll(&mut Context::from_waker(Waker::noop())) {
        Poll::Ready(_) => ProbeVerdict::Exited,
        Poll::Pending => ProbeVerdict::Running,
    }
}

/// A writable handle to a running process's stdin. Obtain it once via
/// `RunningProcess.take_stdin()`; all methods are awaitable.
#[pyclass(name = "ProcessStdin", module = "processkit")]
pub(crate) struct PyProcessStdin {
    // `None` after `close()` — writing then raises a clear error.
    inner: Arc<Mutex<Option<PkProcessStdin>>>,
}

#[pymethods]
impl PyProcessStdin {
    /// Write raw bytes to the child's stdin.
    fn write<'py>(&self, py: Python<'py>, data: Vec<u8>) -> PyResult<Bound<'py, PyAny>> {
        let stdin = self.inner.clone();
        drive_async_py(py, async move {
            let mut guard = stdin.lock().await;
            let writer = guard
                .as_mut()
                .ok_or_else(|| PyOSError::new_err("stdin is closed"))?;
            writer.write(&data).await.map_err(PyErr::from)
        })
    }

    /// Write a line of text, appending a newline.
    fn write_line<'py>(&self, py: Python<'py>, line: String) -> PyResult<Bound<'py, PyAny>> {
        let stdin = self.inner.clone();
        drive_async_py(py, async move {
            let mut guard = stdin.lock().await;
            let writer = guard
                .as_mut()
                .ok_or_else(|| PyOSError::new_err("stdin is closed"))?;
            writer.write_line(&line).await.map_err(PyErr::from)
        })
    }

    /// Send a single control byte to the child's stdin. Under `Command.pty()`
    /// the terminal line discipline can turn it into a real signal; under an
    /// ordinary pipe it remains a byte for a cooperating child to interpret.
    fn send_control<'py>(&self, py: Python<'py>, control: String) -> PyResult<Bound<'py, PyAny>> {
        let mut chars = control.chars();
        let c = chars.next().ok_or_else(|| {
            PyValueError::new_err("send_control() requires exactly one control character")
        })?;
        if chars.next().is_some() {
            return Err(PyValueError::new_err(
                "send_control() requires exactly one control character",
            ));
        }

        let stdin = self.inner.clone();
        drive_async_py(py, async move {
            let mut guard = stdin.lock().await;
            let writer = guard
                .as_mut()
                .ok_or_else(|| PyOSError::new_err("stdin is closed"))?;
            writer.send_control(c).await.map_err(|err| {
                if err.kind() == std::io::ErrorKind::InvalidInput {
                    PyValueError::new_err(err.to_string())
                } else {
                    PyErr::from(err)
                }
            })
        })
    }

    /// Flush buffered writes to the child.
    fn flush<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stdin = self.inner.clone();
        drive_async_py(py, async move {
            let mut guard = stdin.lock().await;
            let writer = guard
                .as_mut()
                .ok_or_else(|| PyOSError::new_err("stdin is closed"))?;
            writer.flush().await.map_err(PyErr::from)
        })
    }

    /// Close stdin (sending EOF to the child). Idempotent.
    fn close<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stdin = self.inner.clone();
        drive_async_py(py, async move {
            let writer = { stdin.lock().await.take() };
            match writer {
                Some(writer) => writer.finish().await.map_err(PyErr::from),
                None => Ok(()),
            }
        })
    }
}

/// An async iterator over a process's stdout, line by line:
/// `async for line in proc.stdout_lines(): ...`.
#[pyclass(name = "StdoutLines", module = "processkit")]
pub(crate) struct PyStdoutLines {
    inner: Arc<Mutex<PkStdoutLines>>,
    // The idle-timeout watchdog, if the originating command set `idle_timeout`.
    idle: Option<IdleGuard>,
}

#[pymethods]
impl PyStdoutLines {
    fn __aiter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __anext__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stream = self.inner.clone();
        let idle = self.idle.clone();
        drive_async_py(py, async move {
            let mut guard = stream.lock().await;
            match idle {
                // Bound the wait for the next line by the idle window: a lapse
                // means the child produced no stdout line in time — kill it and
                // raise the distinct `IdleTimeout` (never a `StopAsyncIteration`,
                // which would look like a clean end-of-stream). `None` is a real
                // end-of-stream; a line resets the clock for the next call.
                Some(guard_idle) => {
                    match tokio::time::timeout(guard_idle.window, guard.next()).await {
                        Ok(Some(line)) => Ok(line),
                        Ok(None) => Err(PyStopAsyncIteration::new_err(())),
                        Err(_elapsed) => {
                            guard_idle.kill();
                            Err(idle_timeout_err(guard_idle.window.as_secs_f64()))
                        }
                    }
                }
                None => match guard.next().await {
                    Some(line) => Ok(line),
                    None => Err(PyStopAsyncIteration::new_err(())),
                },
            }
        })
    }
}

/// An async iterator over a process's stdout, one deserialized JSON value per
/// line: `async for obj in proc.stdout_json_lines(): ...`. Otherwise the exact
/// same consuming/streaming-conflict and idle-timeout rules as [`PyStdoutLines`]
/// (both wrap the crate's own `stdout_lines()`-driven pump under the hood) —
/// this just decodes each line before handing it to Python instead of yielding
/// the raw `str`.
///
/// Wraps the crate's `JsonLines<Box<RawValue>>`: the crate validates and
/// captures each line's exact JSON text (a syntax-checking capture, not a full
/// parse into a value tree — see [`RawValue`]) and produces its own typed,
/// line/column/byte-offset-bearing decode diagnostic on a malformed line (see
/// [`invalid_json_line_err`]); `__anext__`'s `convert` step below hands that
/// captured text to Python's own `json.loads` for the actual object
/// construction — the same "lean on stdlib `json`, no `serde_json::Value` ->
/// Python-object bridge" choice `run_json`/`arun_json` made (`cli.rs::parse_json`),
/// and additionally one that can't silently reorder a decoded object's keys the
/// way a bare `serde_json::Value` round-trip would without also pulling in
/// `serde_json`'s `preserve_order` feature.
#[pyclass(name = "JsonLines", module = "processkit")]
pub(crate) struct PyJsonLines {
    inner: Arc<Mutex<PkJsonLines<Box<RawValue>>>>,
    program: String,
    // The idle-timeout watchdog, if the originating command set `idle_timeout`.
    idle: Option<IdleGuard>,
}

#[pymethods]
impl PyJsonLines {
    fn __aiter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __anext__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stream = self.inner.clone();
        let idle = self.idle.clone();
        let program = self.program.clone();
        // `drive_async_py_convert`, not `drive_async_py`: the success value needs
        // a Python API (`json.loads`) to become the object Python actually sees,
        // so that step is deferred to the event-loop-thread `convert` closure
        // below rather than attempted from inside this tokio-driven future.
        drive_async_py_convert(
            py,
            async move {
                let mut guard = stream.lock().await;
                let item = match idle {
                    // Same bounded-wait-then-kill shape as `PyStdoutLines`: a lapse
                    // between JSON lines is exactly as much "the child went
                    // silent" as a lapse between raw lines.
                    Some(guard_idle) => {
                        match tokio::time::timeout(guard_idle.window, guard.next()).await {
                            Ok(item) => item,
                            Err(_elapsed) => {
                                guard_idle.kill();
                                return Err(idle_timeout_err(guard_idle.window.as_secs_f64()));
                            }
                        }
                    }
                    None => guard.next().await,
                };
                match item {
                    // The stream continues after a malformed line (the crate's
                    // `JsonLines` contract) — this is a per-item error, never one
                    // that ends the iterator.
                    Some(Ok(raw)) => Ok(raw),
                    Some(Err(error)) => Err(invalid_json_line_err(&error)),
                    None => Err(PyStopAsyncIteration::new_err(())),
                }
            },
            move |py, raw: Box<RawValue>| match py
                .import("json")
                .and_then(|json| json.call_method1("loads", (raw.get(),)))
            {
                Ok(value) => Ok(value.unbind()),
                Err(parse_error) => Err(invalid_json_stream_err(py, &program, &parse_error)),
            },
        )
    }
}

/// The stream side of `output_events()`: the crate's lifecycle-event stream plus
/// everything needed to keep it moving *together with* the run's finisher.
///
/// Crate 3.0.0 made the merged stream's terminal `ProcessEvent::Exited` arrive at
/// the moment the run is **reaped**, so a consumer that drains the stream to its
/// end and only then calls `finish()` deadlocks: the stream is parked waiting for
/// a reap nobody has started. Upstream's answer is to drive the stream and the
/// finisher together (`tokio::join!`). Python's documented order is the opposite
/// shape (`async for …` to exhaustion, *then* `await proc.afinish()`), and that
/// order is public contract here — so the binding closes the gap on its own side:
/// this drive starts the finisher itself, at the last possible moment, and parks
/// its result where the handle's consuming verb will find it.
struct EventsDrive {
    stream: PkProcessEvents,
    /// The handle's process slot, shared verbatim — the same `Arc` the handle and
    /// the idle watchdog use, so all three address the one process.
    process: SharedProcess,
    /// Where the finisher this drive starts is published for the handle.
    finish: FinishSlot,
    /// Whether the reap is already someone's job (this drive started it, or a
    /// consuming verb owns it) — once true the stream is simply drained.
    reap_started: bool,
    /// How long to wait for the next event before running the exit probe again:
    /// zero on the first park after an event — so a child that exits while its
    /// last lines are being drained is noticed immediately, at no added latency —
    /// then [`EXIT_POLL_INTERVAL`] for as long as the stream stays quiet.
    probe_after: Duration,
}

/// Steady-state cadence of the events drive's exit probe while the stream is
/// quiet and the child is still running.
///
/// Matches the crate's own readiness-poll tick, and costs one `try_wait`-shaped
/// check per tick per streaming handle. It bounds only the *idle* case: the first
/// park after every event probes immediately (see `EventsDrive::probe_after`), so
/// the end of a run is observed as soon as its output stops, not up to a tick
/// later.
const EXIT_POLL_INTERVAL: Duration = Duration::from_millis(50);

impl EventsDrive {
    /// Pull the next lifecycle event, driving the run's finisher alongside the
    /// stream so its terminal `Exited` event can arrive.
    ///
    /// The loop has two jobs beyond `stream.next()`:
    ///
    /// **Start the reap, as late as possible.** The finisher is armed only once
    ///    the crate's own non-consuming probe reports the child has exited, i.e.
    ///    once the stream is provably heading for its terminal park. Arming it
    ///    earlier would work for the deadlock but would spend the handle for the
    ///    whole streamed run — `pid` and the live line counters would read `None`,
    ///    `kill()`/`take_stdin()` would raise, the idle watchdog would lose its
    ///    kill channel, and `finish()`'s own "close an untaken stdin" step would
    ///    send a `keep_stdin_open` child a premature EOF. Waiting for the exit
    ///    keeps every one of those observable behaviours exactly as it was — and
    ///    the probe itself (see [`probe_exit_now`]) is a single synchronous poll
    ///    under the shared slot's lock, so it never takes the process *out* of the
    ///    slot either, not even for the moment it is being asked.
    ///
    /// The probe is driven from the wait for the next event: whenever the stream
    /// has nothing ready, ask once immediately, then once per
    /// [`EXIT_POLL_INTERVAL`] until either output resumes or the child is gone.
    ///
    /// No output can be lost by reaping here: the crate's stream yields every
    /// buffered line before it even looks at the terminal event, and `finish()`
    /// publishes the outcome from its reap *before* it joins the output pumps.
    async fn next_event(&mut self) -> Option<processkit::ProcessEvent> {
        // Field-wise borrows so the `select!` below can hold `&mut stream` in one
        // branch while the other reads `process`/`finish` and sets `reap_started`.
        let EventsDrive {
            stream,
            process,
            finish,
            reap_started,
            probe_after,
        } = self;
        loop {
            if *reap_started {
                // The reap is under way (or belongs to someone else): the terminal
                // event is coming, so just drain.
                return stream.next().await;
            }
            // Both branches are cancel-safe: `next()` pops from the shared sink
            // only when it resolves, and the timer branch owns nothing at all —
            // the probe it runs is synchronous, so no await point in this drive
            // ever holds the process (or the slot's lock).
            tokio::select! {
                biased;
                event = stream.next() => {
                    // Output is flowing again: the next quiet moment gets an
                    // immediate probe rather than waiting out the idle cadence.
                    *probe_after = Duration::ZERO;
                    match event {
                        Some(event) => return Some(event),
                        None => return None,
                    }
                },
                _ = tokio::time::sleep(*probe_after) => {
                    match probe_exit_now(process) {
                        ProbeVerdict::Exited => {
                            *reap_started = start_joint_finish(process, finish);
                        }
                        // Nothing to reap here — whoever took the process will
                        // publish the terminal event.
                        ProbeVerdict::NoProcess => *reap_started = true,
                        // Still running and still quiet: settle into the idle
                        // cadence instead of spinning on a zero-length wait.
                        ProbeVerdict::Running => *probe_after = EXIT_POLL_INTERVAL,
                    }
                    continue;
                }
            }
        }
    }

    /// Pull the next output-line event while preserving the historical
    /// `output_events()` contract. Lifecycle-only events are skipped here, but
    /// remain available through `lifecycle_events()`.
    async fn next_line(&mut self) -> Option<PyOutputEvent> {
        loop {
            match self.next_event().await {
                Some(event) => match PyOutputEvent::from_event(event) {
                    Some(line) => return Some(line),
                    None => continue,
                },
                None => return None,
            }
        }
    }
}

/// Hand the run to a background `finish()` so the events stream can receive its
/// terminal event, publishing the task for the handle's consuming verb. Returns
/// whether the reap is now under way.
fn start_joint_finish(process: &SharedProcess, finish: &FinishSlot) -> bool {
    let mut slot = finish.lock().unwrap_or_else(PoisonError::into_inner);
    if !matches!(*slot, JointFinish::NotStarted) {
        // Already started (or already claimed) — never start a second one.
        return true;
    }
    let Some(running) = process
        .lock()
        .unwrap_or_else(PoisonError::into_inner)
        .take()
    else {
        // A consuming verb won the race for the process; it owns the reap.
        return true;
    };
    // Spawned, not merely stored in this drive, so it makes progress even if the
    // consumer stops iterating (`break`s out of the loop) — the handle's verb can
    // then await it, and both of the handle's teardown paths (`__exit__`/
    // `__aexit__` via `teardown`, and `Drop`) abort it, dropping the process and
    // taking the tree down exactly as dropping an un-finished handle always did.
    // Every one of those paths goes through the `finish` slot, so this task is
    // never left as the only thing standing between a `break` and an orphaned tree.
    *slot = JointFinish::Running(tokio::spawn(async move { running.finish().await }));
    true
}

/// An async iterator over stdout *and* stderr as interleaved `OutputEvent`s.
///
/// Wraps the crate's `ProcessEvents` (renamed from `OutputEvents` in crate 3.0.0)
/// but keeps the Python name and semantics: it yields *output lines only*, and
/// ends when the child's output does. See [`EventsDrive`] for how that survives
/// 3.0.0's "the terminal event arrives at reap time" rule without deadlocking the
/// documented `async for …` / `await proc.afinish()` order.
#[pyclass(name = "OutputEvents", module = "processkit")]
pub(crate) struct PyOutputEvents {
    inner: Arc<Mutex<EventsDrive>>,
    // The idle-timeout watchdog, if the originating command set `idle_timeout`.
    // Watches the interleaved stream, so any *piped* stream (stdout or stderr)
    // resets the clock — a file-redirected/inherited stream simply contributes
    // no events (see `Command.idle_timeout`'s docstring).
    idle: Option<IdleGuard>,
}

#[pymethods]
impl PyOutputEvents {
    fn __aiter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __anext__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stream = self.inner.clone();
        let idle = self.idle.clone();
        drive_async_py(py, async move {
            let mut guard = stream.lock().await;
            match idle {
                Some(guard_idle) => {
                    // Bound the wait in a `let`, not directly as a `match`
                    // scrutinee, so the timed-out `next_line` future is dropped
                    // before the watchdog's `kill()` runs below rather than
                    // outliving the arm: nothing half-driven is left in flight
                    // while the kill is issued. (The drive holds no part of the
                    // process — see `probe_exit_now` — so the kill finds the slot
                    // populated either way; this just keeps the ordering obvious.)
                    let step = tokio::time::timeout(guard_idle.window, guard.next_line()).await;
                    match step {
                        Ok(Some(line)) => Ok(line),
                        Ok(None) => Err(PyStopAsyncIteration::new_err(())),
                        Err(_elapsed) => {
                            guard_idle.kill();
                            Err(idle_timeout_err(guard_idle.window.as_secs_f64()))
                        }
                    }
                }
                None => match guard.next_line().await {
                    Some(line) => Ok(line),
                    None => Err(PyStopAsyncIteration::new_err(())),
                },
            }
        })
    }
}

/// An async iterator over stderr lines. The core exposes one merged lifecycle
/// stream, so this adapter drains stdout in the background and yields only the
/// stderr variants.
#[pyclass(name = "StderrLines", module = "processkit")]
pub(crate) struct PyStderrLines {
    inner: Arc<Mutex<EventsDrive>>,
    idle: Option<IdleGuard>,
}

#[pymethods]
impl PyStderrLines {
    fn __aiter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __anext__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stream = self.inner.clone();
        let idle = self.idle.clone();
        drive_async_py(py, async move {
            let mut guard = stream.lock().await;
            loop {
                let event = match &idle {
                    Some(guard_idle) => {
                        match tokio::time::timeout(guard_idle.window, guard.next_event()).await {
                            Ok(event) => event,
                            Err(_elapsed) => {
                                guard_idle.kill();
                                return Err(idle_timeout_err(guard_idle.window.as_secs_f64()));
                            }
                        }
                    }
                    None => guard.next_event().await,
                };
                match event {
                    Some(PkProcessEvent::Stderr(line)) => return Ok(line.into_text()),
                    // A stdout line still resets the idle window; it is simply
                    // not part of this stderr-only iterator's public output.
                    Some(_) => continue,
                    None => return Err(PyStopAsyncIteration::new_err(())),
                }
            }
        })
    }
}

/// An async iterator over the complete ordered process lifecycle.
#[pyclass(name = "LifecycleEvents", module = "processkit")]
pub(crate) struct PyLifecycleEvents {
    inner: Arc<Mutex<EventsDrive>>,
    idle: Option<IdleGuard>,
}

#[pymethods]
impl PyLifecycleEvents {
    fn __aiter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __anext__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let stream = self.inner.clone();
        let idle = self.idle.clone();
        drive_async_py(py, async move {
            let mut guard = stream.lock().await;
            let event = match idle {
                Some(guard_idle) => {
                    let step = tokio::time::timeout(guard_idle.window, guard.next_event()).await;
                    match step {
                        Ok(event) => event,
                        Err(_elapsed) => {
                            guard_idle.kill();
                            return Err(idle_timeout_err(guard_idle.window.as_secs_f64()));
                        }
                    }
                }
                None => guard.next_event().await,
            };
            match event {
                Some(event) => Ok(PyLifecycleEvent::from(event)),
                None => Err(PyStopAsyncIteration::new_err(())),
            }
        })
    }
}

/// A handle to a started process: stream its output, write to its stdin, and
/// wait for its completion. The consuming verbs (`outcome`/`aoutcome`,
/// `finish`/`afinish`, `output`/`aoutput`, `output_bytes`/`aoutput_bytes`,
/// `profile`/`aprofile`, `shutdown`/`ashutdown`) each come in a sync/async
/// pair like everywhere else in this library — leave the handle spent after
/// either is called; using it afterwards raises. Usable as a context manager
/// (`with` / `async with`): exiting the block tears the process down — a hard
/// kill of the whole private tree for a standalone handle.
// `frozen` so every method takes `&self`: the consuming verbs used to take an
// exclusive `&mut self` PyO3 borrow and hold it across `block_on`/`drive_async`
// (i.e. across the whole wait, GIL released), so a concurrent `&self` call from
// another thread — even a plain getter or `__repr__` — raced the borrow flag
// and surfaced a raw `RuntimeError("Already borrowed")` instead of a typed
// `ProcessError`. The interior `Mutex<Option<...>>` serializes the access
// instead; the guard is always released (via the owned-returning helpers below)
// *before* any `block_on`/await, so a consumed handle reads back cleanly as
// `None` and the wait window is never held under the lock. The streaming
// handles (`ProcessStdin` and the output iterators) keep their own
// `tokio::sync::Mutex` for their async-held stream state — unchanged.
#[pyclass(name = "RunningProcess", module = "processkit", frozen)]
pub(crate) struct PyRunningProcess {
    // `None` after a consuming method has taken ownership of the process.
    // `Arc` (was a bare `StdMutex`) so an idle-timeout watchdog in a
    // output stream can share the very same slot and
    // hard-kill the child on silence through the one lock — no separate kill
    // channel that could race a consuming verb. Every access still funnels
    // through `lock()`, so the `Arc` is transparent to the methods below.
    pub(crate) inner: SharedProcess,
    // Retained by the binding because the crate's live handle keeps this
    // attribution internal, while Python-side streamed JSON conversion can fail.
    program: String,
    // The binding-only idle (inactivity) timeout carried from the `Command` this
    // handle was started from (`None` if unset). Applied to every stream the
    // streaming verbs hand out (see `idle_guard`).
    idle_timeout: Option<Duration>,
    // The finisher an `output_events()` stream started on this handle's behalf,
    // if any — see `EventsDrive`. `JointFinish::NotStarted` for every run that
    // never streams merged events, which is the only state the consuming verbs
    // below had to consider before crate 3.0.0.
    finish: FinishSlot,
}

impl PyRunningProcess {
    /// Wrap a freshly started crate process, carrying the originating
    /// `Command`'s binding-only idle-timeout onto the handle so its
    /// output streams enforce it. The single
    /// constructor every `start()`/`astart()` site (on `Command`, `Runner`/the
    /// doubles, and `ProcessGroup`) funnels through.
    pub(crate) fn started(
        running: PkRunningProcess,
        idle_timeout: Option<Duration>,
        program: String,
    ) -> Self {
        Self {
            inner: Arc::new(StdMutex::new(Some(running))),
            program,
            idle_timeout,
            finish: Arc::new(StdMutex::new(JointFinish::NotStarted)),
        }
    }

    /// Build the idle-timeout watchdog for a stream this handle is handing out
    /// (`None` when the command set no `idle_timeout`). Clones the shared process
    /// slot so the watchdog can kill through the one lock. Called *before* the
    /// slot is locked in the streaming verbs (an `Arc` clone takes no lock).
    fn idle_guard(&self) -> Option<IdleGuard> {
        self.idle_timeout.map(|window| IdleGuard {
            window,
            process: self.inner.clone(),
        })
    }

    /// Lock the inner slot, recovering from a (never-expected) poisoned mutex
    /// rather than panicking across the FFI boundary — the guarded sections only
    /// read/`as_mut`/`take` the handle and never panic, so poisoning cannot
    /// actually happen.
    fn lock(&self) -> StdMutexGuard<'_, Option<PkRunningProcess>> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Take the process out, returning `None` if the handle was already
    /// consumed. The lock is released before this returns, so a teardown never
    /// holds it across the subsequent `block_on`/await.
    fn take(&self) -> Option<PkRunningProcess> {
        self.lock().take()
    }

    /// Take the process out for a consuming verb, erroring if already consumed.
    /// Like `take`, releases the lock before returning.
    fn take_running(&self) -> PyResult<PkRunningProcess> {
        self.take()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))
    }

    /// Take whatever this handle still owns, leaving it spent: normally the live
    /// process, but — after an `output_events()` stream handed the run to its own
    /// finisher so the crate's lifecycle stream could complete (see
    /// `EventsDrive`) — that finisher's task instead. `None` once the handle has
    /// nothing left (a consuming verb, or a context-manager exit, already took
    /// it).
    ///
    /// Both callers below must go through here rather than reaching for the
    /// process slot alone: [`claim`](Self::claim) so a consuming verb reports the
    /// real run instead of raising "already consumed" for work the binding itself
    /// started, and the context-manager exits so their teardown is not silently
    /// skipped for exactly the same reason (see [`teardown`]).
    fn take_claim(&self) -> Option<Claimed> {
        {
            let mut slot = self.finish.lock().unwrap_or_else(PoisonError::into_inner);
            if let JointFinish::Running(_) = &*slot {
                let JointFinish::Running(task) = std::mem::replace(&mut *slot, JointFinish::Taken)
                else {
                    unreachable!("just matched JointFinish::Running")
                };
                return Some(Claimed::Joint(task));
            }
        }
        if let Some(running) = self.take() {
            return Some(Claimed::Process(Box::new(running)));
        }
        // `start_joint_finish` publishes `Running` while holding the finish lock,
        // but takes the process under that same lock first. It can therefore win
        // between our first finish check and `take()` above, leaving the process
        // empty only because the joint finisher now owns it. Re-check once after
        // an empty take: the NotStarted -> Running transition is one-shot, so this
        // closes that publication race without spinning or changing lock order.
        let mut slot = self.finish.lock().unwrap_or_else(PoisonError::into_inner);
        if let JointFinish::Running(_) = &*slot {
            let JointFinish::Running(task) = std::mem::replace(&mut *slot, JointFinish::Taken)
            else {
                unreachable!("just matched JointFinish::Running")
            };
            return Some(Claimed::Joint(task));
        }
        None
    }

    /// Claim the run for a consuming verb — [`take_claim`](Self::take_claim) with
    /// the "already consumed" error every other consuming path raises.
    fn claim(&self) -> PyResult<Claimed> {
        self.take_claim()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))
    }

    /// Like [`claim`](Self::claim), but for the verbs that cannot be answered from
    /// a joint finisher's `Finished` — `output`/`output_bytes` (they capture
    /// streams this run already streamed away) and `profile` (it must sample a
    /// *live* run). Reaching them once an `output_events()` stream has taken the
    /// run over was already a degenerate call — stdout was consumed by the stream
    /// and stderr was delivered as events, so both returned empty captures — and
    /// it is now diagnosed instead, naming the verbs that do report the run.
    ///
    /// **Where the boundary actually is**, since the public docs state it and
    /// tests pin it: the slot leaves `JointFinish::NotStarted` the moment the
    /// drive's probe first observes the child exited (see `start_joint_finish`) —
    /// *not* when the iterator is exhausted. Draining to the end always gets
    /// there in the ordinary single-consumer flow (the stream cannot reach its
    /// terminal event before the run is reaped, and with no other verb in play
    /// this drive is what reaps it), but so does a `break` out of a command that
    /// exited while it was being read — the `__anext__` that handed over the last
    /// line may well be the one that armed the finisher. A `break` taken while
    /// the child is **still running** does not get there: nothing polls the drive
    /// afterwards, so the probe never runs again, the run stays in this handle's
    /// slot, and these verbs keep their pre-3.0 behaviour (`output`/`output_bytes`
    /// wait for exit and return empty captures with a real outcome; `profile`
    /// samples the rest of the run). Deliberately left that way — the narrowing is
    /// only what the joint finisher forces, never a wider rule applied for
    /// tidiness. Both sides are covered in `tests/test_streaming.py`
    /// (`test_capture_verbs_after_an_early_break_from_an_exited_child_are_diagnosed`,
    /// `test_capture_verbs_still_report_a_run_left_while_the_child_was_running`).
    /// (A consuming verb on another task that claimed the process first leaves
    /// this slot untouched — `ProbeVerdict::NoProcess`, so the drive just drains —
    /// and these verbs then raise the ordinary "handle has been consumed".)
    ///
    /// This **is** a narrowing of the public contract, deliberately taken rather
    /// than papered over, and recorded as such: BREAKING in `CHANGELOG.md`, on
    /// each of the six verbs' docstrings, and in `docs/streaming.md`. Reproducing
    /// the old return values is not simply a matter of reshaping `Finished`: a
    /// `ProcessResult` rebuilt from it would have to fabricate the telemetry the
    /// run no longer carries here (`total_lines`/`total_bytes`, `timeout`,
    /// `ok_codes`), and the crate's `RunProfile` is `#[non_exhaustive]`, so a
    /// profile of an already-finished run cannot be constructed at all. A clear
    /// error naming the verbs that *do* report the run beats a value that is
    /// empty for reasons the caller cannot see.
    fn take_running_uncaptured(&self, verb: &str) -> PyResult<PkRunningProcess> {
        if let JointFinish::Running(_) | JointFinish::Taken =
            &*self.finish.lock().unwrap_or_else(PoisonError::into_inner)
        {
            return Err(ProcessError::new_err(format!(
                "{verb}() cannot report a run whose output was streamed with \
                 output_events(): that stream consumed stdout, delivered stderr \
                 as events, and took over finishing the run. Use finish()/\
                 afinish() (outcome + stderr) or outcome()/aoutcome() instead."
            )));
        }
        self.take_running()
    }
}

/// Shared teardown for both `__exit__` and `__aexit__`: a hard kill of the
/// direct child, then wait for it to be reaped.
///
/// Order is load-bearing: `start_kill` before `wait`. Killing first guarantees
/// `wait` reaps promptly even when stdin was handed out via `take_stdin()`
/// (the handle no longer owns the pipe to auto-close on a `keep_stdin_open`
/// child). `start_kill`/`wait` only touch the direct child; the *whole
/// private tree* is reaped when `wait` consumes `running` and drops its owned
/// process group, whose `Drop` is kernel kill-on-close. So moving `running`
/// into `wait` is not redundant.
async fn kill_and_reap(mut running: PkRunningProcess) -> processkit::Result<()> {
    running.start_kill()?;
    running.wait().await?;
    Ok(())
}

/// Tear down whatever [`PyRunningProcess::take_claim`] handed over, for `__exit__`
/// and `__aexit__`.
///
/// The `Joint` arm is the one crate-3.0 added, and it is load-bearing rather than
/// a formality: once an `output_events()` stream has observed the child exit it
/// moves the run into a background `finish()` (see `start_joint_finish`), so from
/// that moment the process slot is empty. A teardown that only looked at the slot
/// would find nothing and become a silent no-op — the *exact* failure mode
/// `probe_exit_now`'s doc calls the worst one ("an orphaned tree until the objects
/// were collected"), reintroduced through the finisher instead of the probe. It is
/// reachable from ordinary code: `break` out of the loop over a command that
/// already exited but left a grandchild holding the pipe, and the finisher parks
/// on that pipe — for as long as the grandchild lives — with the block long since
/// exited.
///
/// Aborting the finisher is what tears the tree down: its task owns the
/// `RunningProcess`, and dropping one kills its whole private tree (the same
/// kill-on-drop that has always backed this context manager). The result the
/// finisher would have produced is discarded, which is correct for a teardown —
/// `__exit__` never reported an outcome, and a caller who wants one calls
/// `finish()`/`outcome()` *inside* the block, which claims the same task and
/// leaves this a no-op.
///
/// `await`ing the aborted handle is what makes it *deterministic*: `abort()` only
/// schedules cancellation, so returning right after it would hand back to Python
/// with the process not yet dropped. The join resolves only once the task has been
/// dropped — process included — so by the time the `with` block is left the tree
/// is gone, not merely doomed. (A finisher that already completed is not
/// cancellable, and its join returns at once; that is the common drained-to-the-end
/// case, where the process was dropped by the finisher itself.) A `JoinError` is
/// deliberately ignored: cancellation *is* the expected outcome here, and a
/// panicked finisher has already dropped its process too.
async fn teardown(claimed: Claimed) -> processkit::Result<()> {
    match claimed {
        Claimed::Process(running) => kill_and_reap(*running).await,
        Claimed::Joint(task) => {
            task.abort();
            let _ = task.await;
            Ok(())
        }
    }
}

#[pymethods]
impl PyRunningProcess {
    /// The OS process id, or `None` once the handle has been consumed/reaped.
    #[getter]
    fn pid(&self) -> Option<u32> {
        self.lock().as_ref().and_then(|running| running.pid())
    }

    /// Seconds elapsed since the process started, or `None` once consumed.
    #[getter]
    fn elapsed_seconds(&self) -> Option<f64> {
        self.lock().as_ref().map(|r| r.elapsed().as_secs_f64())
    }

    /// Cumulative CPU time so far in seconds, if measurable (`None` otherwise).
    #[getter]
    fn cpu_time_seconds(&self) -> Option<f64> {
        self.lock()
            .as_ref()
            .and_then(|r| r.cpu_time())
            .map(|d| d.as_secs_f64())
    }

    /// Peak resident memory so far in bytes, if measurable (`None` otherwise).
    #[getter]
    fn peak_memory_bytes(&self) -> Option<u64> {
        self.lock().as_ref().and_then(|r| r.peak_memory_bytes())
    }

    /// Number of stdout lines captured so far (`None` once consumed).
    #[getter]
    fn stdout_line_count(&self) -> Option<usize> {
        self.lock().as_ref().map(|r| r.stdout_line_count())
    }

    /// Number of stderr lines captured so far (`None` once consumed).
    #[getter]
    fn stderr_line_count(&self) -> Option<usize> {
        self.lock().as_ref().map(|r| r.stderr_line_count())
    }

    /// Whether this handle owns a private tree — i.e. dropping it (or exiting its
    /// context manager) hard-kills the whole tree. `False` for a handle started
    /// inside a shared `ProcessGroup`; `None` once consumed.
    #[getter]
    fn owns_group(&self) -> Option<bool> {
        self.lock().as_ref().map(|r| r.kills_tree_on_drop())
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    /// Context-manager exit: tear the process down deterministically — a hard
    /// kill of the whole private tree for a standalone `start()`/`astart()`
    /// handle, or just this child for one started inside a `ProcessGroup`. A
    /// no-op if a consuming verb (`outcome`/`finish`/`output`/`output_bytes`/
    /// `profile`/`shutdown`, or their `a`-prefixed twins) already took the
    /// handle. Never suppresses an exception raised inside the block.
    ///
    /// Goes through `take_claim`, not the process slot alone, so a run an
    /// `output_events()` stream handed to its own background finisher is torn down
    /// here too rather than left to that finisher (and, failing it, to the GC) —
    /// see [`teardown`].
    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __exit__(
        &self,
        py: Python<'_>,
        _exc_type: Option<Bound<'_, PyAny>>,
        _exc_value: Option<Bound<'_, PyAny>>,
        _traceback: Option<Bound<'_, PyAny>>,
    ) -> PyResult<bool> {
        // Check before taking: a reentrant-runtime error from `block_on` after the
        // handle is taken would drop (kill-on-drop) a process the caller could
        // otherwise have torn down correctly from the right context. `take_claim()`
        // releases both locks before `block_on`, so a concurrent getter/`__repr__`
        // on another thread reads back `None` cleanly rather than blocking on the
        // teardown wait.
        reject_reentrant_runtime()?;
        if let Some(claimed) = self.take_claim() {
            block_on(py, teardown(claimed))?;
        }
        Ok(false)
    }

    fn __aenter__<'py>(slf: Py<Self>, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        drive_async_py(py, async move { Ok(slf) })
    }

    /// Async counterpart of `__exit__`.
    #[pyo3(signature = (_exc_type=None, _exc_value=None, _traceback=None))]
    fn __aexit__<'py>(
        &self,
        py: Python<'py>,
        _exc_type: Option<Bound<'py, PyAny>>,
        _exc_value: Option<Bound<'py, PyAny>>,
        _traceback: Option<Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        // Check before taking: with no running event loop the taken handle would
        // otherwise be wrapped in a never-awaitable lazy future whose only fate
        // is kill-on-drop, silently spending it instead of leaving it in place
        // for the caller to retry correctly. See `require_event_loop`.
        require_event_loop(py)?;
        let claimed = self.take_claim();
        drive_async(py, async move {
            if let Some(claimed) = claimed {
                teardown(claimed).await?;
            }
            Ok::<bool, processkit::Error>(false)
        })
    }

    /// An async iterator over stdout, line by line:
    /// `async for line in proc.stdout_lines(): ...`.
    fn stdout_lines(&self) -> PyResult<PyStdoutLines> {
        // Setting up the stream spawns a pump task, so it must run inside the
        // tokio runtime context. Holding the std lock across this sync call is
        // safe: it does not await, so it cannot deadlock a concurrent verb.
        // Build the watchdog before locking (an `Arc` clone takes no lock).
        let idle = self.idle_guard();
        let _guard = runtime()?.enter();
        let mut inner = self.lock();
        let running = inner
            .as_mut()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
        let lines = running.stdout_lines().map_err(map_err)?;
        Ok(PyStdoutLines {
            inner: Arc::new(Mutex::new(lines)),
            idle,
        })
    }

    /// An async iterator over stdout, one deserialized JSON value per line:
    /// `async for obj in proc.stdout_json_lines(): ...`. Strict NDJSON framing —
    /// every line, including a blank one, must independently parse as JSON. A
    /// malformed line raises `InvalidJson` (carrying the crate's own
    /// line/column/byte-offset diagnostic and a bounded fragment of that line in
    /// its message, plus `.program` — but, unlike `run_json()`/`arun_json()`,
    /// **no** `.stdout`: a streamed run never buffers the whole payload the way
    /// those do) and the stream continues with the next line, exactly like every
    /// other malformed-item case in this library.
    ///
    /// Same one-shot-stdout, same-idle-timeout, and same consuming/streaming-
    /// conflict rules as `stdout_lines()` (they share one crate-level stdout
    /// pump) — call this **once**, and never after another consumer already
    /// took stdout.
    fn stdout_json_lines(&self) -> PyResult<PyJsonLines> {
        // Setting up the stream spawns a pump task, so it must run inside the
        // tokio runtime context, exactly like `stdout_lines()` above.
        let idle = self.idle_guard();
        let _guard = runtime()?.enter();
        let mut inner = self.lock();
        let running = inner
            .as_mut()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
        let lines = running
            .stdout_json_lines::<Box<RawValue>>()
            .map_err(map_err)?;
        Ok(PyJsonLines {
            inner: Arc::new(Mutex::new(lines)),
            program: self.program.clone(),
            idle,
        })
    }

    /// An async iterator over stderr, line by line. This consumes the merged
    /// lifecycle stream, discards stdout lines, and preserves normal
    /// finish/outcome reporting through the shared finisher.
    fn stderr_lines(&self) -> PyResult<PyStderrLines> {
        let idle = self.idle_guard();
        let _guard = runtime()?.enter();
        let events = {
            let mut inner = self.lock();
            let running = inner
                .as_mut()
                .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
            running.events().map_err(map_err)?
        };
        Ok(PyStderrLines {
            inner: Arc::new(Mutex::new(EventsDrive {
                stream: events,
                process: self.inner.clone(),
                finish: self.finish.clone(),
                reap_started: false,
                probe_after: Duration::ZERO,
            })),
            idle,
        })
    }

    /// An async iterator over stdout and stderr as interleaved `OutputEvent`s.
    ///
    /// Backed by the crate's `events()` (`output_events()` before crate 3.0.0):
    /// the same merged stream, now carrying the whole process lifecycle. Only its
    /// line events reach Python, and the stream it hands back drives the run's
    /// finisher alongside itself so the documented "drain, then `afinish()`" order
    /// still terminates — see `EventsDrive`.
    fn output_events(&self) -> PyResult<PyOutputEvents> {
        let idle = self.idle_guard();
        let _guard = runtime()?.enter();
        let events = {
            let mut inner = self.lock();
            let running = inner
                .as_mut()
                .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
            running.events().map_err(map_err)?
        };
        Ok(PyOutputEvents {
            inner: Arc::new(Mutex::new(EventsDrive {
                stream: events,
                process: self.inner.clone(),
                finish: self.finish.clone(),
                reap_started: false,
                // Probe on the first quiet moment: a command that finishes before
                // (or while) its output is drained is then noticed at once.
                probe_after: Duration::ZERO,
            })),
            idle,
        })
    }

    /// The complete ordered lifecycle: started, output lines, then exited.
    fn lifecycle_events(&self) -> PyResult<PyLifecycleEvents> {
        let idle = self.idle_guard();
        let _guard = runtime()?.enter();
        let events = {
            let mut inner = self.lock();
            let running = inner
                .as_mut()
                .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
            running.events().map_err(map_err)?
        };
        Ok(PyLifecycleEvents {
            inner: Arc::new(Mutex::new(EventsDrive {
                stream: events,
                process: self.inner.clone(),
                finish: self.finish.clone(),
                reap_started: false,
                probe_after: Duration::ZERO,
            })),
            idle,
        })
    }

    /// Take the writable stdin handle. Raises `ProcessError` if stdin was not
    /// kept open (build the `Command` with `keep_stdin_open()`) or was already
    /// taken — so a missing setup fails here with a clear message, not later with
    /// an `AttributeError` on a `None`.
    fn take_stdin(&self) -> PyResult<PyProcessStdin> {
        let mut inner = self.lock();
        let running = inner
            .as_mut()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
        running
            .take_stdin()
            .map(|stdin| PyProcessStdin {
                inner: Arc::new(Mutex::new(Some(stdin))),
            })
            .ok_or_else(|| {
                ProcessError::new_err(
                    "stdin is not available — build the Command with keep_stdin_open() \
                     and call take_stdin() only once (scripted test doubles never \
                     provide stdin)",
                )
            })
    }

    /// Resize a live pseudo-terminal. Raises `Unsupported` for a non-PTY run or
    /// a terminal whose child has already exited.
    fn resize_pty(&self, cols: u16, rows: u16) -> PyResult<()> {
        if cols == 0 || rows == 0 {
            return Err(PyValueError::new_err(
                "resize_pty cols and rows must both be positive",
            ));
        }
        let mut inner = self.lock();
        let running = inner
            .as_mut()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
        running.resize_pty(cols, rows).map_err(map_err)
    }

    /// Begin tearing the tree down without waiting. (Dropping the handle, or the
    /// owning group, also kills it; this just starts it early.) Mirrors
    /// `subprocess.Popen.kill()`: fire-and-forget, does not wait for exit.
    fn kill(&self) -> PyResult<()> {
        let _guard = runtime()?.enter();
        let mut inner = self.lock();
        let running = inner
            .as_mut()
            .ok_or_else(|| ProcessError::new_err("the process handle has been consumed"))?;
        running.start_kill().map_err(map_err)
    }

    /// Wait for exit and return the `Outcome`. Consumes the handle. The
    /// synchronous twin of `aoutcome()` — usable on a handle from either
    /// `start()` or `astart()`, like every other sync/async verb pair in
    /// this library.
    fn outcome(&self, py: Python<'_>) -> PyResult<PyOutcome> {
        // Checked before `claim()`: see the comment on `reject_reentrant_runtime`.
        reject_reentrant_runtime()?;
        match self.claim()? {
            Claimed::Process(running) => {
                block_on(py, async move { running.wait().await }).map(PyOutcome::from)
            }
            // The events stream's finisher already observed this run; its
            // `Finished.outcome` is the very value `wait()` would return (the
            // crate reports one `Outcome`, not a parallel one per finisher).
            Claimed::Joint(task) => {
                block_on_interruptible(py, joint_finished(task))?.map(|f| f.into_outcome())
            }
        }
    }

    /// Async counterpart of `outcome()`. (Named `aoutcome`, not `await` — a
    /// reserved word can't be a method name.)
    fn aoutcome<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        // Checked before `claim()`: see the comment on `require_event_loop`.
        require_event_loop(py)?;
        match self.claim()? {
            Claimed::Process(running) => {
                drive_async(py, async move { running.wait().await.map(PyOutcome::from) })
            }
            Claimed::Joint(task) => drive_async_py(py, async move {
                joint_finished(task).await.map(|f| f.into_outcome())
            }),
        }
    }

    /// Wait for exit and return `Finished` (outcome + captured stderr) without
    /// buffering stdout — use this after streaming stdout. Consumes the handle.
    fn finish(&self, py: Python<'_>) -> PyResult<PyFinished> {
        reject_reentrant_runtime()?;
        match self.claim()? {
            Claimed::Process(running) => {
                block_on(py, async move { running.finish().await }).map(PyFinished::from)
            }
            Claimed::Joint(task) => block_on_interruptible(py, joint_finished(task))?,
        }
    }

    /// Async counterpart of `finish()`.
    fn afinish<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        match self.claim()? {
            Claimed::Process(running) => {
                drive_async(
                    py,
                    async move { running.finish().await.map(PyFinished::from) },
                )
            }
            Claimed::Joint(task) => drive_async_py(py, joint_finished(task)),
        }
    }

    /// Wait for exit and capture the full `ProcessResult`. Consumes the handle.
    ///
    /// Raises `ProcessError` once an `output_events()` stream has taken this run
    /// over — which it does as soon as it observes the child exit, whether or not
    /// the caller iterated to the end: that stream consumed stdout, delivered
    /// stderr as events and completed the run, so there is nothing left to
    /// capture — report such a run with `finish()`/`afinish()` or
    /// `outcome()`/`aoutcome()`. Stopping the iteration while the child still
    /// runs leaves the run here, and this behaves as it did before crate 3.0
    /// (empty captures with a real outcome).
    fn output(&self, py: Python<'_>) -> PyResult<PyProcessResult> {
        reject_reentrant_runtime()?;
        let running = self.take_running_uncaptured("output")?;
        block_on(py, async move { running.output_string().await }).map(PyProcessResult::from)
    }

    /// Async counterpart of `output()` — same `output_events()` restriction.
    fn aoutput<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        let running = self.take_running_uncaptured("aoutput")?;
        drive_async(py, async move {
            running.output_string().await.map(PyProcessResult::from)
        })
    }

    /// Wait for exit and capture the full raw-bytes `BytesResult`. Consumes the
    /// handle. Raises `ProcessError` once an `output_events()` stream has taken
    /// the run over, under the same condition and for the same reason as
    /// `output()`.
    fn output_bytes(&self, py: Python<'_>) -> PyResult<PyBytesResult> {
        reject_reentrant_runtime()?;
        let running = self.take_running_uncaptured("output_bytes")?;
        block_on(py, async move { running.output_bytes().await }).map(PyBytesResult::from)
    }

    /// Async counterpart of `output_bytes()` — same `output_events()` restriction.
    fn aoutput_bytes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        let running = self.take_running_uncaptured("aoutput_bytes")?;
        drive_async(py, async move {
            running.output_bytes().await.map(PyBytesResult::from)
        })
    }

    /// Wait for exit while sampling resource usage every `every_seconds`,
    /// returning a `RunProfile`. Consumes the handle.
    ///
    /// Raises `ProcessError` once an `output_events()` stream has taken this run
    /// over — which it does as soon as it observes the child exit, whether or not
    /// the caller iterated to the end: the run is over, so there is no live run
    /// left to sample — use `finish()`/`afinish()` or `outcome()`/`aoutcome()`.
    /// Stopping the iteration while the child still runs leaves the run here, and
    /// this still profiles the rest of it.
    fn profile(&self, py: Python<'_>, every_seconds: f64) -> PyResult<PyRunProfile> {
        let every = positive_duration(every_seconds, "every_seconds")?;
        reject_reentrant_runtime()?;
        let running = self.take_running_uncaptured("profile")?;
        block_on(py, async move { running.profile(every).await }).map(PyRunProfile::from)
    }

    /// Async counterpart of `profile()` — same `output_events()` restriction.
    fn aprofile<'py>(&self, py: Python<'py>, every_seconds: f64) -> PyResult<Bound<'py, PyAny>> {
        let every = positive_duration(every_seconds, "every_seconds")?;
        require_event_loop(py)?;
        let running = self.take_running_uncaptured("aprofile")?;
        drive_async(py, async move {
            running.profile(every).await.map(PyRunProfile::from)
        })
    }

    /// Gracefully tear down (signal, wait up to `grace_seconds`, then kill) and
    /// return the `Outcome`. Consumes the handle. Named `shutdown`/`ashutdown`
    /// to match `ProcessGroup.shutdown()`/`ashutdown()` — same verb, same
    /// sync/async pairing convention, unlike the pre-1.1 `RunningProcess`
    /// where `shutdown()` was itself a coroutine (a trap: the same verb name
    /// meant "call it" on a `ProcessGroup` but "await it" here).
    ///
    /// **Why the joint arm reports instead of escalating**, since it is the one
    /// place `grace_seconds` stops bounding the call: that arm is only reachable
    /// once the events stream observed the child *exit*, so there is nothing left
    /// to signal, and the escalation the grace would trigger has nothing to kill
    /// but pipe-holding descendants. Awaiting the finisher is what yields the real
    /// `Outcome` — and it drops the process (tearing the tree down) as it returns.
    /// Cutting it short instead would kill the remnant tree sooner but leave this
    /// verb with no outcome to return at all: the run's exit status lives only
    /// inside that finisher (the crate exposes none on a reaped-but-unfinished
    /// handle), so a bounded variant could only raise. `finish()`/`afinish()` wait
    /// on the same descendants for the same reason, before and after crate 3.0 —
    /// so this stays consistent with them, and the *bounded* teardown is the
    /// context manager (`with`/`async with`), which hard-kills the tree without
    /// reporting an outcome. `block_on_interruptible` keeps `Ctrl+C` working
    /// throughout.
    fn shutdown(&self, py: Python<'_>, grace_seconds: f64) -> PyResult<PyOutcome> {
        let grace = nonnegative_duration(grace_seconds, "grace_seconds")?;
        reject_reentrant_runtime()?;
        match self.claim()? {
            Claimed::Process(running) => {
                block_on(py, async move { running.shutdown(grace).await }).map(PyOutcome::from)
            }
            Claimed::Joint(task) => {
                block_on_interruptible(py, joint_finished(task))?.map(|f| f.into_outcome())
            }
        }
    }

    /// Async counterpart of `shutdown()`.
    fn ashutdown<'py>(&self, py: Python<'py>, grace_seconds: f64) -> PyResult<Bound<'py, PyAny>> {
        let grace = nonnegative_duration(grace_seconds, "grace_seconds")?;
        require_event_loop(py)?;
        match self.claim()? {
            Claimed::Process(running) => drive_async(py, async move {
                running.shutdown(grace).await.map(PyOutcome::from)
            }),
            Claimed::Joint(task) => drive_async_py(py, async move {
                joint_finished(task).await.map(|f| f.into_outcome())
            }),
        }
    }

    fn __repr__(&self) -> String {
        match self.lock().as_ref() {
            Some(running) => format!("RunningProcess(pid={:?})", running.pid()),
            None => "RunningProcess(consumed)".to_string(),
        }
    }
}

/// Preserve kill-on-drop — "dropping the handle tears its tree down" — through
/// both places crate 3.0's streaming rework can otherwise strand the process.
///
/// 1. **The events stream's background finisher** (see `EventsDrive`): the run may
///    live inside a spawned task rather than this handle's slot. Aborting the task
///    drops the process it owns, which restores exactly the old behaviour. A no-op
///    in every ordinary case — a task that already completed cannot be cancelled,
///    and a consuming verb (or a context-manager exit) that claimed it left
///    `JointFinish::Taken` behind.
/// 2. **The shared process slot itself.** The slot is an `Arc` so a stream's idle
///    watchdog and events drive can address the one process through the one lock —
///    but it is this handle's *own* slot, not shared ownership, so the drop must
///    empty it explicitly instead of letting the last `Arc` holder decide when the
///    child dies. Without this, a live `output_events()` (or idle-timeout
///    `stdout_lines()`) object outliving the handle would keep the whole tree alive
///    past the drop, silently downgrading kill-on-drop to "…once the last stream
///    object is collected too". The other holders already handle an empty slot:
///    `IdleGuard::kill` becomes a no-op, the drive's probe reads `NoProcess` and
///    just drains a stream that is about to hit EOF anyway (the tree is gone).
impl Drop for PyRunningProcess {
    fn drop(&mut self) {
        if let JointFinish::Running(task) =
            &*self.finish.lock().unwrap_or_else(PoisonError::into_inner)
        {
            task.abort();
        }
        // Taken (and dropped) *after* the finish guard above is released, keeping
        // the one lock order every other path uses: `finish` then `process`.
        drop(self.take());
    }
}

/// Register this module's pyclasses (`RunningProcess`, `ProcessStdin`,
/// `StdoutLines`, `JsonLines`, `StderrLines`, `OutputEvents`, `LifecycleEvents`)
/// on `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyRunningProcess>()?;
    m.add_class::<PyProcessStdin>()?;
    m.add_class::<PyStdoutLines>()?;
    m.add_class::<PyJsonLines>()?;
    m.add_class::<PyStderrLines>()?;
    m.add_class::<PyOutputEvents>()?;
    m.add_class::<PyLifecycleEvents>()?;
    Ok(())
}
