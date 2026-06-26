# Changelog

All notable changes to **processkit** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Synchronous `Command` builder over the `processkit` Rust crate (pinned at
  `=1.0.1`): `output()` (captures a non-zero exit, timeout, and signal-kill as
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
- More `Command` knobs: `ok_codes([…])` (treat the given exit codes as success,
  replacing the default `{0}` — for `grep`/`diff`-style tools), `inherit_env([…])`
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
  `output_bytes` / `exit_code` / `probe` / `run_unit` (+ async) taking just the
  per-call args.
- `RunningProcess` live introspection (`elapsed_seconds`, `cpu_time_seconds`,
  `peak_memory_bytes`, `stdout_line_count` / `stderr_line_count`, `owns_group`),
  plus `output_bytes()` and `profile(every_seconds)` → `RunProfile`.
- `RecordReplayRunner` test double — `record(path)` real runs then `save()`, and
  `replay(path)` offline; plus `output_bytes` on `Runner` / `ScriptedRunner`.
- `ProcessResult` with `stdout`, `stderr`, `code`, `is_success`, `timed_out`,
  `signal`, `program`, `duration_seconds`, `truncated`, and `combined()`; plus a
  `BytesResult` (raw-bytes `stdout`, text `stderr`) from `output_bytes()` /
  `aoutput_bytes()`.
- `ProcessGroup` context manager — a kill-on-drop container for a process tree;
  `start()` a command into it, inspect `mechanism` / `members()`, and the whole
  tree (grandchildren included) is reaped on `with`-exit or `shutdown()`.
- `RunningProcess` handle exposing the child `pid`.
- Exception hierarchy rooted at `ProcessError`: `NonZeroExit`, `Timeout`,
  `Cancelled`, `Signalled`, `ProcessNotFound`, `Unsupported`, `OutputTooLarge`.
  `Timeout` is also a builtin `TimeoutError` and `ProcessNotFound` is also a
  `FileNotFoundError` (matching `asyncio` / `subprocess`), so the stdlib `except`
  clauses catch them. The data-carrying ones expose structured fields — e.g.
  `NonZeroExit.code` / `.stdout` / `.stderr` / `.program`,
  `Timeout.timeout_seconds`, `Signalled.signal`, `OutputTooLarge.byte_limit` /
  `.total_bytes` — so a failure can be inspected programmatically, not just read
  as a message.
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
    plus `start_kill()` / `shutdown(grace_seconds)`. It is also a context manager
    (`with` / `async with`): exiting the block tears the process down
    deterministically — a hard kill of the whole private tree for a standalone
    `start()`/`astart()` handle — without relying on Python's GC.
  - `ProcessGroup`: `async with`, `astart()`, `ashutdown()`.
- `Command` stdin configuration: `stdin_bytes()` / `stdin_text()` (feed input
  upfront) and `keep_stdin_open()` (write interactively after start).
- New result types: `Outcome`, `Finished`, `OutputEvent`.
- Higher-level features:
  - **Resource limits** on `ProcessGroup`: keyword-only `memory_max`,
    `max_processes`, `cpu_quota`, `shutdown_timeout`, `escalate_to_kill`
    (enforced via the Windows Job Object or a Linux cgroup-v2 *root*).
  - **Signals & observability** on `ProcessGroup`: `signal("term"|…)`,
    `suspend()`, `resume()`, `terminate_all()`, and `stats()` →
    `ProcessGroupStats`.
  - **Pipelines**: `Command | Command` (or `.pipe()`) → `Pipeline`, with the
    sync/async run verbs (incl. `output_bytes()` / `aoutput_bytes()` for a binary
    tail) and `timeout()`.
  - **Supervision**: `Supervisor(cmd, restart=…, max_restarts=…, backoff_initial=…,
    backoff_factor=…, max_backoff=…, jitter=…, stop_when=…)` with `run()` /
    `arun()` → `SupervisionOutcome`.
  - **Readiness probes**: `await wait_for_port(host, port, timeout)`,
    `await wait_for_line(lines, predicate, timeout)`, and
    `await wait_for(predicate, timeout)` (poll any sync-or-async condition).
  - New types/exception: `Pipeline`, `ProcessGroupStats`, `Supervisor`,
    `SupervisionOutcome`, `ResourceLimit`.
- Testing seam: a `Runner` (real) and a `ScriptedRunner` (test double) with a
  uniform sync + async (`a`-prefixed) `output`/`run`/`exit_code`/`probe`/`start`
  interface, plus `Reply`
  (`ok`/`fail`/`timeout`/`signalled`/`lines`/`pending`). Inject a `Runner` in
  production and a `ScriptedRunner` in tests — no real processes spawned; the
  results returned are genuine `ProcessResult` / `RunningProcess` objects.
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
- Packaging metadata for the PyPI page: Trove classifiers (CPython 3.10–3.14, the
  supported operating systems, topics) and project URLs (Documentation, Issues).

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

### Notes

- This is the **1.0** release: the public API is frozen.
- Distributed as abi3 wheels for CPython 3.10+ (standard/GIL builds), **plus a
  version-specific free-threaded wheel** for CPython 3.14t (PEP 703).
- The `RecordReplayRunner` test double enables the crate's `record` feature,
  which pulls `serde` / `serde_json` into the compiled wheel.

[Unreleased]: https://github.com/ZelAnton/processkit-py/commits/main
