//! The async streaming/interactive handles: `RunningProcess` plus its
//! `ProcessStdin`, `StdoutLines`, and `OutputEvents`.

use std::sync::{Arc, Mutex as StdMutex, MutexGuard as StdMutexGuard, PoisonError};
use std::time::Duration;

use processkit::prelude::StreamExt;
use processkit::Finished as PkFinished;
// Crate 3.0.0 renamed `OutputEvents` -> `ProcessEvents` (and the verb
// `output_events()` -> `events()`) as the merged stream widened from output to
// the whole process lifecycle. The Python names are unchanged — see
// `PyOutputEvents` below.
use processkit::ProcessEvents as PkProcessEvents;
use processkit::ProcessStdin as PkProcessStdin;
use processkit::RunningProcess as PkRunningProcess;
use processkit::StdoutLines as PkStdoutLines;
use pyo3::exceptions::{PyOSError, PyStopAsyncIteration, PyValueError};
use pyo3::prelude::*;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;

use crate::convert::{nonnegative_duration, positive_duration};
use crate::errors::{idle_timeout_err, map_err, ProcessError};
use crate::result::{
    PyBytesResult, PyFinished, PyOutcome, PyOutputEvent, PyProcessResult, PyRunProfile,
};
use crate::runtime::{
    block_on, block_on_interruptible, drive_async, drive_async_py, reject_reentrant_runtime,
    require_event_loop, runtime,
};

/// The shared process slot: `None` once a consuming verb has taken ownership.
/// Shared (via `Arc`) between the `RunningProcess` handle and any idle-timeout
/// watchdog living in one of its streams, so both address the one process
/// through the one `StdMutex` (no second, racing kill channel).
type SharedProcess = Arc<StdMutex<Option<PkRunningProcess>>>;

/// The idle-timeout watchdog carried by a `stdout_lines()` / `output_events()`
/// stream: the inactivity window plus a shared handle to the process to kill on
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
    /// A consuming verb already took the joint finisher's result.
    Taken,
}

type FinishSlot = Arc<StdMutex<JointFinish>>;

/// What a consuming verb (`finish`/`outcome`/`shutdown` & co.) found when it
/// claimed the run: either the live process, or the joint finisher the events
/// stream started.
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

/// Borrow the process out of the shared slot for the duration of one `&mut`
/// operation, putting it back when the borrow ends — **including when the future
/// holding this guard is cancelled mid-await**.
///
/// This is what lets the events stream run the crate's non-consuming exit probe
/// (which needs `&mut RunningProcess`) without spending the handle: the process
/// is out of the slot only while a `__anext__` future is actually parked, and it
/// is back in place the instant that future resolves or is dropped — so the idle
/// watchdog's `start_kill` (see [`IdleGuard`]) and the handle's own verbs find it
/// exactly where they expect.
struct ProcessLoan {
    slot: SharedProcess,
    running: Option<PkRunningProcess>,
}

impl ProcessLoan {
    fn take(slot: &SharedProcess) -> Self {
        let running = slot.lock().unwrap_or_else(PoisonError::into_inner).take();
        Self {
            slot: slot.clone(),
            running,
        }
    }
}

impl Drop for ProcessLoan {
    fn drop(&mut self) {
        if let Some(running) = self.running.take() {
            let mut guard = self.slot.lock().unwrap_or_else(PoisonError::into_inner);
            // The slot is empty for exactly as long as this loan lives — every
            // other taker leaves it empty and never refills it, and this type is
            // the only thing that puts a process back — so the guard below always
            // restores. It is checked rather than assumed because the alternative
            // (blindly overwriting) would drop, and therefore hard-kill, a tree
            // whichever owner resurrected the slot still means to drive. Not a
            // `debug_assert!`: this runs in a `Drop`, where a panic during an
            // unwind aborts the interpreter outright.
            if guard.is_none() {
                *guard = Some(running);
            }
        }
    }
}

/// What the non-consuming exit probe observed.
enum ProbeVerdict {
    /// The child has exited (and been reaped by the probe): its output pipes are
    /// at EOF, so the event stream is heading for its terminal park.
    Exited,
    /// There is no process to probe — a consuming verb (or a concurrent joint
    /// finisher) already owns the reap, so it will publish the terminal event.
    NoProcess,
}

/// Wait, **without consuming the handle**, until the child is observed to have
/// exited.
///
/// `RunningProcess::wait_for` is the crate's own readiness driver: it polls the
/// caller's predicate and, between polls, fails fast the moment the child is seen
/// to have exited ("An exited child can never become ready"). With a predicate
/// that is never ready and a horizon far past any real run, that fail-fast path
/// is the *only* way it returns — which makes it a public, non-consuming "has the
/// child exited yet?" wait. It takes `&mut self`, never `self`, and while an
/// `events()` stream is live its background-drain setup is a no-op (stdout is
/// already consumed by the stream, stderr's drain is idempotent), so it cannot
/// steal a line from the stream.
async fn await_child_exit(slot: SharedProcess) -> ProbeVerdict {
    let mut loan = ProcessLoan::take(&slot);
    let Some(running) = loan.running.as_mut() else {
        return ProbeVerdict::NoProcess;
    };
    // The horizon is clamped by the crate to ~10 years, so the deadline branch is
    // unreachable in practice and the return means "the child exited". Treating a
    // (hypothetical) deadline return the same way is still safe: it only starts
    // the finisher, which waits for the child rather than killing it.
    let _ = running
        .wait_for(|| std::future::ready(false), Duration::MAX)
        .await;
    ProbeVerdict::Exited
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

    /// Send a single control byte to the child's stdin.
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
}

