# Changelog

All notable changes to **processkit** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
-

### Changed
-

### Fixed
- `Args` (`from processkit import Args`) no longer rejects the single most
  common real call site — a variable annotated `list[str]` (or
  `list[pathlib.Path]` / `list[os.PathLike[str]]`) passed straight through to
  an argv-like parameter, e.g. `args: list[str] = [...]; cmd.args(args)`.
  `list` is invariant, so the original `list[StrPath] | tuple[StrPath, ...]`
  spelling only ever accepted a `list[StrPath]`-annotated variable or a
  literal, not a `list[str]`/`list[Path]`/`list[os.PathLike[str]]`-annotated
  one, even though the values are runtime-identical — a static-typing-only
  false positive with no runtime effect. `Args` is now a union of the concrete
  homogeneous list shapes (`list[str]`, `list[Path]`, `list[os.PathLike[str]]`)
  instead of the single invariant `list[StrPath]`; a *mixed* `str`/
  `os.PathLike[str]` argv is still accepted, now spelled as a `tuple` rather
  than a `list` literal (e.g. `cmd.args((path, "literal"))`). A bare `str`
  still does not type-check as `Args` (unchanged; see the `Args` docstring).

## [1.1.1] - 2026-07-06

### Added
- `Command.line_terminator(mode)` / `Command.stdout_line_terminator(mode)` /
  `Command.stderr_line_terminator(mode)` — choose where the line pump splits a
  stream into lines: `"newline"` (default, splits on `\n` only, unchanged
  behavior) or `"carriage_return"` (also splits on a bare `\r`, delivering each
  frame of a `curl`/`pip`/`apt`-style redrawn-in-place progress bar live instead
  of piling it all up into one line at EOF). `line_terminator` sets both
  streams at once; the `stdout_`/`stderr_` variants target one stream, leaving
  the other's framing untouched. Binds `processkit` 2.1.0's
  `Command::line_terminator`/`stdout_line_terminator`/`stderr_line_terminator`
  (`LineTerminator`), exposed as the new `LineTerminatorName` string-preset
  alias.
- `testing.Reply.with_stderr(text)` — attach stderr to a scripted reply,
  including a successful (`Reply.ok(...)`) one, without resorting to
  `Reply.fail(0, ...)` as a workaround.
