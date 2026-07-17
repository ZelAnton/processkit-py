//! A typed CLI wrapper: a program plus default timeout/env, with run verbs that
//! take just the per-call arguments. Convenient for wrapping a tool (git, docker)
//! you call repeatedly with the same defaults.

use std::cell::RefCell;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use processkit::CliClient as PkCliClient;
use processkit::Command as PkCommand;
use processkit::IntoCommand;
use processkit::JobRunner;
use processkit::ProcessRunner;
use pyo3::prelude::*;

use crate::cancellation::PyCancellationToken;
use crate::command::PyCommand;
use crate::convert::{build_retry_policy, parse_retry_if, positive_duration};
use crate::errors::map_err;
use crate::result::{PyBytesResult, PyProcessResult};
use crate::runner::{extract_runner, scope_when_capture, with_when_capture_sync};
use crate::runtime::drive_async_py;

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

thread_local! {
    /// Per-thread hand-off for a `default_env_fn` resolver failure. The crate's
    /// resolver is infallible (`Fn() -> String`, no `Result`), so a raising or
    /// non-`str`-returning callback can't signal failure through its return type —
    /// instead it parks its `PyErr` here, and [`build_command`] (which runs every
    /// resolver synchronously on this same thread while applying the client's
    /// defaults) picks it up and raises it, aborting the call before the runner is
    /// ever reached. Thread-local, not a shared cell on the client: the resolvers
    /// for one build all run on one thread, so the capture-then-read hand-off can
    /// never interleave with a concurrent build on *another* thread.
    ///
    /// The slot is *not* owned by a single build, though: a resolver may itself
    /// make a nested processkit call on the same thread (the classic "read a
    /// secret via a child `CliClient.run()`" pattern), and that nested
    /// `build_command` re-enters this slot while the outer build's error is still
    /// parked. To stay correct under that reentrancy, [`build_command`] brackets
    /// its build with [`ResolverErrorScope`], which saves and clears the slot on
    /// entry and restores it on exit — so a nested build gets a fresh slot for its
    /// own resolvers and never observes, consumes, or clobbers the outer build's
    /// parked error (which would silently revert the outer call to fail-open).
    /// Empty between top-level builds.
    static RESOLVER_ERROR: RefCell<Option<PyErr>> = const { RefCell::new(None) };
}

/// RAII bracket that makes the [`RESOLVER_ERROR`] hand-off reentrancy-safe. A
/// `default_env_fn` resolver can trigger a *nested* [`build_command`] on the same
/// thread (e.g. it fetches a secret via a child `CliClient.run()`); without a
/// bracket, that nested build's entry-clear would wipe an outer build's already-
/// parked error, so the outer `build_command` would read an empty slot and
/// silently revert to the fail-open (blank-credential) behaviour this whole
/// mechanism exists to prevent. On construction the guard *takes* (saves and
/// clears) whatever the slot holds — an outer build's parked error if this build
/// is nested, or `None` at the top level — giving this build a fresh, empty slot;
/// on drop it puts that saved value back, so an outer build still finds its error
/// waiting. Restoring in `Drop` also keeps the slot consistent if the build
/// unwinds.
struct ResolverErrorScope {
    /// The slot's contents from before this build, restored on drop. Held in an
    /// `Option` only so `Drop` (which gets `&mut self`) can move the `PyErr` back
    /// out on restore.
    outer: Option<PyErr>,
}

impl ResolverErrorScope {
    /// Enter a build: save and clear the slot, leaving it empty for this build's
    /// own resolvers to park into.
    fn enter() -> Self {
        Self {
            outer: RESOLVER_ERROR.with(|slot| slot.borrow_mut().take()),
        }
    }

    /// Take this build's own parked resolver error, if any. Leaves the slot empty
    /// so the `Drop` restore puts the *outer* build's saved error back.
    fn take_error(&self) -> Option<PyErr> {
        RESOLVER_ERROR.with(|slot| slot.borrow_mut().take())
    }
}

