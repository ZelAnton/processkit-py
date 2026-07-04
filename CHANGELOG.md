# Changelog

All notable changes to **processkit** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `Invocation.env_is(name, value)` / `has_env(name)` — the platform-correct
  (case-insensitive on Windows, last write wins) effective-override check. The
  existing `env` dict is plain Python dict semantics, not platform env-key
  rules: a same-case duplicate key collapses to its last value, but a
  differently-cased Windows duplicate (`"Path"`/`"PATH"`) survives as two
  separate entries — use `env_is()`/`has_env()` for the correct answer either
  way.

### Changed
- `[project.urls] Homepage` in `pyproject.toml` now points at the project
  overview site (https://zelanton.github.io/processkit/) instead of the
  GitHub repository, which is still linked separately as `Repository`.

### Fixed
- `wait_for()`'s deadline handling no longer swallows the *caller's* own
  cancellation (turning it into a misleading `TimeoutError`) if that cancellation
  lands while the timed-out predicate is being cancelled and drained; it also no
  longer cancels a pre-existing `asyncio.Future`/`Task` passed in as the
  predicate's own awaitable (only a task it created itself), no longer discards a
  condition that turns out true in the same tick as the deadline, and no longer
  swallows a `SystemExit`/`KeyboardInterrupt` raised by the predicate.
- `wait_for_line()` no longer masks a builtin-`TimeoutError`-family exception
  raised by the predicate or the stream itself behind the generic timeout
  message; it now shares `wait_for()`'s bounding, so `timeout=0` reliably
  evaluates once instead of sometimes short-circuiting first.
- `wait_for()`, `wait_for_line()`, and `wait_for_port()` now reject a NaN
  `timeout`/`interval` with `ValueError` instead of polling forever.
- `wait_for_port()` now chains the last connection attempt's exception (e.g. a
  DNS failure) as the raised `TimeoutError`'s `__cause__` instead of discarding
  it.
- A consuming verb called without the context it needs — an async verb
  (`RunningProcess.wait`/`finish`/`output`/`output_bytes`/`profile`/`shutdown`/
  `__aexit__`, `Supervisor.arun`, `ProcessGroup.ashutdown`/`__aexit__`) called
  with no running `asyncio` event loop, or a sync verb (`Supervisor.run`,
  `ProcessGroup.shutdown`/`__exit__`) called from inside an already-running
  async context — now raises a clear error and leaves the handle intact and
  reusable. Previously the same misuse destroyed the live process (or spent the
  handle) as a side effect of the error path.
- `Timeout.timeout_seconds` is now `None` (not a misleading `0.0`) when the
  deadline wasn't known to the checking verb (a scripted/cassette-replayed
  timeout with no `timeout()` configured).
- `ProcessStdin.write()` / `write_line()` / `flush()` / `close()` now raise the
  matching stdlib `OSError` subclass (e.g. `BrokenPipeError` for a closed
  child), not a bare `OSError`.
- `ProcessGroup.signal()`'s docstring no longer claims Windows "emulates" the
  POSIX signals — a Job Object only delivers `kill` there; every other name
  raises `Unsupported`, as it always has.

## [1.0.0] - 2026-07-04

### Added
- Synchronous `Command` builder over the `processkit` Rust crate (pinned at
  `=1.2.0`): `output()` (captures a non-zero exit, timeout, and signal-kill as
  data), `output_bytes()` (raw-bytes stdout → `BytesResult`), `run()` (returns
  trimmed stdout, raises on failure), `exit_code()`, and `probe()`, configured
  with `arg`/`args`/`cwd`/`env`/`envs`/`env_remove`/`env_clear`/`timeout`/
  `output_limit`. The program and working directory accept any `os.PathLike`, not
  only `str`.
- Full environment control on `Command`: `envs(mapping)` (set many at once),
  `env_remove(key)`, and `env_clear()` (start from an empty environment) — for
  reproducible or locked-down (sandboxed) children.
- Output caps on `Command`: `output_limit(max_bytes=…, max_lines=…,
  on_overflow="drop_oldest"|"drop_newest"|"error")` bounds how much captured
  output is retained (cap `max_bytes` to bound the parent's memory against an
  untrusted child; a `max_lines`-only cap does not); on `"error"` overflow the
  run raises `OutputTooLarge`.