- `processkit.testing.DryRunRunner` — a render-only test double that never
  spawns a process: every verb renders the command to its display-quoted line
  (via the crate's own `Command.command_line()` quoting) and returns a
  synthetic success, the seam behind a tool's own `--dry-run`/`--echo` mode.
  Inspect the rendered lines with `commands()` / `only_command()`, or stream
  them live as each call happens with `on_invocation(callback)`. Works at every
  runner injection point (`output_all` and friends, `Supervisor`, `CliClient`,
  `runner=`), like the other doubles. (Binds `processkit` 2.1.0's
  `testing::DryRunRunner`.)
- `Supervisor(..., give_up_when=classifier)` — classify a permanent failure so
  supervision gives up instead of restarting a crash forever, reporting the new
  `SupervisionOutcome.stopped == "gave_up"`. Bound as a **Python callable**
  (like `stop_when`, not a `retry_if`-style string preset — the crate's
  classifier is a per-attempt closure, and a useful verdict is result-specific,
  not a fixed vocabulary). The callback receives one argument mirroring the
  crate's `GiveUpAttempt` sum type, dispatched with `isinstance`: a
  `ProcessResult` for a crashed run that produced a result (classify by e.g.
  `attempt.code`), or a `ProcessError` subclass for a launch that never produced
  one (classify by e.g. `isinstance(attempt, ProcessNotFound)` for a missing
  binary). Consulted only for a crash the policy would otherwise restart, ahead
  of `max_restarts` and the failure-storm guard. A crash verdict stops with
  `stopped == "gave_up"`; a launch-failure verdict has no result to report and
  surfaces the classified error directly from `run()`/`arun()`. Off by default —
  a permanent failure restarts as before. The classifier runs on the runtime
  thread under the GIL; a raising or non-bool callback reads as "not permanent"
  (keep restarting) and is surfaced via the unraisable hook, never silently
  swallowed.
- `Command.umask(mask)` — set the child's POSIX file-mode creation mask; on a
  non-POSIX platform the run raises `Unsupported`, matching the existing
  `uid`/`gid`/`groups`/`setsid` verbs.
- `Command.priority(level)` — set the child's CPU-scheduling priority, one of
  the named presets `"idle"`, `"below_normal"`, `"normal"`, `"above_normal"`,
  `"high"` (new `Priority` type alias). Unix `nice`/`setpriority`, Windows
  priority class — unlike the privilege/POSIX-only verbs above, supported on
  **both** platform families, so it never raises `Unsupported`. Raising to
  `"high"` on Unix without `CAP_SYS_NICE`/root raises `PermissionDenied`
  instead of silently applying a lower priority.
- `Command.timeout_opt(seconds)` — like `timeout()`, but takes `float | None`,
  convenient when a timeout arrives from config as `Optional[float]`: a value
  behaves exactly like `timeout(seconds)`, `None` clears a prior `timeout()`
  exactly like `no_timeout()`.
- `Command.retry_never()` — explicitly opt one command out of retrying, even
  when it runs through a `CliClient` configured with a `default_retry_if`.
- `NonZeroExit` / `Timeout` / `Signalled` now carry a `stdout_bytes: bytes | None`
  field — the exact raw stdout bytes when the error came from a checking verb over
  `output_bytes()` (e.g. `BytesResult.ensure_success()`), `None` on the text path
  (`run()` / `output()`) where `stdout` is already the complete decoded text.
  When present, these are the exact pre-decode bytes `stdout` is a lossy UTF-8
  view of (they differ only for non-UTF-8 output). Binds processkit 2.1.0's
  `Error::stdout_bytes()`.

### Changed
- `Command.output_limit(max_bytes=...)`'s byte ceiling now also bounds the raw
  stdout of `output_bytes()` / `aoutput_bytes()`, matching processkit 2.1.0 —
  previously a byte cap bounded only the line-pumped stderr and raw stdout was
  always unbounded. Under `on_overflow="error"` an over-cap `output_bytes()` run
  now raises `OutputTooLarge` (with `max_lines=None` — raw bytes have no line
  count) where it once returned all bytes; under a drop mode its retained bytes
  are bounded to a head/tail with `BytesResult.truncated` set. A `max_lines` cap
  still never bounds raw stdout. This applies to every inherited `output_bytes`
  consumer that runs a `Command` built with such a policy (`CliClient`,
  `Pipeline`, `RunningProcess`, `ProcessGroup`, and the `runner=` doubles). The
  `Supervisor` capture policy is unaffected — it captures line-based output only
  and has no `output_bytes` verb.

### Fixed
-

## [1.1.0] - 2026-07-06

### Breaking
- `RunningProcess`'s consuming verbs now come in a sync/async pair, like
  everywhere else in this library, instead of being coroutine-only. Migration:
  `await proc.wait()` → `await proc.aoutcome()` (renamed — `await` is a
  reserved word, so the async twin of the new sync `outcome()` couldn't be
  called `await()`); `await proc.finish()` → `await proc.afinish()`;
  `await proc.output()` → `await proc.aoutput()`; `await proc.output_bytes()`
  → `await proc.aoutput_bytes()`; `await proc.profile(...)` →
  `await proc.aprofile(...)`; `await proc.shutdown(...)` →
  `await proc.ashutdown(...)`. Each bare name is now a new **synchronous**
  method (`proc.outcome()`, `proc.finish()`, `proc.output()`,
  `proc.output_bytes()`, `proc.profile(...)`, `proc.shutdown(...)`), making a
  handle from the synchronous `Command.start()` / `Runner.start()` genuinely
  usable end-to-end with no event loop at all — not just for the
  monitor-and-`kill()` pattern. No aliasing was possible (the old bare names
  now mean something different — synchronous — so keeping them pointing at the
  old async behavior would be actively misleading, not merely redundant).
  `RunningProcess.shutdown()`/`ashutdown()` also now match
  `ProcessGroup.shutdown()`/`ashutdown()`'s naming exactly, closing a trap
  where the same verb name meant "call it" on one class but "await it" on the
  other.
- `ProcessRunner` no longer includes `start`/`astart` — it is now the
  capture/check verb surface only (`output`/`run`/`exit_code`/`probe` and
  their `a`-prefixed twins). A new `StreamingRunner(ProcessRunner)` protocol
  adds `start`/`astart` back for code that also needs a live `RunningProcess`
  handle. Migration: annotate an injection point that only calls the
  capture/check verbs as `ProcessRunner` (now narrower, easier for a custom
  double to satisfy); annotate one that also calls `start`/`astart` as
  `StreamingRunner`. Every built-in runner (`Runner`, `ScriptedRunner`,
  `RecordingRunner`, `RecordReplayRunner`) satisfies `StreamingRunner` (and
  therefore `ProcessRunner` too), so existing injected-runner call sites are
  unaffected — only code that annotated *against* `ProcessRunner` expecting
  `start`/`astart` to be part of it needs to switch to `StreamingRunner`. The
  internal `_runner.py` module (never part of the public import path) is
  renamed `_protocols.py` to reflect holding two protocols now, not one.
- `wait_for()` is renamed `wait_until()` — the old name collided with
  `asyncio.wait_for`, which bounds one *awaitable*, not a *polled predicate*
  (different semantics entirely). Migration: `await wait_for(...)` →
  `await wait_until(...)`, same arguments. No alias was kept — a `wait_for`
  alias sitting next to `asyncio.wait_for` in the same import line would
  perpetuate exactly the confusion this rename fixes. All three readiness
  helpers (`wait_until`, `wait_for_port`, `wait_for_line`) now raise
  `WaitTimeout` (`ProcessError`, `TimeoutError`) instead of a bare
  `TimeoutError` on their own deadline — still catchable as `except
  TimeoutError`, but now carrying `timeout_seconds` (and, for
  `wait_for_port`, `host`/`port`) as structured fields instead of only a
  message string.

### Added
- A **pytest plugin**, autoloaded via a `pytest11` entry point in every pytest
  session where processkit is installed (nothing to add to `conftest.py`; the
  plugin module is pure Python and import-safe). It exposes the
  `processkit.testing` doubles as ready-made fixtures — `scripted_runner` (a fresh
  `ScriptedRunner`), `recording_runner` (a `RecordingRunner` spy replying
  `Reply.ok("")`, the neutral default), and `record_replay_runner` (a
  `RecordReplayRunner` bound to a per-test cassette) — so injecting a test double
  is a single fixture parameter. The cassette fixture is replay-by-default with a
  vcr-style switch to record (`--processkit-record` CLI flag, then the
  `PROCESSKIT_RECORD` env var, then the `processkit_record` ini option, in that
  precedence); its file lives under the test's `tmp_path` unless the
  `processkit_cassette_dir` ini option points at a kept directory, and its name is
  derived deterministically from the test's node id. A `@pytest.mark.no_real_spawn`
  marker (registered so it passes `--strict-markers`) makes any real spawn through
  `Command`/`Pipeline`/`Runner`/`ProcessGroup` inside the marked test fail loudly,
  while injected doubles keep working. Documented in `docs/testing.md` and the
  cookbook.
- `Args` and `ReadableBuffer` type aliases (`from processkit import Args,
  ReadableBuffer`). `Args` (`list[StrPath] | tuple[StrPath, ...]`) replaces
  `Sequence[str]`/`Sequence[StrPath]` on every argv-like parameter
  (`Command`'s `args`, `ScriptedRunner.on()`/`on_sequence()`'s `prefix`,
  `CliClient.command()`/its verbs) — deliberately **not** `Sequence[StrPath]`,
  since `str` is itself structurally a `Sequence[str]` (each character is a
  `str`), so that spelling let a bare string slip through everywhere an argv
  list was expected (`cmd.args("--flag")` type-checked, then exploded into
  one argument *per character* at runtime). This is a static-typing-only
  tightening — runtime behavior (and any caller not using mypy) is
  unaffected; a mypy-strict caller passing something other than a `list`/
  `tuple` (an arbitrary custom `Sequence`) at one of these call sites may
  need to wrap it in `list(...)`. `ReadableBuffer` (`bytes | bytearray |
  memoryview`) replaces the too-narrow `bytes` on `Command.stdin_bytes()` /
  `ProcessStdin.write()` — both already accepted `bytearray`/`memoryview` at
  runtime (PyO3's buffer-protocol extraction), so this only catches up the
  stub to reality, no runtime change.
- `CliClient`'s `command()` and every verb (`run`/`output`/`output_bytes`/
  `exit_code`/`probe`, `a`-prefixed twins) now accept a `str` or any
  `os.PathLike[str]` for each argv element, unified with `Command`'s own
  `arg`/`args` typing — previously `CliClient` was `str`-only, so a
  `pathlib.Path` argument needed a manual `str()` there but not on `Command`.
- Documented explicitly: `Timeout`, `ProcessNotFound`, and `PermissionDenied`
  are transitively `OSError` subclasses too (since their builtin second base
  — `TimeoutError`/`FileNotFoundError`/`PermissionError` — has itself been an
  `OSError` subclass since Python 3.3), so `except OSError` catches all
  three alongside `except ProcessError`. No behavior change — this was
  already true; it just wasn't written down anywhere.
- Fixed: `PermissionDenied.program` is now typed `str | None` (was `str`) and
  reliably reads `None` — not a missing-attribute `AttributeError` — on the
  broader OS-refusal path with no program to name (`is_permission_denied()`
  also classifies a program-less `Io` failure, e.g. a group signal the OS
  refused, alongside the ordinary spawn-time denial that does name one).
  Mirrors the class-level default already used for `Timeout.timeout_seconds`.
- `CancellationToken` — a portable cancel switch: `Command.cancel_on(token)`
  (replaces any prior token — last write wins), `Pipeline.cancel_on(token)`
  (gap-fill — a stage with its own explicit token keeps it), and `CliClient`'s
  `default_cancel_on=` (also gap-fill) tear the run/chain down when `token`
  fires, surfacing the new `Cancelled` exception. `token.cancel()` is
  idempotent; `token.child_token()` derives a token cancelled automatically
  with its parent but cancellable independently, for scoping a broader
  shutdown token down to one operation.
- `Cancelled` exception — a run deliberately cancelled via a
  `CancellationToken`. Previously such a cancellation surfaced only as a
  plain `ProcessError` (no dedicated subclass existed since `cancel_on` had
  no binding yet); now a distinct, terminal exception — never retried by
  `Command.retry()` or restarted by `Supervisor`, matching the crate's own
  contract (a cancelled token stays cancelled forever, so a replay could only
  fail the same way).
- `ScriptedRunner.when(predicate, reply)` — reply with `reply` when
  `predicate(command)` accepts it, for a match that isn't a plain argv
  prefix (`on()`) — e.g. inspecting `cwd`/`arguments`/flags via `Command`'s
  own inspection accessors. `predicate` is infallible from the crate's
  perspective, like `Supervisor.stop_when`: a raising or non-`bool` predicate
  reads as "does not match", surfaced via the unraisable hook.
- `Reply.with_line_delay(seconds)` — sleep `seconds` before each scripted
  stdout line on a `start()`/`astart()` run, so a hermetic streaming test can
  observe genuinely incremental delivery instead of every line arriving at
  once.
- `RecordingRunner.new(inner)` — wrap any of `Runner`, `ScriptedRunner`,
  `RecordReplayRunner`, or another `RecordingRunner`, recording every call
  made through it. The general form behind the existing `replying(reply)`
  (a recorder whose inner runner is always a fresh `ScriptedRunner` replying
  with one canned `Reply`) — `new()` lets a test combine recording with a
  double it already built (e.g. a `RecordReplayRunner` cassette) or with the
  real `Runner`.
- `ProcessGroup` is now itself a runner: `group.output(cmd)` / `.run(cmd)` /
  `.exit_code(cmd)` / `.probe(cmd)` / `.output_bytes(cmd)` (+ `a`-prefixed
  twins) run `cmd` as a *shared* member of the group (not a standalone
  private tree) — the same verb surface `Runner`/`ScriptedRunner`/… expose,
  for code written against that seam that should route every spawn through
  one shared group. (Not registered as a `runner=` injection target — a
  `ProcessGroup` carries real OS resources and is injected directly by
  callers who already hold one, not through that kwarg seam.)
- `output_all()` / `aoutput_all()` / `output_all_bytes()` / `aoutput_all_bytes()`
  now reject `concurrency=0` with `ValueError` instead of silently clamping it
  to `1` (a confusing "asked for none, got some anyway").
- `Command.no_timeout()` — run without a timeout, and (unlike simply leaving
  it unset) opt out of a client-wide `CliClient` `default_timeout` gap-fill.
  Clears a prior `.timeout()`; the last of the two wins.
- `Command.stdout_tee(path, *, append=False)` / `stderr_tee(path, *,
  append=False)` — tee every decoded line of the stream to a file *as it is
  produced* (the line plus a `\n`, CRLF normalized) while the run **also** keeps
  capturing the full output: the one-line way to "stream a log to a file and
  still get the captured `ProcessResult`", without a manual loop over
  `stdout_lines()`. The sink is a **file path** (`str` / `os.PathLike[str]`);
  teeing to an arbitrary Python object as a live async writer is deliberately
  **not** supported yet (a separate, deferred feature — dispatching each line to
  a thread, re-acquiring the GIL, honoring backpressure across the FFI boundary
  is its own scope). The file is opened **at build time** — the crate takes a
  concrete sink, not a lazy factory — so an unopenable path (missing parent
  directory, a directory, a permission denial) raises the matching `OSError`
  subclass right at the builder call, not at run; it is created/truncated by
  default, or appended to with `append=True`. Inherited crate semantics: a slow
  sink applies backpressure (it does not block the runtime); a tee write error
  disables the tee for the rest of the run without breaking the run or its
  captured result (warned under `enable_logging()`); and the tee is inert unless
  the line pump runs — a no-op under `stdout("inherit")` / `stdout("null")` and
  under `output_bytes()` (raw capture), working with the line verbs (`output()`
  / `aoutput()` / `run()`, `start()` + `stdout_lines()` / `output_events()`). A
  reused command's shared sink handle **appends** across sequential re-runs
  (retries, `Supervisor` incarnations) and **interleaves** across concurrent
  pipeline stages.
- `Command.command_line()` — render the command as a single shell-quoted line
  for display (logs, error messages, a dry-run echo); includes argv, unlike
  the redacted `repr()`. Never used to actually execute anything. Plus
  `Command.program` / `Command.arguments` read-only properties (named
  `arguments`, not `args` — that name is already the builder method that
  appends args).
- `Command.unchecked_in_pipe()` — exempt a command, as a `Pipeline` stage,
  from pipefail attribution (its unclean exit, including a `SIGPIPE`, is
  skipped when the chain decides what to report); a no-op outside a
  `Pipeline`.
- `ProcessResult.ensure_success()` / `BytesResult.ensure_success()` — raise
  the same exception a checking verb would if the result's exit isn't in
  `success_codes`, for turning an already-captured `output()`/`output_bytes()`
  result into an error after the fact. Returns `self` unchanged on success, so
  it composes: `cmd.output().ensure_success().stdout`.
- `.diagnostic: str | None` on `NonZeroExit`, `Timeout`, and `Signalled` — the
  best human-facing message (captured stderr if it carries text, otherwise
  captured stdout; `None` if both streams are blank), so a generic `except
  ProcessError` handler can log/report something useful without knowing which
  of the three stream-bearing exceptions it caught.
- `Command.timeout_signal()` / `ProcessGroup.signal()` now also accept a raw
  platform signal number (an `int`), not just a portable name — the crate's
  `Signal::Other` escape hatch (Unix only; a raw number is `Unsupported` on
  Windows like every non-`Kill` signal, same as the named variants).
- `CliClient.command(args)` — a `Command` for `program <args>` with the
  client's defaults (timeout/env/retry/cancel) pre-applied; chain more
  builders for a customized one-off call, then pass the result to `run()` /
  `output()` / … (which now accept either a plain arg list or such a
  `Command` — the `IntoCommand` path). An explicit setting on the returned
  `Command` always wins over the client's default; only the gaps get filled.
- `CliClient`'s `default_env_fn={key: resolver, ...}` — a per-key zero-arg
  resolver called fresh each time a command is *built* (not each retry
  attempt) to fill an environment variable, for a credential that should be
  read freshly rather than baked in once at client-construction time (a
  static `default_env` value). An explicit per-call `env`/`default_env` at
  the same key still wins — this only fills the gap.
- `Supervisor`'s `capture_max_bytes=`/`capture_max_lines=`/
  `capture_on_overflow=` — bound (or widen) the output captured from each
  supervised incarnation; the default is already a sensible bounded tail
  (`Command.output_limit`'s own kwargs, applied here as constructor kwargs
  instead of a builder method, per the config-struct convention). Setting any
  of the three requires at least one of the two cap sizes, mirroring
  `output_limit`'s own validation.
- `Command.retry(retry_if, *, max_retries=, initial_backoff=, multiplier=,
  max_backoff=, jitter=)` and `CliClient`'s `default_retry_if=` (+
  `default_max_retries=`/`default_initial_backoff=`/`default_multiplier=`/
  `default_max_backoff=`/`default_jitter=`) — retry a run with exponential
  backoff, a cap, and jitter, while `retry_if` accepts the resulting error.
  Honored only by the success-checking verbs (`run`/`exit_code`/`probe`, and
  `CliClient`'s equivalents); ignored by `Supervisor` (its own `RestartPolicy`
  governs keep-alive restarts — a different concern), `output_all`, and
  `Pipeline`. Bound as kwargs over the crate's `RetryPolicy`, not a mirrored
  pyclass (the established config-struct convention — see `AGENTS.md`).
  `retry_if` is a named preset over the crate's own error-classification
  accessors, not an arbitrary Python callable crossing the FFI boundary:
  `"transient"` (a bare-retry-clears spawn/IO condition — interrupted,
  would-block, a busy resource) or `"transient_or_timeout"` (also retries a
  `.timeout()` expiry). `CliClient`'s tuning knobs require
  `default_retry_if=` to be set (raises `ValueError` otherwise) — the same
  explicit opt-in `Command.retry()`'s required `retry_if` already enforces.