impl Drop for ResolverErrorScope {
    fn drop(&mut self) {
        // Restore the outer build's parked error (or `None` at the top level),
        // undoing the `take` in `enter` — so a nested build leaves the outer
        // build's slot exactly as it found it.
        RESOLVER_ERROR.with(|slot| {
            *slot.borrow_mut() = self.outer.take();
        });
    }
}

/// Wrap a Python zero-arg callable as a `CliClient.default_env_fn` resolver.
/// The crate's resolver is infallible (`Fn() -> V`, no `Result`), so a raising
/// or non-`str`-returning callback can't signal failure through its return type.
/// Rather than fail **open** — the old behaviour: report via the unraisable hook
/// and resolve to an empty string, which for a token/password/dynamic-config
/// resolver would spawn the command with a blank credential instead of refusing
/// — the failure is parked in [`RESOLVER_ERROR`] for [`build_command`] to raise,
/// aborting the call before the runner (and any real spawn) is reached (fail
/// **closed**). The sole surviving fallback is a *finalizing* interpreter
/// (`try_attach` yields `None`): at shutdown there is no live interpreter to
/// raise into, so the empty string stays there — the same finalization guard as
/// `logging.rs`'s bridge.
fn make_env_resolver(callback: Py<PyAny>) -> impl Fn() -> String + Send + Sync + 'static {
    move || {
        // `try_attach`, not `attach`: the crate materializes a command's env on
        // its run path, which can execute on a tokio worker not joined at
        // `Py_Finalize` (the runtime is an immortal singleton). A finalizing
        // interpreter yields `None` -> fall back to an empty string, instead of
        // the panic/crash a plain `attach` would cause at shutdown. Same
        // finalization guard as `logging.rs`'s bridge.
        Python::try_attach(|py| {
            match callback
                .call0(py)
                .and_then(|value| value.extract::<String>(py))
            {
                Ok(resolved) => resolved,
                Err(err) => {
                    // Park the real exception for `build_command` to raise. Keep
                    // the FIRST failure if several resolvers fail in one build:
                    // the crate keeps invoking the remaining resolvers (each still
                    // returns the empty string below), but the earliest-registered
                    // failure is the deterministic one to surface. The returned
                    // empty string is inert — `build_command` aborts before the
                    // command is ever run, so this value is never observed.
                    RESOLVER_ERROR.with(|slot| {
                        let mut slot = slot.borrow_mut();
                        if slot.is_none() {
                            *slot = Some(err);
                        }
                    });
                    String::new()
                }
            }
        })
        .unwrap_or_default()
    }
}