- More `Command` knobs: `success_codes([…])` (treat the given exit codes as
  success, replacing the default `{0}` — for `grep`/`diff`-style tools),
  `inherit_env([…])`
  (allowlist inheritance), `timeout_grace()` / `timeout_signal()` (graceful
  timeout), `stdout("inherit"|"null")` / `stderr(…)` redirection, `encoding(…)` /
  `stdout_encoding` / `stderr_encoding` (decode non-UTF-8 output),
  `kill_on_parent_death()`, `create_no_window()` (Windows), and POSIX
  `uid` / `gid` / `groups` / `setsid`.
- Concurrent batch execution: `output_all` / `aoutput_all` (and `…_bytes`
  variants) run many commands with bounded `concurrency`, returning each
  `ProcessResult` — or a `ProcessError` for a spawn/I/O failure — in input order.
- `CliClient(program, *, default_timeout=…, default_env=…, default_env_remove=…)`
  — a typed wrapper for a tool you call repeatedly, with `run` / `output` /
  `output_bytes` / `exit_code` / `probe` (+ async) taking just the per-call args.
- `enable_logging()` — opt-in observability: forwards the core's per-run events to
  Python's `logging` (a `processkit` logger; DEBUG for a run, WARNING for an edge
  case). Idempotent; off by default; `argv`/`env` are never logged (secrets). Use
  `logging.basicConfig(level=…)` and filter the `processkit` logger as usual.
- `RunningProcess` live introspection (`elapsed_seconds`, `cpu_time_seconds`,
  `peak_memory_bytes`, `stdout_line_count` / `stderr_line_count`, `owns_group`),
  plus `output_bytes()` and `profile(every_seconds)` → `RunProfile`. A `RunProfile`
  carries the run's full `outcome` (`code` / `signal` / `timed_out` — a superset of
  `wait()`) alongside the CPU/memory samples (`cpu_time_seconds`,
  `peak_memory_bytes`, `avg_cpu_cores`, `samples`).
- Synchronous `Command.start()` — a blocking twin of `astart()` returning a live
  `RunningProcess` for streaming a child from synchronous code (its consuming
  methods `wait` / `finish` / `output` / … remain coroutines, awaited from an
  event loop).