impl EventsDrive {
    /// Pull the next *output line* event, driving the run's finisher alongside the
    /// stream so the stream can reach its end.
    ///
    /// The loop has two jobs beyond `stream.next()`:
    ///
    /// 1. **Filter.** Non-line lifecycle events (`Started`, `Exited`, and any kind
    ///    a later crate release adds) are skipped, never surfaced as an
    ///    `OutputEvent` with empty text — see `PyOutputEvent::from_event`.
    /// 2. **Start the reap, as late as possible.** The finisher is armed only once
    ///    the crate's own non-consuming probe reports the child has exited, i.e.
    ///    once the stream is provably heading for its terminal park. Arming it
    ///    earlier would work for the deadlock but would spend the handle for the
    ///    whole streamed run — `pid` and the live line counters would read `None`,
    ///    `kill()`/`take_stdin()` would raise, the idle watchdog would lose its
    ///    kill channel, and `finish()`'s own "close an untaken stdin" step would
    ///    send a `keep_stdin_open` child a premature EOF. Waiting for the exit
    ///    keeps every one of those observable behaviours exactly as it was.
    ///
    /// No output can be lost by reaping here: the crate's stream yields every
    /// buffered line before it even looks at the terminal event, and `finish()`
    /// publishes the outcome from its reap *before* it joins the output pumps.
    async fn next_line(&mut self) -> Option<PyOutputEvent> {
        // Field-wise borrows so the `select!` below can hold `&mut stream` in one
        // branch while the other reads `process`/`finish` and sets `reap_started`.
        let EventsDrive {
            stream,
            process,
            finish,
            reap_started,
        } = self;
        loop {
            if *reap_started {
                // The reap is under way (or belongs to someone else): the terminal
                // event is coming, so just drain.
                match stream.next().await {
                    Some(event) => match PyOutputEvent::from_event(event) {
                        Some(line) => return Some(line),
                        None => continue,
                    },
                    None => return None,
                }
            }
            // Both branches are cancel-safe: `next()` pops from the shared sink
            // only when it resolves, and the probe hands the process back to the
            // slot when its future is dropped (see `ProcessLoan`).
            tokio::select! {
                biased;
                event = stream.next() => match event {
                    Some(event) => match PyOutputEvent::from_event(event) {
                        Some(line) => return Some(line),
                        None => continue,
                    },
                    None => return None,
                },
                verdict = await_child_exit(process.clone()) => {
                    *reap_started = match verdict {
                        ProbeVerdict::Exited => start_joint_finish(process, finish),
                        // Nothing to reap here — whoever took the process will
                        // publish the terminal event.
                        ProbeVerdict::NoProcess => true,
                    };
                    continue;
                }
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
    // then await it, and the handle's `Drop` aborts it, dropping the process and
    // taking the tree down exactly as dropping an un-finished handle always did.
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
                    // scrutinee: that drops the timed-out `next_line` future — and
                    // with it the exit probe's `ProcessLoan`, returning the process
                    // to the shared slot — *before* the watchdog's `kill()` below
                    // looks for it. As a match scrutinee the future would outlive
                    // the arm and the kill would silently find an empty slot.
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
// handles (`ProcessStdin`/`StdoutLines`/`OutputEvents`) keep their own
// `tokio::sync::Mutex` for their async-held stream state — unchanged.
#[pyclass(name = "RunningProcess", module = "processkit", frozen)]
pub(crate) struct PyRunningProcess {
    // `None` after a consuming method has taken ownership of the process.
    // `Arc` (was a bare `StdMutex`) so an idle-timeout watchdog in a
    // `stdout_lines()`/`output_events()` stream can share the very same slot and
    // hard-kill the child on silence through the one lock — no separate kill
    // channel that could race a consuming verb. Every access still funnels
    // through `lock()`, so the `Arc` is transparent to the methods below.
    pub(crate) inner: SharedProcess,
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
    /// `stdout_lines()` / `output_events()` streams enforce it. The single
    /// constructor every `start()`/`astart()` site (on `Command`, `Runner`/the
    /// doubles, and `ProcessGroup`) funnels through.
    pub(crate) fn started(running: PkRunningProcess, idle_timeout: Option<Duration>) -> Self {
        Self {
            inner: Arc::new(StdMutex::new(Some(running))),
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

    /// Claim the run for a consuming verb: normally the live process, but — after
    /// an `output_events()` stream handed the run to its own finisher so the
    /// crate's lifecycle stream could complete (see `EventsDrive`) — that
    /// finisher's task instead, so the verb reports the real run rather than
    /// raising "already consumed" for work the binding itself started.
    fn claim(&self) -> PyResult<Claimed> {
        {
            let mut slot = self.finish.lock().unwrap_or_else(PoisonError::into_inner);
            if let JointFinish::Running(_) = &*slot {
                let JointFinish::Running(task) = std::mem::replace(&mut *slot, JointFinish::Taken)
                else {
                    unreachable!("just matched JointFinish::Running")
                };
                return Ok(Claimed::Joint(task));
            }
        }
        self.take_running()
            .map(|running| Claimed::Process(Box::new(running)))
    }

    /// Like [`claim`](Self::claim), but for the verbs that cannot be answered from
    /// a joint finisher's `Finished` — `output`/`output_bytes` (they capture
    /// streams this run already streamed away) and `profile` (it must sample a
    /// *live* run). Reaching them after a fully drained `output_events()` stream
    /// was already a degenerate call — stdout was consumed by the stream and
    /// stderr was delivered as events, so both returned empty captures — and it is
    /// now diagnosed instead, naming the verbs that do report the run.
    fn take_running_uncaptured(&self, verb: &str) -> PyResult<PkRunningProcess> {
        if let JointFinish::Running(_) | JointFinish::Taken =
            &*self.finish.lock().unwrap_or_else(PoisonError::into_inner)
        {
            return Err(ProcessError::new_err(format!(
                "{verb}() cannot report a run whose output was streamed with \
                 output_events(): that stream consumed stdout and delivered stderr \
                 as events, and completing it finished the run. Use finish()/\
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
        // otherwise have torn down correctly from the right context. `take()`
        // releases the lock before `block_on`, so a concurrent getter/`__repr__`
        // on another thread reads back `None` cleanly rather than blocking on the
        // teardown wait.
        reject_reentrant_runtime()?;
        if let Some(running) = self.take() {
            block_on(py, kill_and_reap(running))?;
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
        let running = self.take();
        drive_async(py, async move {
            if let Some(running) = running {
                kill_and_reap(running).await?;
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
    fn output(&self, py: Python<'_>) -> PyResult<PyProcessResult> {
        reject_reentrant_runtime()?;
        let running = self.take_running_uncaptured("output")?;
        block_on(py, async move { running.output_string().await }).map(PyProcessResult::from)
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        let running = self.take_running_uncaptured("aoutput")?;
        drive_async(py, async move {
            running.output_string().await.map(PyProcessResult::from)
        })
    }

    /// Wait for exit and capture the full raw-bytes `BytesResult`. Consumes the handle.
    fn output_bytes(&self, py: Python<'_>) -> PyResult<PyBytesResult> {
        reject_reentrant_runtime()?;
        let running = self.take_running_uncaptured("output_bytes")?;
        block_on(py, async move { running.output_bytes().await }).map(PyBytesResult::from)
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        require_event_loop(py)?;
        let running = self.take_running_uncaptured("aoutput_bytes")?;
        drive_async(py, async move {
            running.output_bytes().await.map(PyBytesResult::from)
        })
    }

    /// Wait for exit while sampling resource usage every `every_seconds`,
    /// returning a `RunProfile`. Consumes the handle.
    fn profile(&self, py: Python<'_>, every_seconds: f64) -> PyResult<PyRunProfile> {
        let every = positive_duration(every_seconds, "every_seconds")?;
        reject_reentrant_runtime()?;
        let running = self.take_running_uncaptured("profile")?;
        block_on(py, async move { running.profile(every).await }).map(PyRunProfile::from)
    }

    /// Async counterpart of `profile()`.
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
    fn shutdown(&self, py: Python<'_>, grace_seconds: f64) -> PyResult<PyOutcome> {
        let grace = nonnegative_duration(grace_seconds, "grace_seconds")?;
        reject_reentrant_runtime()?;
        match self.claim()? {
            Claimed::Process(running) => {
                block_on(py, async move { running.shutdown(grace).await }).map(PyOutcome::from)
            }
            // The events stream's finisher only starts once the child has been
            // observed to exit, so there is nothing left to signal or escalate:
            // a graceful teardown of an already-exited run *is* its outcome.
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

/// Preserve kill-on-drop for a run whose process this binding moved into the
/// events stream's background finisher (see `EventsDrive`).
///
/// Dropping a `RunningProcess` tears its tree down; that guarantee must not be
/// lost just because the process now lives inside a spawned task. Aborting the
/// task drops the process it owns, which restores exactly that behaviour. It is a
/// no-op in every ordinary case: a task that already completed cannot be
/// cancelled, and a consuming verb that claimed the result left `JointFinish::
/// Taken` behind.
impl Drop for PyRunningProcess {
    fn drop(&mut self) {
        if let JointFinish::Running(task) =
            &*self.finish.lock().unwrap_or_else(PoisonError::into_inner)
        {
            task.abort();
        }
    }
}

/// Register this module's pyclasses (`RunningProcess`, `ProcessStdin`,
/// `StdoutLines`, `OutputEvents`) on `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyRunningProcess>()?;
    m.add_class::<PyProcessStdin>()?;
    m.add_class::<PyStdoutLines>()?;
    m.add_class::<PyOutputEvents>()?;
    Ok(())
}