/// Apply the client's defaults to `call` — running each `default_env_fn`
/// resolver exactly as the crate would (fresh per build, gap-filled so a
/// per-command `env()` or a static `default_env` for the same key still wins and
/// a resolver whose key is already set never runs) — then surface any resolver
/// failure captured in [`RESOLVER_ERROR`] as the raised `PyErr`. On success the
/// fully-defaulted `Command` is returned for the caller to run; on failure the
/// error propagates and the caller never touches the runner, so no process is
/// spawned. The build is synchronous (no `await` between the resolvers and the
/// read), so the whole capture-then-read hand-off stays on one thread — the
/// caller's for the sync verbs and `command()`, the polling worker for the async
/// verbs — and never interleaves with another build on a *different* thread.
///
/// A resolver can, however, re-enter `build_command` on the *same* thread (it
/// makes a nested processkit call — e.g. reads a secret via a child
/// `CliClient.run()`). [`ResolverErrorScope`] brackets the build so that nested
/// build gets its own fresh slot and neither consumes nor clobbers this build's
/// parked error; without it, the nested build would clear an outer parked error
/// and the outer call would silently revert to fail-open.
fn build_command(
    client: &PkCliClient<Arc<dyn ProcessRunner + Send + Sync>>,
    call: ClientCall,
) -> PyResult<PkCommand> {
    // Save + clear the slot for the duration of this build (restored on drop), so
    // the capture-then-read hand-off is reentrancy-safe: a nested build triggered
    // by a resolver on this thread cannot see or wipe an outer build's parked
    // error. The build itself invokes the resolvers.
    let scope = ResolverErrorScope::enter();
    let command = match call {
        ClientCall::Args(args) => client.command(args),
        ClientCall::Cmd(cmd) => (*cmd).into_command(client),
    };
    match scope.take_error() {
        Some(err) => Err(err),
        None => Ok(command),
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
        // construction): a non-callable is a construction-time mistake, so it
        // belongs at construction time — a clear `TypeError` naming the key,
        // rather than a failure deferred to the first command build. (A genuine
        // *callable* that fails at resolve time — raises, or returns a non-`str`
        // — is a distinct, per-build runtime failure; `make_env_resolver` /
        // `build_command` now propagate THAT as the raised exception too, fail-
        // closed, aborting before any spawn, instead of the old empty-string
        // fallback.)
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
    ///
    /// Applying the defaults resolves every `default_env_fn`; a resolver that
    /// raises or returns a non-`str` aborts `command()` with that exception,
    /// same as the run verbs (fail-closed — a broken credential resolver never
    /// yields a silently-empty env var).
    fn command(&self, args: Vec<PathBuf>) -> PyResult<PyCommand> {
        Ok(PyCommand {
            inner: build_command(&self.inner, ClientCall::Args(args))?,
        })
    }

    /// Run with the given args, or a `Command` from `command()`; require a
    /// zero exit and return trimmed stdout.
    ///
    /// Runs through the same `when`-capture scope as `Runner`'s own verbs (see
    /// `runner.rs`), so an injected `ScriptedRunner` whose `when` predicate raises
    /// aborts the call with that error instead of silently falling through to a
    /// fallback reply. (`build_command` runs the client's `default_env_fn`
    /// resolvers, not `when` predicates, so it stays outside the scope.)
    fn run(&self, py: Python<'_>, call: &Bound<'_, PyAny>) -> PyResult<String> {
        let command = build_command(&self.inner, ClientCall::from_py(call)?)?;
        with_when_capture_sync(py, self.inner.run(command))
    }

    /// Run with the given args, or a `Command` from `command()`, and capture
    /// output (a non-zero exit is data).
    fn output(&self, py: Python<'_>, call: &Bound<'_, PyAny>) -> PyResult<PyProcessResult> {
        let command = build_command(&self.inner, ClientCall::from_py(call)?)?;
        with_when_capture_sync(py, self.inner.output_string(command)).map(PyProcessResult::from)
    }

    /// Run with the given args, or a `Command` from `command()`, and capture
    /// raw-bytes stdout.
    fn output_bytes(&self, py: Python<'_>, call: &Bound<'_, PyAny>) -> PyResult<PyBytesResult> {
        let command = build_command(&self.inner, ClientCall::from_py(call)?)?;
        with_when_capture_sync(py, self.inner.output_bytes(command)).map(PyBytesResult::from)
    }

    /// Run with the given args, or a `Command` from `command()`, and return
    /// the exit code.
    fn exit_code(&self, py: Python<'_>, call: &Bound<'_, PyAny>) -> PyResult<i32> {
        let command = build_command(&self.inner, ClientCall::from_py(call)?)?;
        with_when_capture_sync(py, self.inner.exit_code(command))
    }

    /// Run a predicate call (args, or a `Command` from `command()`) and read
    /// its exit code as a bool.
    fn probe(&self, py: Python<'_>, call: &Bound<'_, PyAny>) -> PyResult<bool> {
        let command = build_command(&self.inner, ClientCall::from_py(call)?)?;
        with_when_capture_sync(py, self.inner.probe(command))
    }

    /// Resolve this client's `program` to a concrete executable path **without
    /// spawning it** — the client-level preflight ("is this tool installed?"),
    /// with no side effects (no process is started).
    ///
    /// Builds a command for the client's program with the client's defaults
    /// applied — so a `default_env` (or a `default_env_fn`) that relocates
    /// `PATH` is honored exactly as it would be at launch — then resolves it via
    /// `Command.resolve_program()`, reusing the **same** internal
    /// PATH/PATHEXT/execute-bit logic the real spawn uses. The preflight
    /// therefore never disagrees with what an actual run of this client would
    /// find, and returns the resolved **absolute** path as a `str`.
    ///
    /// Applying the defaults resolves every `default_env_fn` (fresh, like the run
    /// verbs and `command()`); a resolver that raises or returns a non-`str`
    /// aborts `resolve_program()` with that exception (fail-closed), before any
    /// filesystem lookup. Synchronous and cheap (a few `stat`s); no tokio runtime
    /// is required. On a miss raises `ProcessNotFound` (also a
    /// `FileNotFoundError`) — see `Command.resolve_program` for the full contract
    /// (`searched` diagnostic). There is deliberately no `a`-prefixed async twin.
    fn resolve_program(&self) -> PyResult<String> {
        // Go through `build_command` (not the crate's `CliClient::resolve_program`
        // directly) so a failing `default_env_fn` resolver is surfaced fail-closed
        // via `RESOLVER_ERROR`, exactly like the run verbs — the crate's own
        // resolver seam is infallible and would otherwise swallow the failure.
        let command = build_command(&self.inner, ClientCall::Args(Vec::new()))?;
        command
            .resolve_program()
            .map(|path| path.to_string_lossy().into_owned())
            .map_err(map_err)
    }

    /// Async counterpart of `run()`.
    ///
    /// The `default_env_fn` resolvers run when the returned awaitable is first
    /// awaited (fresh per build, like the sync verbs); a resolver that raises or
    /// returns a non-`str` propagates that exception out of the `await`, before
    /// the runner is reached, so no process is spawned (fail-closed). An injected
    /// `ScriptedRunner`'s raising `when` predicate likewise aborts the awaited
    /// call (via `scope_when_capture`), matching the sync verbs.
    fn arun<'py>(&self, py: Python<'py>, call: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        let call = ClientCall::from_py(call)?;
        drive_async_py(
            py,
            scope_when_capture(async move {
                let command = build_command(&client, call)?;
                client.run(command).await.map_err(map_err)
            }),
        )
    }

    /// Async counterpart of `output()`.
    fn aoutput<'py>(
        &self,
        py: Python<'py>,
        call: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        let call = ClientCall::from_py(call)?;
        drive_async_py(
            py,
            scope_when_capture(async move {
                let command = build_command(&client, call)?;
                client
                    .output_string(command)
                    .await
                    .map(PyProcessResult::from)
                    .map_err(map_err)
            }),
        )
    }

    /// Async counterpart of `output_bytes()`.
    fn aoutput_bytes<'py>(
        &self,
        py: Python<'py>,
        call: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        let call = ClientCall::from_py(call)?;
        drive_async_py(
            py,
            scope_when_capture(async move {
                let command = build_command(&client, call)?;
                client
                    .output_bytes(command)
                    .await
                    .map(PyBytesResult::from)
                    .map_err(map_err)
            }),
        )
    }

    /// Async counterpart of `exit_code()`.
    fn aexit_code<'py>(
        &self,
        py: Python<'py>,
        call: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        let call = ClientCall::from_py(call)?;
        drive_async_py(
            py,
            scope_when_capture(async move {
                let command = build_command(&client, call)?;
                client.exit_code(command).await.map_err(map_err)
            }),
        )
    }

    /// Async counterpart of `probe()`.
    fn aprobe<'py>(
        &self,
        py: Python<'py>,
        call: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let client = self.inner.clone();
        let call = ClientCall::from_py(call)?;
        drive_async_py(
            py,
            scope_when_capture(async move {
                let command = build_command(&client, call)?;
                client.probe(command).await.map_err(map_err)
            }),
        )
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