- `wait_for_line(lines, predicate, *, timeout)` is generalized over the
  iterator's item type (previously hardcoded to `AsyncIterator[str]`) — it now
  works over any async iterator (e.g. `RunningProcess.output_events()`'s
  `OutputEvent` items), not just stdout lines, given a callable predicate.
  `predicate` also accepts a plain `str` as a substring-match shorthand
  (`wait_for_line(lines, "listening on", timeout=10)`) when the iterator
  yields `str`. Purely additive: an existing callable-predicate,
  `str`-iterator call site is unaffected.
- `Invocation.env_is(name, value)` / `has_env(name)` — the platform-correct
  (case-insensitive on Windows, last write wins) effective-override check. The
  existing `env` dict is plain Python dict semantics, not platform env-key
  rules: a same-case duplicate key collapses to its last value, but a
  differently-cased Windows duplicate (`"Path"`/`"PATH"`) survives as two
  separate entries — use `env_is()`/`has_env()` for the correct answer either
  way.
- `runner=` keyword on `output_all` / `aoutput_all` / `output_all_bytes` /
  `aoutput_all_bytes`, `Supervisor(...)`, and `CliClient(...)` — drives the
  batch/supervision/client through an injected runner (`Runner`,
  `ScriptedRunner`, `RecordingRunner`, or `RecordReplayRunner`) instead of the
  real one, so a test double stands in with no real process spawned. Defaults
  to the real `Runner` when omitted (no behavior change). `CliClient` was
  previously locked to the real runner; it is now just as testable as raw
  `Command` code.
