# Changelog

All notable changes to **processkit** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Synchronous `Command` builder over the `processkit` Rust crate (pinned at
  `=1.0.1`): `output()` (captures a non-zero exit, timeout, and signal-kill as
  data), `run()` (returns trimmed stdout, raises on failure), `exit_code()`, and
  `probe()`, with `arg`/`args`/`cwd`/`env`/`timeout` configuration. The program
  and working directory accept any `os.PathLike`, not only `str`.
- `ProcessResult` with `stdout`, `stderr`, `code`, `is_success`, `timed_out`,
  `signal`, `program`, `duration_seconds`, and `combined()`.
- `ProcessGroup` context manager — a kill-on-drop container for a process tree;
  `start()` a command into it, inspect `mechanism` / `members()`, and the whole
  tree (grandchildren included) is reaped on `with`-exit or `shutdown()`.
- `RunningProcess` handle exposing the child `pid`.
- Exception hierarchy rooted at `ProcessError`: `NonZeroExit`, `Timeout`,
  `Cancelled`, `Signalled`, `ProcessNotFound`, `Unsupported`. The data-carrying
  ones expose structured fields — e.g. `NonZeroExit.code` / `.stdout` / `.stderr`
  / `.program`, `Timeout.timeout_seconds`, `Signalled.signal` — so a failure can
  be inspected programmatically, not just read as a message.
- Blocking synchronous calls are interruptible: `Ctrl+C` (SIGINT) raises
  `KeyboardInterrupt` promptly and tears down the run's process tree, instead of
  hanging until the child exits.
- Asyncio-native surface (tokio ↔ asyncio bridge). Cancelling an awaited run —
  directly, or via `asyncio.wait_for` / `asyncio.timeout` — tears down the whole
  process tree and raises `asyncio.CancelledError`.
  - `Command`: `aoutput()`, `arun()`, `aexit_code()`, `aprobe()`, and `astart()`
    (returns a `RunningProcess` for streaming/interactive I/O).
  - `RunningProcess`: `async for line in proc.stdout_lines()`, `output_events()`
    (stdout+stderr as `OutputEvent`s), interactive `take_stdin()` →
    `ProcessStdin` (`write`/`write_line`/`flush`/`close`), and `await`able
    `wait()` → `Outcome`, `finish()` → `Finished`, `output()` → `ProcessResult`,
    plus `start_kill()` / `shutdown(grace_seconds)`.
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
    sync/async run verbs and `timeout()`.
  - **Supervision**: `Supervisor(cmd, restart=…, max_restarts=…, backoff_initial=…,
    backoff_factor=…, max_backoff=…, jitter=…, stop_when=…)` with `run()` /
    `arun()` → `SupervisionOutcome`.
  - **Readiness probes**: `await wait_for_port(host, port, timeout)` and
    `await wait_for_line(lines, predicate, timeout)`.
  - New types/exception: `Pipeline`, `ProcessGroupStats`, `Supervisor`,
    `SupervisionOutcome`, `ResourceLimit`.
- Testing seam: a `Runner` (real) and a `ScriptedRunner` (test double) with a
  uniform sync + async (`a`-prefixed) `output`/`run`/`exit_code`/`probe`/`start`
  interface, plus `Reply`
  (`ok`/`fail`/`timeout`/`signalled`/`lines`/`pending`). Inject a `Runner` in
  production and a `ScriptedRunner` in tests — no real processes spawned; the
  results returned are genuine `ProcessResult` / `RunningProcess` objects.
- A task-oriented [cookbook](docs/cookbook.md).
- Type stubs (`_processkit.pyi`) for the compiled extension.
- A [platform support & caveats](docs/platforms.md) matrix documenting per-OS
  teardown, resource-limit, signal, and stats behaviour.
- **Stability commitment:** as of 1.0 the public API follows SemVer — breaking
  changes land only in a new major version.

### Notes

- This is the **1.0** release: the public API is frozen.
- Distributed as abi3 wheels for CPython 3.10+ (standard/GIL builds);
  free-threaded (PEP 703) support is tracked for a later release.

[Unreleased]: https://github.com/ZelAnton/processkit-py/commits/main
