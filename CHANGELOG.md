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
- Provisional async surface on `Command`: `aoutput()` / `arun()` (tokio ↔ asyncio
  bridge). Cancelling the awaiting asyncio task tears down the process tree and
  raises `asyncio.CancelledError`. The async surface is finalised in Phase 2.
- Type stubs (`_processkit.pyi`) for the compiled extension.

[Unreleased]: https://github.com/ZelAnton/processkit-py/commits/main