- `ScriptedRunner.on_sequence(prefix, replies)` — reply with each of `replies`
  in turn on successive matching calls (fail a few times, then succeed), then
  repeat the last reply once exhausted. The declarative form for retry/
  supervision test scenarios.
- Prebuilt wheels for **Intel macOS** (x86_64), cross-compiled from the arm64
  (Apple Silicon) runner. Previously Intel Mac users installed from the sdist
  (needing a Rust toolchain); both macOS architectures are now covered.
- Prebuilt wheels for **Windows on ARM (arm64)**, built natively on GitHub's
  free-for-public-repos `windows-11-arm` runner. Both families ship — the abi3
  GIL wheel (CPython 3.10+) and the free-threaded cp314t wheel — so ARM64
  Windows users (a growing laptop segment) get a binary `pip install` instead
  of a from-source build needing a Rust toolchain. No cibuildwheel override was
  needed: it already provides a native ARM64 CPython 3.10 (for the abi3 wheel)
  and a native ARM64 cp314t, so the existing `build`/`skip` selectors cover
  win_arm64 unchanged.
- An **API reference** section on the documentation site — a complete,
  per-symbol index of the public surface (every class, function, protocol, type
  alias, and exception, plus the `processkit.testing` submodule), reachable from
  the site navigation. It is rendered by `mkdocstrings` straight from the type
  stub (`_processkit.pyi`) and docstrings via griffe's *static* analysis (no
  compiled extension needed, so it builds in the extension-free Docs CI), and a
  drift guard (`scripts/gen_api_reference.py --check` plus
  `tests/test_api_reference.py`) fails if the page ever omits — or invents — a
  public symbol, so the reference cannot silently diverge from the real API.