- `RecordReplayRunner` test double — `record(path)` real runs then `save()`, and
  `replay(path)` offline; plus `output_bytes` on `Runner` / `ScriptedRunner`. It
  records and replays the streaming `start()` verb too (record is capture-whole;
  interactive mid-stream stdin can't be cassette-recorded — script those with
  `ScriptedRunner`); `output_bytes` through a cassette raises `Unsupported` (a
  text fixture can't reproduce exact bytes).
- `RecordingRunner` spy test double — `RecordingRunner.replying(reply)` answers
  every command with one canned `Reply` and records each call, so a test can
  assert on *what* its code ran: `calls()` returns every `Invocation` (in order)
  and `only_call()` the single one. Each `Invocation` exposes `program`, `args`,
  `cwd`, `env`, `has_stdin`, and `has_flag(flag)`; its `repr` is redacted (program
  + arg count + env names, never values). Completes the test-double set.
- `ProcessResult` with `stdout`, `stderr`, `code`, `is_success`, `timed_out`,
  `signal`, `program`, `duration_seconds`, `truncated`, and `combined`; plus a
  `BytesResult` (raw-bytes `stdout`, text `stderr`) from `output_bytes()` /
  `aoutput_bytes()`.
- `ProcessGroup` context manager — a kill-on-drop container for a process tree;
  `start()` a command into it, inspect `mechanism` / `members()`, and the whole
  tree (grandchildren included) is reaped on `with`-exit or `shutdown()`.
- `RunningProcess` handle exposing the child `pid`.
- Exception hierarchy rooted at `ProcessError`: `NonZeroExit`, `Timeout`,
  `Signalled`, `ProcessNotFound`, `PermissionDenied`, `Unsupported`,
  `OutputTooLarge`. `Timeout` is also a builtin `TimeoutError`, `ProcessNotFound`
  is also a `FileNotFoundError`, and `PermissionDenied` is also a
  `PermissionError` (matching `asyncio` / `subprocess`), so the stdlib `except`
  clauses catch them. The data-carrying ones expose structured fields — e.g.
  `NonZeroExit.code` / `.stdout` / `.stderr` / `.program`,
  `Timeout.timeout_seconds`, `Signalled.signal`, `OutputTooLarge.max_bytes` /
  `.total_bytes`, `Unsupported.operation` — so a failure can be inspected
  programmatically, not just read as a message. (`ResourceLimit` carries no extra
  field; its reason is `str(exc)`.)
- Blocking synchronous calls are interruptible: `Ctrl+C` (SIGINT) raises
  `KeyboardInterrupt` promptly and tears down the run's process tree, instead of
  hanging until the child exits.
- Asyncio-native surface (tokio ↔ asyncio bridge). Cancelling an awaited run —
  directly, or via `asyncio.wait_for` / `asyncio.timeout` — tears down the whole
  process tree and raises `asyncio.CancelledError`.
  - `Command`: `aoutput()`, `aoutput_bytes()`, `arun()`, `aexit_code()`,
    `aprobe()`, and `astart()` (returns a `RunningProcess` for
    streaming/interactive I/O).
  - `RunningProcess`: `async for line in proc.stdout_lines()`, `output_events()`
    (stdout+stderr as `OutputEvent`s), interactive `take_stdin()` →
    `ProcessStdin` (`write`/`write_line`/`flush`/`close`), and `await`able
    `wait()` → `Outcome`, `finish()` → `Finished`, `output()` → `ProcessResult`,
    plus `kill()` / `shutdown(grace_seconds)`. It is also a context manager
    (`with` / `async with`): exiting the block tears the process down
    deterministically — a hard kill of the whole private tree for a standalone
    `start()`/`astart()` handle — without relying on Python's GC.
  - `ProcessGroup`: `async with`, `astart()`, `ashutdown()`.
- `Command` stdin configuration: `stdin_bytes()` / `stdin_text()` (feed input
  upfront) and `keep_stdin_open()` (write interactively after start).
- New result types: `Outcome`, `Finished`, `OutputEvent`.
- Higher-level features:
  - **Resource limits** on `ProcessGroup`: keyword-only `max_memory`,
    `max_processes`, `cpu_quota`, `shutdown_grace`, `escalate_to_kill`
    (enforced via the Windows Job Object or a Linux cgroup-v2 *root*).
  - **Signals & observability** on `ProcessGroup`: `signal("term"|…)`,
    `suspend()`, `resume()`, `kill_all()`, and `stats()` →
    `ProcessGroupStats`.
  - **Pipelines**: `Command | Command` (or `.pipe()`) → `Pipeline`, with the
    sync/async run verbs (incl. `output_bytes()` / `aoutput_bytes()` for a binary
    tail) and `timeout()`.
  - **Supervision**: `Supervisor(cmd, restart=…, max_restarts=…, backoff_initial=…,
    backoff_factor=…, max_backoff=…, jitter=…, stop_when=…, storm_pause=…,
    failure_threshold=…, failure_decay=…)` with `run()` / `arun()` →
    `SupervisionOutcome`. Setting `storm_pause` enables the failure-storm guard
    (crash-loop circuit-breaker), reported via `SupervisionOutcome.storm_pauses`.
  - **Readiness probes**: `await wait_for_port(host, port, *, timeout)`,
    `await wait_for_line(lines, predicate, *, timeout)`, and
    `await wait_for(predicate, *, timeout)` (poll any sync-or-async condition).
  - New types/exception: `Pipeline`, `ProcessGroupStats`, `Supervisor`,
    `SupervisionOutcome`, `ResourceLimit`.
- Testing seam: a `Runner` (real) and a `ScriptedRunner` (test double) with a
  uniform sync + async (`a`-prefixed) `output`/`run`/`exit_code`/`probe`/`start`
  interface, plus `Reply`
  (`ok`/`fail`/`timeout`/`signalled`/`lines`/`pending`). Inject a `Runner` in
  production and a `ScriptedRunner` in tests — no real processes spawned; the
  results returned are genuine `ProcessResult` / `RunningProcess` objects. The
  injected runner is typed by the `ProcessRunner` `typing.Protocol`, which
  `Runner` / `ScriptedRunner` / `RecordReplayRunner` / `RecordingRunner` all
  satisfy structurally. The test doubles (`ScriptedRunner`, `RecordReplayRunner`,
  `RecordingRunner`) plus `Reply` and `Invocation` live in the **`processkit.testing`**
  submodule; `Runner` and `ProcessRunner` are top-level (production).
- A full [documentation guide set](docs/README.md): a task-oriented
  [cookbook](docs/cookbook.md) plus deep guides for
  [running commands](docs/commands.md), [process groups](docs/process-groups.md),
  [streaming & interactive I/O](docs/streaming.md), [pipelines](docs/pipelines.md),
  [timeouts & cancellation](docs/timeouts-and-cancellation.md),
  [supervision](docs/supervision.md), and [testing](docs/testing.md), tied
  together by a progressively-disclosed README with a cover illustration.
- Type stubs (`_processkit.pyi`) for the compiled extension.
- A [platform support & caveats](docs/platforms.md) matrix documenting per-OS
  teardown, resource-limit, signal, and stats behaviour.
- **Stability commitment:** as of 1.0 the public API follows SemVer — breaking
  changes land only in a new major version.
- **Free-threaded CPython (PEP 703):** the extension declares `gil_used = false`,
  so importing it on a free-threaded build (CPython 3.14t) does **not** re-enable
  the GIL. Shipped as a version-specific free-threaded wheel alongside the
  abi3 (GIL) wheel, and the full test suite runs on the free-threaded interpreter
  in CI. Also adds CPython **3.14** to the supported set (the abi3 wheel already
  runs there).
- **musllinux (Alpine/musl) wheels** for x86_64 and aarch64, alongside the
  existing manylinux (glibc) wheels — so `pip install` gets a binary wheel on
  Alpine-based images instead of building from the sdist. Both the abi3 GIL wheel
  and the free-threaded cp314t wheel ship per libc. CI builds and smoke-tests the
  x86_64 musllinux wheels on every push (aarch64 builds natively at release).
- Packaging metadata for the PyPI page: Trove classifiers (CPython 3.10–3.14, the
  supported operating systems, topics) and project URLs (Documentation, Issues).
- Runnable [`examples/`](examples/) — self-contained, cross-platform programs, one
  per target niche (whole-tree no-orphan teardown, a readiness-gated server,
  supervision-until-healthy, a resource-limited sandbox). Each is exercised in CI.
- Docs: a **"Coming from subprocess"** guide that maps `subprocess` /
  `asyncio.subprocess` patterns onto their processkit equivalents (verbs, flags,
  pipelines, the exception mapping) and shows the whole-tree containment the stdlib
  can't express.

### Changed
- Renamed `Command.ok_codes()` → **`success_codes()`** (clearer that it is the
  whole success set, not an addition), and an empty sequence now raises
  `ValueError` instead of being silently ignored.
- Renamed `RunProfile.exit_code` → **`code`**, matching the exit-code field on
  every other result type (`ProcessResult`, `Outcome`, …).
- `Command.encoding()` / `stdout_encoding` / `stderr_encoding` now also accept
  common **Python codec aliases** (`latin_1`, `utf_8`, `euc_jp`, …) in addition to
  WHATWG labels, normalized to the WHATWG form; an unmappable label raises
  `ValueError` naming the WHATWG equivalent. (WHATWG `iso-8859-1` / Python
  `latin_1` decode as windows-1252.)
- `Command.arg()` / `args()` and the `Command(...)` constructor's args accept any
  `os.PathLike[str]` (e.g. `pathlib.Path`), not only `str`, so a `Path` argument
  needs no `str()`. (`bytes` paths are not accepted; `StrPath` was narrowed to
  `str | os.PathLike[str]` to match.)
- Closed-set string parameters and return values are typed as `Literal` in the
  stubs (signal names, `restart`, `mechanism`, `SupervisionOutcome.stopped`,
  `OutputEvent.stream`) for editor autocomplete and `mypy` typo-catching.
- Exported the `StrPath` (`str | os.PathLike[str]`) and `SignalName` (the signal-name
  `Literal`) type aliases from the package, so your own wrappers can annotate against
  the same types the API accepts.
- Renamed `ProcessGroup(memory_max=…)` → **`max_memory`**, so every ceiling on the
  surface follows the `max_*` convention (`max_processes`, `output_limit(max_bytes=…,
  max_lines=…)`, `Supervisor(max_restarts=…, max_backoff=…)`). The crate builder
  remains `memory_max()`.
- Renamed `RunProfile.avg_cpu` → **`avg_cpu_cores`** (self-documenting: the value is
  CPU-cores, e.g. `1.7` ≈ 1.7 cores busy).
- Renamed `RunningProcess.start_kill()` → **`kill()`**, matching
  `subprocess.Popen.kill()` (fire-and-forget; does not wait for exit).
- Renamed `ProcessGroup.terminate_all()` → **`kill_all()`** and the
  `ProcessGroup(shutdown_timeout=…)` ceiling → **`shutdown_grace`**, so the group's
  teardown surface reads as what it does — a hard kill of the whole tree, after an
  optional grace period — and lines up with `RunningProcess.kill()` and
  `Command.timeout_grace()`. The crate keeps `terminate_all()` / `shutdown_timeout()`.
- Renamed the `OutputTooLarge` overflow fields `line_limit` / `byte_limit` →
  **`max_lines`** / **`max_bytes`**, so the caps reported on overflow match the
  `output_limit(max_bytes=…, max_lines=…)` kwargs that set them.
- Moved the runner test doubles — `ScriptedRunner`, `RecordReplayRunner`,
  `RecordingRunner`, the `Reply` builder, and the `Invocation` record — into a new
  **`processkit.testing`** submodule (mirroring the crate's `processkit::testing`
  split), so the top-level `processkit` namespace is the production surface and the
  test scaffolding is one explicit import away (`from processkit.testing import
  ScriptedRunner`). `Runner` and the `ProcessRunner` protocol stay top-level.
- `ProcessResult.combined` is now a **property** (was `combined()`), matching the
  other read accessors (`stdout`, `code`, …).
- Renamed `Outcome.is_success` / `Finished.is_success` → **`exited_zero`**. These
  test literal "exit code 0" and — unlike `ProcessResult.is_success` — carry no
  `success_codes` context, so the new name no longer implies the command's own
  success verdict. Use `ProcessResult.is_success`, or test `code` against your set.
- `RunningProcess.take_stdin()` now **raises** `ProcessError` (instead of returning
  `None`) when stdin was not kept open or was already taken — so a missing
  `keep_stdin_open()` fails at the call, not later with an `AttributeError`. Its
  return type is now `ProcessStdin` (no longer `... | None`).
- The readiness helpers `wait_for()` / `wait_for_port()` / `wait_for_line()` now
  take `timeout` as a **keyword-only** argument, for uniformity.

### Removed
- `Cancelled` exception. It was never raised from the Python surface (the binding
  exposes no cancellation token; cancelling an awaited run surfaces as
  `asyncio.CancelledError`), so it was pure catch-list clutter. Re-addable
  (additive) if a token-style cancellation API is ever exposed.
- `CliClient.run_unit()` / `arun_unit()`. The success-only `-> None` verb existed
  nowhere else on the surface; use `run()` / `arun()` and ignore the returned
  stdout for the same "run, raise on failure" behavior.
- `ResourceLimit.message`. It duplicated `str(exc)` — idiomatic Python 3 exceptions
  carry no separate `.message` attribute. Read the reason via `str(exc)`.

### Fixed
- A synchronous verb called from inside a `Supervisor` `stop_when` predicate no
  longer re-enters the tokio runtime and panics (the panic was previously
  swallowed, so the predicate silently never fired); it now raises a clear
  `ProcessError`. Documented that the predicate must read the result handed to it
  rather than run new verbs.
- `Supervisor(backoff_factor=…)` is now applied (and validated) independently of
  `backoff_initial` — previously the factor was silently dropped unless
  `backoff_initial` was also passed.
- A `RecordReplayRunner.replay()` cassette miss now carries the `.program` field,
  matching every other program-bearing `ProcessError`.
- `wait_for_port()` no longer leaks the probe socket if the awaiting task is
  cancelled just after the connection is accepted.
- `wait_for()` now bounds its predicate by `timeout` — an async predicate that
  hangs no longer ignores the deadline — while propagating the predicate's own
  exception unchanged and cancelling the in-flight predicate (rather than orphaning
  it) when the awaiting task is cancelled.

### Security
- `repr(Command(...))` no longer renders argv (or env *values*): it now uses the
  crate's redacted form — program, argument *count*, and env *names* only. A repr
  is emitted everywhere (logging `%r`, f-strings, tracebacks, test diffs), so this
  prevents a secret passed as an argument from leaking through any of them. (The
  Python surface exposes no way to recover the full command line; argv remains
  visible to the OS via `ps` / `/proc` while the child runs.)
- Documentation hardening: the sandbox/privilege-drop guidance now sets all of
  `gid` / `groups` / `uid` (dropping `uid` alone leaves the child holding the
  parent's supplementary groups — a sandbox-escape footgun); documents that
  record/replay cassettes are written owner-only (`0600`, no symlink follow) on
  Unix; and warns that exception `stdout`/`stderr` still carry raw values — pass
  secrets via `env(...)`, not flags.

### Notes

- This is the **1.0** release: the public API is frozen.
- Distributed as abi3 wheels for CPython 3.10+ (standard/GIL builds), **plus a
  version-specific free-threaded wheel** for CPython 3.14t (PEP 703).
- The `RecordReplayRunner` test double enables the crate's `record` feature,
  which pulls `serde` / `serde_json` into the compiled wheel.
- `enable_logging()` enables the crate's `tracing` feature; the bridge pulls
  `tracing` / `tracing-subscriber` (registry only) into the compiled wheel.

[Unreleased]: https://github.com/ZelAnton/processkit-py/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ZelAnton/processkit-py/releases/tag/v1.0.0
