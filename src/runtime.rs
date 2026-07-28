//! The single tokio runtime the binding owns and the interruptible blocking
//! driver that powers the synchronous surface.

use std::collections::{HashMap, VecDeque};
use std::future::Future;
use std::io::Write;
use std::pin::Pin;
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::{Arc, Mutex as StdMutex, MutexGuard as StdMutexGuard, PoisonError};
use std::task::{Context, Poll};
use std::time::Duration;

#[cfg(windows)]
use std::net::TcpStream as WakeWriter;
#[cfg(unix)]
use std::os::fd::{FromRawFd, RawFd};
#[cfg(unix)]
use std::os::unix::net::UnixStream as WakeWriter;
#[cfg(windows)]
use std::os::windows::io::{FromRawSocket, RawSocket};

use pyo3::prelude::*;
use pyo3::sync::PyOnceLock;
use pyo3::{intern, IntoPyObjectExt};

use crate::errors::{map_err, ProcessError};

/// The one tokio runtime the binding owns, shared by the sync surface
/// (`block_on`) and the async surface (the socket-wakeup bridge below).
///
/// This is the *raw*, infallible accessor. Every path that actually **drives**
/// the runtime — `block_on`, `drive_async`, or `Runtime::enter` to spawn a
/// stream pump — must first pass [`guard_against_fork`] (directly, or via the
/// checked [`runtime`] accessor) so a runtime copied into a POSIX `fork()` child
/// is refused instead of hung.
pub(crate) fn rt() -> &'static tokio::runtime::Runtime {
    pyo3_async_runtimes::tokio::get_runtime()
}

/// PID of the process that first touched the shared tokio runtime, or `0` before
/// the first touch. Set once on first access and compared on every later one to
/// detect a POSIX `fork()` that copied an already-initialized runtime into a
/// child (see [`guard_against_fork`]). A real `getpid()` is never `0`, so `0` is
/// a safe "not yet claimed" sentinel.
static RUNTIME_OWNER_PID: AtomicU32 = AtomicU32::new(0);

/// Fail fast if the shared tokio runtime would be driven from a process that
/// `fork()`ed *after* the runtime was already initialized in its parent.
///
/// `pyo3-async-runtimes` keeps the tokio runtime in a process-global `OnceLock`.
/// A POSIX `fork()` copies that struct — including the `OnceLock`'s "already
/// initialized" flag — into the child, but **not** the runtime's worker threads:
/// `fork()` carries only the calling thread into the child. So in the child the
/// runtime *looks* ready yet has no workers to drive I/O, and any lock a vanished
/// worker held at fork time (the tokio I/O driver's, the allocator's) stays
/// locked forever. Driving it there — `block_on`, `drive_async`, or even
/// `Runtime::enter` plus spawning a stream pump — hangs or panics with no
/// recovery.
///
/// We cannot rebuild the managed runtime in the child: its `OnceLock` is already
/// set and private to `pyo3-async-runtimes`, so there is no sound "reset". The
/// only safe answer is to refuse quickly and clearly and point the caller at the
/// `spawn` / `forkserver` multiprocessing start methods (see
/// `docs/platforms.md`). Claiming ownership on the first *touch* rather than at
/// import means a process that forks *before* its first processkit call is
/// unaffected — its child simply initializes its own fresh runtime.
fn guard_against_fork() -> PyResult<()> {
    // `std::process::id()` is an uncached `getpid()` on Unix, so it reflects the
    // child's real PID immediately after `fork()` (not the parent's). On Windows,
    // where there is no `fork()`, the PID never changes and this is a no-op.
    let me = std::process::id();
    // Claim ownership on the first touch; otherwise the stored owner must be us.
    // A stored owner that is neither `0` nor `me` is a parent's PID carried in by
    // `fork()` — exactly the hazard we refuse.
    match RUNTIME_OWNER_PID.compare_exchange(0, me, Ordering::AcqRel, Ordering::Acquire) {
        Ok(_) => Ok(()),
        Err(owner) if owner == me => Ok(()),
        Err(_forked) => Err(ProcessError::new_err(
            "processkit's async runtime was initialized in a parent process and \
             cannot be used here: this process was created by POSIX fork() (for \
             example os.fork(), or multiprocessing / ProcessPoolExecutor with the \
             default 'fork' start method on Linux) after processkit had already \
             run. A forked child does not inherit the runtime's worker threads, so \
             driving it now would hang or panic. Use the 'spawn' or 'forkserver' \
             start method (multiprocessing.get_context(\"spawn\")), or perform the \
             fork before the first processkit call.",
        )),
    }
}