### Changed
- `[project.urls] Homepage` in `pyproject.toml` now points at the project
  overview site (https://zelanton.github.io/processkit/) instead of the
  GitHub repository, which is still linked separately as `Repository`.

### Fixed
- Fixed the macOS x86_64 release wheel build: `delocate-wheel` was rejecting
  the cross-compiled Intel wheel because the compiled extension's embedded
  minimum macOS target (10.12, the current Rust default for
  `x86_64-apple-darwin`) didn't match the wheel's `macosx_10_9` tag. The
  x86_64 cibuildwheel build now sets `MACOSX_DEPLOYMENT_TARGET=10.12`
  explicitly so the tag matches the binary.
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
  `timeout` with `ValueError` instead of polling forever; `wait_for()` and
  `wait_for_port()` reject a NaN `interval` the same way (`wait_for_line()` has
  no `interval` parameter).
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
- Error mapping now uses the `processkit` 1.2.0 crate's `Error` accessors
  instead of hand-matching each variant, closing two gaps: a cancelled run's
  exception now carries `.program` (previously missing); and a spawn/IO
  failure refused for a permission reason is now consistently `PermissionDenied`
  (previously only a spawn-time refusal was — e.g. an OS-refused
  `ProcessGroup.signal()` used to surface as a plain `ProcessError`).
- `docs/testing.md`/`docs/cookbook.md` no longer claim an unmatched
  `ScriptedRunner` call with no fallback raises `ProcessNotFound` (it raises a
  plain `ProcessError` — that was always the actual behavior, the docs were
  wrong) or that `CliClient` is un-injectable (see `runner=` above).

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

[Unreleased]: https://github.com/ZelAnton/processkit-py/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/ZelAnton/processkit-py/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/ZelAnton/processkit-py/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ZelAnton/processkit-py/releases/tag/v1.0.0
