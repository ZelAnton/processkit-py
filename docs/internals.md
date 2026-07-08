# Architecture

This page is for contributors: how the binding is put together, where the line
between "binding" and "crate" runs, and the conventions that keep the two
layers — and the three parallel views of the public API — in sync. The user-
facing guides (linked from the [docs home](README.md)) explain *what* the
library does; this page explains *how the code that implements it is
organized*.

## Two layers, one boundary

**processkit-py is a thin PyO3 binding to the [`processkit`](https://crates.io/crates/processkit)
Rust crate — not a reimplementation.** Concretely:

```text
┌───────────────────────────────────────────────────────────────────┐
│  Python package (src/processkit/)                                 │
│  __init__.py facade · _aio.py · _protocols.py · _types.py         │
├───────────────────────────────────────────────────────────────────┤
│  Binding crate (src/*.rs) — cdylib `_processkit`                  │
│  pyclasses/verbs, error mapping, runtime driving — thin glue only │
├───────────────────────────────────────────────────────────────────┤
│  `processkit` crate (crates.io, pinned exact version)             │
│  ALL platform logic: Windows Job Objects, Linux cgroup v2,        │
│  POSIX process groups, race-free spawn, async-throughout (tokio)  │
└───────────────────────────────────────────────────────────────────┘
```

Everything that decides *how a process tree is actually contained and torn
down on a given OS* — Job Object completion ports on Windows, cgroup v2 on
Linux, process-group fallbacks, the race-free spawn sequencing — lives in the
`processkit` crate (see its own docs at [docs.rs/processkit](https://docs.rs/processkit)).
The binding crate (`src/*.rs`, compiled to the cdylib `_processkit`) never
reimplements any of that; it exists solely to:

- expose the crate's types as PyO3 pyclasses with a Python-shaped verb surface
  (kwargs, `str`/`os.PathLike`, sync **and** async pairs),
- drive the crate's `async`-throughout futures to completion from Python's
  sync and async worlds (the `runtime.rs` trio, below),
- map the crate's single `processkit::Error` onto a typed Python exception
  hierarchy (`errors.rs`'s `map_err`, below),
- and re-export a small amount of pure-Python convenience on top (`src/processkit/`,
  further below) that composes on the compiled surface instead of touching the
  OS itself.

If you find yourself teaching the binding crate a new fact about an OS
mechanism, that fact almost certainly belongs upstream in `processkit`
instead — bump the pinned crate version and bind the new capability, don't
duplicate it here.

## The Rust module map

`src/lib.rs` is the `#[pymodule(gil_used = false)]` entry point. It declares no
logic of its own beyond calling each module's `register(m)` — registration is
delegated so that adding a new pyclass or function touches only its own
module, not this central list:

```rust
mod batch;       mod cancellation; mod cli;      mod command;
mod convert;     mod errors;       mod group;    mod logging;
mod result;      mod runner;       mod running;  mod runtime;
mod supervisor;
```

| Module | Owns |
|---|---|
| `command.rs` | The `Command` builder and shell-free `Pipeline`. |
| `runner.rs` | The runner seam: `Runner`, the `ScriptedRunner`/`RecordReplayRunner`/`RecordingRunner`/`DryRunRunner` test doubles, the `Reply` builder, and the `runner_pymethods!` macro (below). |
| `running.rs` | The async streaming/interactive handles: `RunningProcess`, `ProcessStdin`, `StdoutLines`, `OutputEvents`. |
| `group.rs` | The `ProcessGroup` containment container and its `ProcessGroupStats`. |
| `supervisor.rs` | The `Supervisor` (restart/backoff) and its `SupervisionOutcome`. |
| `cli.rs` | `CliClient` — a program plus default timeout/env/retry, with verbs that take just per-call args. |
| `batch.rs` | Module-level batch execution: many `Command`s with bounded concurrency. |
| `result.rs` | The captured-result value types: `ProcessResult`, `BytesResult`, `Outcome`, `OutputEvent`, `Finished`, `RunProfile`. |
| `cancellation.rs` | `CancellationToken`, a portable cancel switch shared by `Command`/`CliClient`/`Pipeline`. |
| `logging.rs` | Opt-in bridge forwarding the crate's `tracing` events to Python's `logging`. |
| `convert.rs` | Small converters from Python-facing strings/numbers to crate types (durations, encodings, retry policy). |
| `errors.rs` | The exception hierarchy and `map_err` — the single crate-error → Python-exception funnel (below). |
| `runtime.rs` | The single tokio runtime and the interruptible blocking driver (`block_on` / `drive_async` / `block_on_interruptible`, below). |

This table is a map, not a promise: consult each module's own doc comment for
the authoritative, current description.

`gil_used = false` opts the module into PEP 703 free-threaded CPython (on a
free-threaded build, importing it does not force the GIL back on). This is
sound only because the binding holds no unsynchronized shared state — see
`lib.rs`'s own comment for the itemized reasons (the tokio runtime is a
managed singleton, exception caches use `PyOnceLock`, stream handles are
`Arc<Mutex<…>>`, the stateful pyclasses that carry consumable/reconfigurable
state — `ProcessGroup`, `RunningProcess`, `ScriptedRunner`, `DryRunRunner` —
are `#[pyclass(frozen)]` with an interior `std::sync::Mutex` that serializes
cross-thread access, and the remaining immutable pyclasses lean on PyO3's own
per-object borrow checking). Keep that invariant in mind before adding any new
shared mutable state to a pyclass.

## The call flow: Python → crate → typed exception

Every consuming verb (`output`, `run`, `exit_code`, `probe`, `start`, and their
`a`-prefixed async twins) funnels through the same shape:

```text
Python call
  │
  ▼
PyO3 pyclass method (#[pymethods], e.g. PyCommand::output / Runner::aoutput)
  │
  ▼
crate future (processkit::Command::output_string(&cmd), etc. — async-throughout)
  │
  ▼
runtime.rs: block_on(...) [sync verbs]  or  drive_async(...) [async verbs]
  │                                            │
  │  block_on_interruptible: GIL released,      │  future_into_py bridges the
  │  polls the future on a fixed tick so a       │  future onto the caller's
  │  blocked Ctrl+C still raises on the main      │  running asyncio loop
  │  thread; a reentrant call from inside the     │
  │  runtime (e.g. a Supervisor stop_when         │
  │  callback) is rejected with a clear error      │
  │  instead of panicking tokio                    │
  ▼                                            ▼
Result<T, processkit::Error>
  │
  ▼
errors.rs: map_err(error) -> PyErr   (the ONLY place a crate Error becomes a PyErr)
  │
  ▼
Typed Python exception (ProcessError subclass, or a dual-base one like
Timeout/ProcessNotFound/PermissionDenied that also inherits a builtin)
```

Two invariants worth internalizing when adding a new verb:

- **`runtime.rs` is the only place a future is driven** (`block_on`,
  `drive_async`, and the lower-level `block_on_interruptible` that both build
  on). A new verb should call one of these three, never hand-roll its own
  `rt().block_on(...)` — that's how the reentrancy guard and the Ctrl+C
  polling stay uniform across the whole surface.
- **`map_err` is the only funnel from `processkit::Error` to `PyErr`.** It
  picks the exception class from the error's own accessors
  (`is_timeout()`/`is_not_found()`/`is_permission_denied()`, falling back to a
  match on the enum variant for the rest) and attaches the structured fields
  (`code`, `stdout`, `stderr`, `program`, `signal`, `timeout_seconds`,
  `diagnostic`, output-cap counters) via `setattr`. A new crate error variant
  is covered automatically as long as it exposes the right accessor; no other
  module should construct a `ProcessError` subclass by hand from a crate error.

## Conventions

- **Per-module `register(m)`.** Every `src/*.rs` module exposes
  `pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()>` that adds
  its own classes/functions (and, for `errors.rs`, the whole exception
  hierarchy). `lib.rs` only calls each `register`; it never lists an
  individual class or function itself. Adding a pyclass or function means
  adding it to its module's `register`, nothing in `lib.rs`.
- **`runner_pymethods!` (`runner.rs`).** PyO3's `multiple-pymethods` feature is
  off, so a pyclass may have only one `#[pymethods]` impl. Five runner
  pyclasses (`Runner`, `ScriptedRunner`, `RecordReplayRunner`,
  `RecordingRunner`, `DryRunRunner`) each need the identical twelve-verb
  surface (`output`/`output_bytes`/`run`/`exit_code`/`probe`/`start`, times
  their `a`-prefixed async twins) forwarding to the generic `runner_*` helper
  functions over `ProcessRunner`. The macro splices that shared block together
  with each type's own unique members (constructor, builders, `__repr__`)
  passed in as a token tree, so the run-verb surface has a single source of
  truth instead of five hand-copied blocks that could drift.
- **Config struct → kwargs, not a mirror pyclass.** When the crate exposes a
  builder/options struct (e.g. `ProcessGroupOptions`), the binding does *not*
  create a matching Python class for it. Instead the pyclass constructor takes
  the options as `#[pyo3(signature = (*, field=None, ...))]` keyword
  arguments, builds the crate's options struct from defaults, and applies only
  what was actually passed (see `PyProcessGroup::new` in `group.rs`). This
  keeps the Python surface flat (`ProcessGroup(max_memory=..., cpu_quota=...)`)
  instead of forcing callers to construct and thread through a second object.
- **Sync/async verb parity (the `a`-prefix).** Every consuming verb ships as a
  pair: a blocking one (`output`, `run`, `start`, …) and an `a`-prefixed
  asyncio one (`aoutput`, `arun`, `astart`, …) that accepts the identical
  arguments and returns the identical wrapped type. This holds across
  `Command`/`Pipeline`, every runner (real and test doubles), `RunningProcess`,
  `ProcessGroup`, `Supervisor`, and `CliClient`. A new verb should ship both
  halves together, wired through `block_on`/`drive_async` respectively.
- **`gil_used = false`.** See the free-threading note above — a deliberate,
  narrowly-justified opt-in, not a default to imitate carelessly in a module
  that *does* need shared mutable state outside PyO3's own guarding.

## The pure-Python layer (`src/processkit/`)

Alongside the compiled `_processkit` extension, a small amount of hand-written
Python composes on top of it rather than adding more Rust surface:

- **`_aio.py`** — asyncio readiness helpers (`wait_until`, `wait_for_line`,
  `wait_for_port`, `wait_for_path`) and `WaitTimeout`. These compose on the
  already-compiled async surface (a `StdoutLines` iterator, a plain TCP
  connect) instead of bridging the crate's own probing methods, which keeps
  them simpler and usable against *any* server, not only one this package
  started.
- **`_protocols.py`** — the `ProcessRunner` / `StreamingRunner` `Protocol`
  classes: the typed dependency-injection seam that lets code written against
  "a runner" accept the real `Runner`, any of the test doubles, or a
  hand-rolled double, all checked structurally by the type checker.
- **`_types.py`** — the public type aliases (`StrPath`, `Args`, `SignalName`,
  `RetryIf`, `ReadableBuffer`, `LineTerminatorName`, `Priority`) exported so
  callers can annotate their own wrappers with the same vocabulary the API
  uses.
- **`__init__.py`** — the facade. It re-exports the compiled classes/functions
  from `_processkit` together with the pure-Python helpers above, and its
  `__all__` list **is** the public surface: anything not listed there is not
  public, regardless of what's importable by digging into a submodule. The
  test-double runners (`ScriptedRunner`, `RecordReplayRunner`,
  `RecordingRunner`, `DryRunRunner`, `Reply`, `Invocation`) are deliberately
  excluded from the top-level `__all__` and re-exported instead from
  `processkit.testing`, so the production surface and the testing surface
  stay visibly separate.

## Guarding against drift: the stub/runtime/surface triangle

The compiled module (`_processkit`), the hand-written type stub
(`src/processkit/_processkit.pyi`), and the package's `__all__` re-exports are
three independent, hand-maintained mirrors of one surface. Nothing keeps them
in sync automatically — a renamed method, a new pyclass, or a dropped kwarg
default can drift silently in any one of them. Two independent mechanisms
catch that:

1. **`tests/test_api_surface.py`** is an AST-based drift guard, run as part of
   the normal test suite. It parses `_processkit.pyi` and compares it against
   the compiled module at runtime: every compiled class/function must be
   stubbed (and vice versa), every class's members must match (name, and
   property-vs-method kind), every `__all__` must be sorted/unique/importable
   and cover every compiled export and every shim module's own `__all__`, the
   (async) context-manager dunders must be declared where promised, and every
   exported exception must remain a `ProcessError` subclass. A dedicated test
   (`test_signature_parameters_match_the_stub`) additionally compares each
   callable's actual *parameter list* (name, kind, whether it has a default)
   against the stub's — catching a renamed/reordered kwarg or a dropped
   default that the name-only checks can't see.
2. **`stubtest` (mypy.stubtest)**, run in CI's `typecheck` job
   (`uv run python -m mypy.stubtest processkit --ignore-disjoint-bases
   --allowlist stubtest-allowlist.txt`), checks the stub against the compiled
   module from the opposite direction — signature *shape* (parameter
   names/kinds/defaults) and member existence both ways, at a level
   `test_api_surface.py`'s hand-written checks don't reach. `stubtest-allowlist.txt`
   suppresses only the small set of irreducible false positives this pairing
   produces (PyO3's `__new__`-only construction vs. the stub's `__init__`
   form, module-level `Literal` aliases stubtest doesn't recognize as such,
   and the compiled module's own auto-generated `__all__`) — every entry there
   documents *why* it's a false positive, not a real gap, and an unused entry
   fails CI (`--ignore-disjoint-bases` is passed but
   `--ignore-unused-allowlist` is not), so a stale suppression surfaces on its
   own.

**When you add a new pyclass, method, property, or module-level function:**
add it to the `#[pymethods]`/`#[pyfunction]` in Rust, add the matching
declaration to `_processkit.pyi`, and re-export it (top-level `__init__.py`
for production surface, `processkit/testing.py` for a test double) if it's
meant to be public. Run `uv run pytest tests/test_api_surface.py` and
`uv run python -m mypy.stubtest processkit --ignore-disjoint-bases --allowlist
stubtest-allowlist.txt` locally (both also run in CI) before opening a pull
request — they will fail loudly, and specifically, if any of the three views
disagree.

## Rust unit tests (`cargo test`) vs. the Python suite (`tests/`)

The binding has two independent levels of test coverage, split by what they
can exercise without a live Python interpreter:

- **Rust `#[cfg(test)]` modules** (`src/convert.rs`, `src/supervisor.rs`) cover
  the crate's *pure, PyO3-free helpers* — string/number parsing
  (`parse_priority`, `parse_signal`/`parse_signal_name`, `parse_overflow_mode`,
  `parse_line_terminator`, `parse_restart_policy`, `stop_reason_str`) and
  boundary-value validation (`positive_duration`/`nonnegative_duration`'s
  NaN/infinite/negative/overflowing-`Duration` cases,
  `build_output_buffer_policy`'s cap combinations). These are cheap to write
  and run per-case (every named preset, every alias, the unknown-name
  rejection), which the Python suite can only reach indirectly and rarely
  exhaustively. `cargo test` runs them **without** the `extension-module`
  feature — the crate is deliberately structured (see the `[features]` comment
  in `Cargo.toml`) so `cargo test`/`cargo check` work without ever linking as a
  Python extension; the handful of these tests that do need the GIL (e.g.
  `parse_signal`'s `Bound<'_, PyAny>` argument) call `Python::initialize()`
  first, since nothing else brings up the interpreter in a plain test binary.
  `cargo test` runs in CI's `rust-lint` job alongside `cargo fmt`/`cargo
  clippy`.
- **`tests/` (pytest, `uv run pytest`)** covers everything that needs PyO3, the
  GIL, or a real child process/event loop: the compiled classes' behavior
  (`Command`, `Pipeline`, `ProcessGroup`, `Supervisor`, `CliClient`, the runner
  doubles), the sync/async verb pairs, exception mapping, the stdout/stderr
  capture and tee pipeline, and the stub/runtime/surface drift guards above.
  This is also where a parsing helper's *observable* behavior through the
  Python-facing API is covered end-to-end (e.g. `Command.priority("bogus")`
  raising `ValueError`), even though the exhaustive boundary-value cases for
  the helper itself live in the Rust tests instead.

When adding a new pure helper to `convert.rs`/`supervisor.rs`, prefer a Rust
`#[cfg(test)]` case for its boundary values; reach for a Python test only for
behavior that's actually observable through the compiled API (an exception's
type/message, a builder's resulting policy) rather than the helper's internals
directly.