/// The shared runtime, guarded against post-`fork()` use. Use this over [`rt`]
/// anywhere the returned handle is driven immediately (`enter` to spawn a stream
/// pump); [`rt`] stays infallible for the hot loop in [`block_on_interruptible`],
/// which runs [`guard_against_fork`] once up front instead of per iteration.
pub(crate) fn runtime() -> PyResult<&'static tokio::runtime::Runtime> {
    guard_against_fork()?;
    Ok(rt())
}

/// Bridge a crate future to a Python awaitable: convert its error to the right
/// Python exception with `map_err`, its success value to the matching Python
/// wrapper, and hand the whole thing to the single lazy, owner-aware bridge
/// (`PyLazyFuture`). The caller maps the success value inside `fut` (e.g.
/// `.map(PyProcessResult::from)`); a scalar result (`String` / `i32` / `bool`)
/// passes through unchanged. This is the async twin of the sync `block_on` and
/// keeps every `a`-prefixed verb a one-liner.
///
/// Unlike a bare `future_into_py`, the returned awaitable does **not** start the
/// work until it is first `await`ed — see [`PyLazyFuture`] for the full
/// lifecycle contract (lazy start, owner-driven teardown, unchanged
/// cancellation).
pub(crate) fn drive_async<F, U>(py: Python<'_>, fut: F) -> PyResult<Bound<'_, PyAny>>
where
    F: Future<Output = Result<U, processkit::Error>> + Send + 'static,
    U: for<'py> IntoPyObject<'py> + Send + 'static,
{
    lazy_bridge(py, async move {
        let value = fut.await.map_err(map_err)?;
        // Defer conversion until the event-loop callback consumes this closure.
        // No runtime thread enters Python merely to hand a completed value over.
        Ok(Box::new(IntoPyConverter(value)) as CompletionConverter)
    })
}

/// Like [`drive_async`], but for a future that already yields a `PyResult`
/// (its own Python exception, e.g. `StopAsyncIteration` from a streaming
/// `__anext__`, or a raw `PyOSError` from a stdin write) rather than a crate
/// error. Routes through the same lazy bridge so every `a`-prefixed awaitable
/// — consuming verb, streaming step, or async context-manager entry — shares
/// one lifecycle contract instead of calling `future_into_py` directly.
pub(crate) fn drive_async_py<F, T>(py: Python<'_>, fut: F) -> PyResult<Bound<'_, PyAny>>
where
    F: Future<Output = PyResult<T>> + Send + 'static,
    T: for<'py> IntoPyObject<'py> + Send + 'static,
{
    lazy_bridge(py, async move {
        let value = fut.await?;
        Ok(Box::new(IntoPyConverter(value)) as CompletionConverter)
    })
}

/// Like [`drive_async_py`], but converts a raw completed value with `convert`
/// on the event-loop thread. Use this when the success value needs Python APIs
/// rather than merely implementing `IntoPyObject`.
pub(crate) fn drive_async_py_convert<F, T, C>(
    py: Python<'_>,
    fut: F,
    convert: C,
) -> PyResult<Bound<'_, PyAny>>
where
    F: Future<Output = PyResult<T>> + Send + 'static,
    T: Send + 'static,
    C: for<'py> FnOnce(Python<'py>, T) -> PyResult<Py<PyAny>> + Send + 'static,
{
    lazy_bridge(py, async move {
        let value = fut.await?;
        Ok(Box::new(WithPyConverter {
            value: Some(value),
            convert: Some(convert),
        }) as CompletionConverter)
    })
}

/// Type-erased conversion of a completed Rust value into its Python wrapper.
/// It is built by the runtime task but invoked only by the event-loop callback,
/// so even the last `IntoPyObject` step stays on the interpreter-owning thread.
trait ConvertCompletion: Send {
    fn convert(self: Box<Self>, py: Python<'_>) -> PyResult<Py<PyAny>>;
}

struct IntoPyConverter<T>(T);

struct WithPyConverter<T, C> {
    value: Option<T>,
    convert: Option<C>,
}

impl<T> ConvertCompletion for IntoPyConverter<T>
where
    T: for<'py> IntoPyObject<'py> + Send + 'static,
{
    fn convert(self: Box<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        self.0.into_py_any(py)
    }
}

impl<T, C> ConvertCompletion for WithPyConverter<T, C>
where
    T: Send + 'static,
    C: for<'py> FnOnce(Python<'py>, T) -> PyResult<Py<PyAny>> + Send + 'static,
{
    fn convert(mut self: Box<Self>, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let value = self.value.take().expect("completion value consumed once");
        let convert = self
            .convert
            .take()
            .expect("completion converter consumed once");
        convert(py, value)
    }
}

type CompletionConverter = Box<dyn ConvertCompletion + 'static>;

/// The inert, type-erased bridged work a [`PyLazyFuture`] holds until its first
/// `await`: it awaits the crate/Python future and produces either its Python
/// error or a converter for the success value. Boxed so every `a`-verb's
/// distinct future and result types collapse to one bridge type.
type BridgedWork = Pin<Box<dyn Future<Output = PyResult<CompletionConverter>> + Send + 'static>>;

/// Wrap inert bridged `work` in a lazy, owner-aware [`PyLazyFuture`]. Nothing is
/// scheduled here: a Rust future does nothing until polled, and `PyLazyFuture`
/// does not hand it to the runtime until it is first awaited.
fn lazy_bridge<F>(py: Python<'_>, work: F) -> PyResult<Bound<'_, PyAny>>
where
    F: Future<Output = PyResult<CompletionConverter>> + Send + 'static,
{
    let lazy = PyLazyFuture {
        state: StdMutex::new(LazyState::Pending(Box::pin(work))),
    };
    Ok(Py::new(py, lazy)?.into_bound(py).into_any())
}

/// Outcome shared between the tokio task and the event-loop wakeup callback.
/// The runtime writes it before waking the socket; the loop takes it exactly
/// once and performs the Python conversion/completion itself.
enum CompletionState {
    Pending,
    Ready(PyResult<CompletionConverter>),
}

struct SharedCompletion {
    state: StdMutex<CompletionState>,
}

impl SharedCompletion {
    fn lock(&self) -> StdMutexGuard<'_, CompletionState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

/// The runtime work plus its Python-future cancellation signal. Polling work
/// first preserves the upstream bridge's rule that a result already ready in
/// the same turn wins over cancellation.
struct CancellableWork {
    work: BridgedWork,
    cancel_rx: tokio::sync::oneshot::Receiver<()>,
    listen_for_cancel: bool,
}

enum WorkExit {
    Completed(PyResult<CompletionConverter>),
    Cancelled,
}

impl Future for CancellableWork {
    type Output = WorkExit;

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        if let Poll::Ready(result) = self.work.as_mut().poll(cx) {
            return Poll::Ready(WorkExit::Completed(result));
        }

        if self.listen_for_cancel {
            match Pin::new(&mut self.cancel_rx).poll(cx) {
                Poll::Ready(Ok(())) => return Poll::Ready(WorkExit::Cancelled),
                // The callback owner disappeared without cancelling. Stop
                // polling the closed receiver and let the real work finish.
                Poll::Ready(Err(_closed)) => self.listen_for_cancel = false,
                Poll::Pending => {}
            }
        }
        Poll::Pending
    }
}

struct HubEntry {
    future: Py<PyAny>,
    completion: Arc<SharedCompletion>,
}

struct HubState {
    entries: HashMap<u64, HubEntry>,
    ready: VecDeque<u64>,
    wake_outstanding: bool,
    closed: bool,
}

/// One completion dispatcher per live asyncio loop. Every operation registers
/// an entry here; runtime workers only enqueue its integer id and write to the
/// one shared socket. This keeps high-volume streams from creating a socketpair
/// for every `__anext__` while retaining a loop-thread-only completion point.
struct CompletionHub {
    next_id: AtomicU64,
    state: StdMutex<HubState>,
    writer: StdMutex<Option<WakeWriter>>,
}

impl CompletionHub {
    fn lock_state(&self) -> StdMutexGuard<'_, HubState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn register(&self, future: Py<PyAny>, completion: Arc<SharedCompletion>) -> Option<u64> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let mut state = self.lock_state();
        if state.closed {
            return None;
        }
        state.entries.insert(id, HubEntry { future, completion });
        Some(id)
    }

    fn cancel(&self, id: u64) {
        self.lock_state().entries.remove(&id);
    }

    fn publish(&self, id: u64) {
        let should_wake = {
            let mut state = self.lock_state();
            if state.closed || !state.entries.contains_key(&id) {
                return;
            }
            state.ready.push_back(id);
            if state.wake_outstanding {
                false
            } else {
                state.wake_outstanding = true;
                true
            }
        };
        if should_wake {
            let mut slot = self.writer.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some(writer) = slot.as_mut() {
                if writer.write_all(&[1]).is_err() {
                    // Dropping the failed endpoint wakes the loop's receive with
                    // EOF/error, where the queued outcomes are still drained.
                    slot.take();
                }
            }
        }
    }

    fn take_ready(&self) -> Vec<HubEntry> {
        let mut state = self.lock_state();
        let ids: Vec<_> = state.ready.drain(..).collect();
        state.wake_outstanding = false;
        ids.into_iter()
            .filter_map(|id| state.entries.remove(&id))
            .collect()
    }

    fn close(&self) -> Vec<HubEntry> {
        let entries = {
            let mut state = self.lock_state();
            state.closed = true;
            state.ready.clear();
            state.wake_outstanding = false;
            state.entries.drain().map(|(_id, entry)| entry).collect()
        };
        self.writer
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .take();
        entries
    }

    fn is_closed(&self) -> bool {
        self.lock_state().closed
    }

    fn has_entries(&self) -> bool {
        !self.lock_state().entries.is_empty()
    }
}

/// Python-owned anchor stored in a weak-key map by event loop. It keeps the
/// shared hub and reader alive without keeping the loop itself alive.
#[pyclass]
struct PyCompletionHub {
    hub: Arc<CompletionHub>,
    _reader: Py<PyAny>,
}

/// Callback for the hub's one outstanding `sock_recv`. It drains every queued
/// completion on the event-loop thread, then rearms the receive for later work.
#[pyclass]
struct PyHubWakeCallback {
    hub: Arc<CompletionHub>,
    event_loop: Py<PyAny>,
    reader: Py<PyAny>,
}

/// Close an idle hub after resumed awaiters have had one event-loop turn to
/// register their next operation. This retains one socket for sequential
/// stream awaits without leaving a pending receive behind when the loop ends.
#[pyclass]
struct PyHubIdleCallback {
    hub: Arc<CompletionHub>,
    event_loop: Py<PyAny>,
    reader: Py<PyAny>,
}

fn complete_entry(py: Python<'_>, entry: HubEntry) -> PyResult<()> {
    let future = entry.future.bind(py);
    if future.call_method0(intern!(py, "done"))?.is_truthy()? {
        return Ok(());
    }
    let result = match std::mem::replace(&mut *entry.completion.lock(), CompletionState::Pending) {
        CompletionState::Ready(result) => result.and_then(|convert| convert.convert(py)),
        CompletionState::Pending => Err(ProcessError::new_err(
            "the async completion wakeup arrived without a result",
        )),
    };
    match result {
        Ok(value) => {
            future.call_method1(intern!(py, "set_result"), (value,))?;
        }
        Err(error) => {
            future.call_method1(
                intern!(py, "set_exception"),
                (error.into_bound_py_any(py)?,),
            )?;
        }
    }
    Ok(())
}

fn arm_hub_receive(
    py: Python<'_>,
    event_loop: &Bound<'_, PyAny>,
    reader: &Bound<'_, PyAny>,
    hub: Arc<CompletionHub>,
) -> PyResult<()> {
    let receive = event_loop.call_method1(intern!(py, "sock_recv"), (reader, 1))?;
    let task = event_loop.call_method1(intern!(py, "create_task"), (receive,))?;
    task.call_method1(
        intern!(py, "add_done_callback"),
        (PyHubWakeCallback {
            hub,
            event_loop: event_loop.clone().unbind(),
            reader: reader.clone().unbind(),
        },),
    )?;
    Ok(())
}

#[pymethods]
impl PyHubWakeCallback {
    fn __call__(&self, wake_task: &Bound<'_, PyAny>) -> PyResult<()> {
        let py = wake_task.py();
        if wake_task
            .call_method0(intern!(py, "cancelled"))?
            .is_truthy()?
        {
            self.reader.bind(py).call_method0(intern!(py, "close"))?;
            for entry in self.hub.close() {
                entry.future.bind(py).call_method0(intern!(py, "cancel"))?;
            }
            return Ok(());
        }

        // Retrieve the receive result so an OS error is marked observed. Ready
        // completions remain valid even if the socket reported EOF/error.
        let receive_ok = wake_task.call_method0(intern!(py, "result")).is_ok();
        for entry in self.hub.take_ready() {
            if let Err(error) = complete_entry(py, entry) {
                error.write_unraisable(py, None);
            }
        }
        if !receive_ok {
            self.reader.bind(py).call_method0(intern!(py, "close"))?;
            for entry in self.hub.close() {
                entry.future.bind(py).call_method0(intern!(py, "cancel"))?;
            }
            return Ok(());
        }
        self.event_loop.bind(py).call_method1(
            intern!(py, "call_soon"),
            (PyHubIdleCallback {
                hub: Arc::clone(&self.hub),
                event_loop: self.event_loop.clone_ref(py),
                reader: self.reader.clone_ref(py),
            },),
        )?;
        Ok(())
    }
}

#[pymethods]
impl PyHubIdleCallback {
    fn __call__(&self, py: Python<'_>) -> PyResult<()> {
        if self.hub.has_entries() {
            return arm_hub_receive(
                py,
                self.event_loop.bind(py),
                self.reader.bind(py),
                Arc::clone(&self.hub),
            );
        }

        self.reader.bind(py).call_method0(intern!(py, "close"))?;
        for entry in self.hub.close() {
            entry.future.bind(py).call_method0(intern!(py, "cancel"))?;
        }
        Ok(())
    }
}

/// Callback attached to each public asyncio Future. Cancellation removes only
/// that operation from the shared hub and drops its Rust work.
#[pyclass]
struct PyCancelCallback {
    cancel_tx: Option<tokio::sync::oneshot::Sender<()>>,
    hub: Arc<CompletionHub>,
    id: u64,
}

#[pymethods]
impl PyCancelCallback {
    fn __call__(&mut self, future: &Bound<'_, PyAny>) -> PyResult<()> {
        let py = future.py();
        if future.call_method0(intern!(py, "cancelled"))?.is_truthy()? {
            self.hub.cancel(self.id);
            if let Some(cancel_tx) = self.cancel_tx.take() {
                let _ = cancel_tx.send(());
            }
        }
        Ok(())
    }
}

#[cfg(unix)]
fn take_wake_writer(writer: &Bound<'_, PyAny>) -> PyResult<WakeWriter> {
    let fd: RawFd = writer
        .call_method0(intern!(writer.py(), "detach"))?
        .extract()?;
    // `socket.detach()` transfers ownership of this live AF_UNIX endpoint out
    // of the Python socket object. From this point the Rust `UnixStream` is its
    // sole owner and closes it on every success/error/cancellation path.
    Ok(unsafe { WakeWriter::from_raw_fd(fd) })
}

#[cfg(windows)]
fn take_wake_writer(writer: &Bound<'_, PyAny>) -> PyResult<WakeWriter> {
    let socket: RawSocket = writer
        .call_method0(intern!(writer.py(), "detach"))?
        .extract()?;
    // On Windows `socket.socketpair()` produces connected TCP sockets.
    // `detach()` transfers this endpoint's SOCKET ownership to Rust, exactly
    // what `TcpStream::from_raw_socket` requires.
    Ok(unsafe { WakeWriter::from_raw_socket(socket) })
}

static COMPLETION_HUBS: PyOnceLock<Py<PyAny>> = PyOnceLock::new();

fn completion_hub_map(py: Python<'_>) -> PyResult<&Bound<'_, PyAny>> {
    let map = COMPLETION_HUBS.get_or_try_init(py, || -> PyResult<Py<PyAny>> {
        Ok(py
            .import("weakref")?
            .getattr("WeakKeyDictionary")?
            .call0()?
            .unbind())
    })?;
    Ok(map.bind(py))
}

fn create_completion_hub(
    py: Python<'_>,
    event_loop: &Bound<'_, PyAny>,
) -> PyResult<Arc<CompletionHub>> {
    let sockets = py.import("socket")?.call_method0("socketpair")?;
    let reader = sockets.get_item(0)?;
    let writer = sockets.get_item(1)?;
    reader.call_method1(intern!(py, "setblocking"), (false,))?;
    let writer = take_wake_writer(&writer)?;
    let hub = Arc::new(CompletionHub {
        next_id: AtomicU64::new(1),
        state: StdMutex::new(HubState {
            entries: HashMap::new(),
            ready: VecDeque::new(),
            wake_outstanding: false,
            closed: false,
        }),
        writer: StdMutex::new(Some(writer)),
    });
    arm_hub_receive(py, event_loop, &reader, Arc::clone(&hub))?;

    let anchor = Py::new(
        py,
        PyCompletionHub {
            hub: Arc::clone(&hub),
            _reader: reader.unbind(),
        },
    )?;
    completion_hub_map(py)?.set_item(event_loop, anchor)?;
    Ok(hub)
}

fn completion_hub(py: Python<'_>, event_loop: &Bound<'_, PyAny>) -> PyResult<Arc<CompletionHub>> {
    let existing = completion_hub_map(py)?.call_method1("get", (event_loop,))?;
    if !existing.is_none() {
        let existing = existing.cast::<PyCompletionHub>()?.borrow();
        if !existing.hub.is_closed() {
            return Ok(Arc::clone(&existing.hub));
        }
    }
    create_completion_hub(py, event_loop)
}

fn panic_message(payload: &dyn std::any::Any) -> &str {
    if let Some(message) = payload.downcast_ref::<&str>() {
        message
    } else if let Some(message) = payload.downcast_ref::<String>() {
        message.as_str()
    } else {
        "unknown error"
    }
}

/// Start `work` and return the real asyncio Future that represents it. The
/// loop's shared completion hub is the cross-thread handoff: tokio stores the
/// outcome, enqueues this operation's id, and wakes the hub's `sock_recv`.
fn start_bridge(py: Python<'_>, work: BridgedWork) -> PyResult<Py<PyAny>> {
    let locals = pyo3_async_runtimes::tokio::get_current_locals(py)?;
    let event_loop = locals.event_loop(py);
    let future = event_loop.call_method0(intern!(py, "create_future"))?;
    let hub = completion_hub(py, &event_loop)?;
    let completion = Arc::new(SharedCompletion {
        state: StdMutex::new(CompletionState::Pending),
    });
    let id = hub
        .register(future.clone().unbind(), Arc::clone(&completion))
        .ok_or_else(|| ProcessError::new_err("the asyncio completion hub is closed"))?;

    let (cancel_tx, cancel_rx) = tokio::sync::oneshot::channel();
    if let Err(error) = future.call_method1(
        intern!(py, "add_done_callback"),
        (PyCancelCallback {
            cancel_tx: Some(cancel_tx),
            hub: Arc::clone(&hub),
            id,
        },),
    ) {
        hub.cancel(id);
        return Err(error);
    }

    let worker = rt().spawn(pyo3_async_runtimes::tokio::scope(
        locals,
        CancellableWork {
            work,
            cancel_rx,
            listen_for_cancel: true,
        },
    ));
    rt().spawn(async move {
        let result = match worker.await {
            Ok(WorkExit::Completed(result)) => result,
            Ok(WorkExit::Cancelled) => return,
            Err(join_error) if join_error.is_panic() => {
                let payload = join_error.into_panic();
                Err(pyo3_async_runtimes::err::RustPanic::new_err(format!(
                    "rust future panicked: {}",
                    panic_message(payload.as_ref())
                )))
            }
            // Tokio tasks are never aborted by this bridge, so cancellation of
            // the JoinHandle itself is unreachable. Still surface it rather
            // than leaving the Python Future pending forever.
            Err(join_error) => Err(ProcessError::new_err(format!(
                "the async runtime task ended before producing a result: {join_error}"
            ))),
        };
        *completion.lock() = CompletionState::Ready(result);
        // The mutex unlock publishes the result before its id is enqueued and
        // the shared socket is woken.
        hub.publish(id);
    });

    Ok(future.unbind())
}

/// The single async bridge every `a`-prefixed verb returns: a lazily-scheduled,
/// owner-aware awaitable with an explicit lifecycle contract.
///
/// # Why not raw `future_into_py`
///
/// `pyo3_async_runtimes::tokio::future_into_py` *eagerly* spawns its future on
/// the shared runtime the instant it is called and keeps a strong reference to
/// the backing `asyncio.Future`, so the work runs to completion even if the
/// awaitable is never awaited, its last Python owner is dropped, or the event
/// loop closes underneath it. For a plain `Command.aoutput()` that leaks a
/// child; for `Supervisor(restart="always").arun()` it is an immortal restart
/// loop that pins every captured Python callback (`stop_when`/`give_up_when`)
/// until the interpreter exits.
///
/// Its completion path also attaches to Python on a detached blocking thread,
/// calls `loop.call_soon_threadsafe`, and can still be inside the interpreter
/// after the awaiting coroutine resumes. If that was the program's last act,
/// `Py_FinalizeEx` could begin underneath the bridge thread. This bridge instead
/// wakes `loop.sock_recv` through an OS socket and completes the Python Future
/// on the loop thread, so there is no foreign interpreter attach to race.
///
/// # Contract
///
/// * **Ownership.** While `Pending`, this owns the inert work future and
///   everything it captured — including a process handle a consuming verb took
///   eagerly out of `self` (`RunningProcess.aoutput()` & co.). On the first
///   `await`, ownership of the work transfers to the runtime.
/// * **Lazy start.** A Rust future is inert until polled, and this does not
///   hand the work to the runtime until `__await__`. So an `a`-verb called
///   **without `await`** starts nothing at all.
/// * **Owner-driven teardown.** Dropping a `Pending` awaitable — an `a`-verb
///   called without `await`, or its last owner lost before the first `await` —
///   drops the inert future, releasing every Python object it captured and, for
///   a future that already owns a started process/tree, tearing that tree down
///   via kill-on-drop. Nothing was ever scheduled, so no detached task survives
///   to touch Python during finalization.
/// * **Loop-thread completion.** The runtime stores a type-erased outcome and
///   wakes one shared socket per event loop. `loop.sock_recv` runs on the loop
///   thread, converts the value, and resolves the backing Future there.
/// * **Cancellation is unchanged.** Once awaited, cancellation of the backing
///   `asyncio.Future` signals the runtime work to drop, so `Future.cancel()`
///   still raises `CancelledError` and tears the process tree down exactly as
///   before.
#[pyclass(module = "processkit")]
pub(crate) struct PyLazyFuture {
    state: StdMutex<LazyState>,
}

enum LazyState {
    /// Built but not yet scheduled — nothing runs until `__await__`.
    Pending(BridgedWork),
    /// Scheduled: the backing `asyncio.Future` the socket bridge returned,
    /// whose await/cancel machinery every later `__await__` delegates to.
    Started(Py<PyAny>),
    /// The work was taken to be scheduled but bridge setup failed (no
    /// running loop); the future — and any process it owned — was already
    /// dropped, so there is nothing left to await.
    Spent,
}

impl PyLazyFuture {
    /// Lock the state, recovering from a (never-expected) poisoned mutex rather
    /// than panicking across the FFI boundary — the guarded sections never
    /// panic, so poisoning cannot actually happen.
    fn lock(&self) -> StdMutexGuard<'_, LazyState> {
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[pymethods]
impl PyLazyFuture {
    /// Schedule the work on the first `await` (the one place it is actually
    /// spawned) and delegate to the backing `asyncio.Future`'s own await/cancel
    /// machinery. Idempotent on re-await: later calls delegate to the same
    /// backing future, mirroring `asyncio.Future` semantics.
    fn __await__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        // Refuse before touching state so a fork child fails cleanly and
        // idempotently on every await, without spending the inert work (which
        // the bridge below would otherwise schedule onto a runtime whose
        // worker threads did not survive the fork).
        guard_against_fork()?;
        let mut state = self.lock();
        if let LazyState::Started(inner) = &*state {
            return inner.bind(py).call_method0(intern!(py, "__await__"));
        }
        let work = match std::mem::replace(&mut *state, LazyState::Spent) {
            LazyState::Pending(work) => work,
            // `Started` is handled above; `Spent` means a prior `__await__` took
            // the work and bridge setup failed, dropping it (and any process
            // it owned) already.
            LazyState::Started(_) | LazyState::Spent => {
                return Err(ProcessError::new_err(
                    "this async operation has already been consumed",
                ));
            }
        };
        // Hand the inert work to the socket-wakeup bridge. On success, remember
        // the backing future so a re-await delegates to it; on failure the work
        // (and any process it owns) has already been dropped and the state stays
        // `Spent`.
        let inner = start_bridge(py, work)?;
        let await_iter = inner.bind(py).call_method0(intern!(py, "__await__"))?;
        *state = LazyState::Started(inner);
        Ok(await_iter)
    }

    fn __repr__(&self) -> &'static str {
        match &*self.lock() {
            LazyState::Pending(_) => "<processkit awaitable (pending)>",
            LazyState::Started(_) => "<processkit awaitable (started)>",
            LazyState::Spent => "<processkit awaitable (spent)>",
        }
    }
}

/// Drive a crate future to completion on the sync surface and convert a crate
/// error to the right Python exception with `map_err` — the sync twin of
/// `drive_async`. The caller maps the success value to its Python wrapper on the
/// returned `PyResult` (e.g. `.map(PyProcessResult::from)`); a scalar result
/// (`String` / `i32` / `bool` / `()`) is returned as-is. This is the interruptible
/// `block_on_interruptible(...)?.map_err(map_err)` dance in one place, so every
/// sync verb is a one-liner and `map_err` lives in a single spot.
pub(crate) fn block_on<F, U>(py: Python<'_>, fut: F) -> PyResult<U>
where
    F: std::future::Future<Output = Result<U, processkit::Error>> + Send,
    U: Send,
{
    block_on_interruptible(py, fut)?.map_err(map_err)
}

/// How often a blocked sync call surfaces to check for pending Python signals.
const SIGNAL_POLL_INTERVAL: Duration = Duration::from_millis(100);

/// Drive a future to completion with the GIL released, re-acquiring it on a
/// fixed tick to honour pending signals (notably `Ctrl+C`). A fast future
/// returns on the first tick with no added latency; a slow one yields every
/// `SIGNAL_POLL_INTERVAL` so `Python::check_signals` can raise. When it raises,
/// `fut` is dropped here — which, for a run that owns its process group, tears
/// the tree down.
pub(crate) fn block_on_interruptible<F, T>(py: Python<'_>, fut: F) -> PyResult<T>
where
    F: std::future::Future<Output = T> + Send,
    T: Send,
{
    // Refuse a runtime copied into a POSIX `fork()` child before touching it —
    // otherwise `rt().block_on` below drives a runtime with no surviving worker
    // threads and hangs/panics for good. Checked once here, not per loop tick.
    guard_against_fork()?;
    // `rt().block_on` is NOT re-entrant: driving it from a thread that is already
    // inside the runtime panics ("Cannot start a runtime from within a runtime").
    // That happens if a Rust->Python callback running inside the runtime — e.g. a
    // `Supervisor` `stop_when` predicate — calls a synchronous verb. Detect it and
    // raise a clear error instead of letting tokio panic (PyO3 would otherwise turn
    // the panic into a `PanicException`, which the predicate wrapper swallows,
    // producing a silent, confusing failure). This is a no-op on the normal sync
    // path, where the calling thread holds no runtime context.
    reject_reentrant_runtime()?;
    let mut fut = std::pin::pin!(fut);
    loop {
        let step = py.detach(|| {
            rt().block_on(async { tokio::time::timeout(SIGNAL_POLL_INTERVAL, fut.as_mut()).await })
        });
        match step {
            Ok(value) => return Ok(value),
            // The tick elapsed without completion — let Python run its signal
            // handlers, then keep waiting.
            Err(_elapsed) => py.check_signals()?,
        }
    }
}

/// Whether an asyncio event loop is currently running on this thread — the
/// precondition the async surface needs. Check this *before* a consuming verb
/// takes its handle out of `self` so calling an `a`-prefixed verb from sync
/// code (no loop) raises here, cleanly, *before* the handle is consumed —
/// leaving it in place for the caller to reach for the correct sync twin. The
/// lazy bridge (`drive_async`) would otherwise happily wrap the taken handle in
/// a never-awaitable future whose only fate is kill-on-drop, silently spending
/// a live handle the caller could still have used.
pub(crate) fn require_event_loop(py: Python<'_>) -> PyResult<()> {
    pyo3_async_runtimes::tokio::get_current_loop(py)
        .map(|_| ())
        .map_err(|_| {
            ProcessError::new_err(
                "no running asyncio event loop; call this async (a-prefixed) verb \
                 with `await` from inside a coroutine, not from sync code",
            )
        })
}

/// Whether the calling thread is already inside the shared tokio runtime — the
/// same condition `block_on_interruptible` rejects above. Check this *before* a
/// sync consuming verb takes its handle out of `self`, for the same reason
/// `require_event_loop` is checked before `drive_async`.
pub(crate) fn reject_reentrant_runtime() -> PyResult<()> {
    if tokio::runtime::Handle::try_current().is_ok() {
        return Err(ProcessError::new_err(
            "cannot call a synchronous processkit verb from inside an async context \
             or a callback that runs on the runtime (e.g. a Supervisor stop_when \
             predicate); use the async (a-prefixed) API, or compute the value before \
             the callback",
        ));
    }
    Ok(())
}
