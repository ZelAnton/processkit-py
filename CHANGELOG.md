# Changelog

All notable changes to **processkit** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Give `LifecycleEvent` immutable value semantics based on `kind`, `pid`,
  `text`, and `outcome`, including matching hashes and pickle round-trips for
  every lifecycle variant.

### Changed
-

### Fixed

- Keep `processkit supervise` setup best-effort when looking up or invoking
  `reconfigure` on a non-standard output stream fails; supervision continues
  without line buffering instead of aborting.
- Preserve a fresh `CancelledError` delivered while async completion-order
  iterators drain cancelled slots: both text and bytes iterators still settle
  every slot before re-raising it.
- Report non-`AttributeError` failures while looking up optional `flush` on
  Python tee writers through `sys.unraisablehook`; capture and mirroring
  continue, while missing or non-callable `flush` remains optional.
- Keep CLI output-loss termination at exit code 119 when even looking up
  `sys.stderr.write` fails; emergency diagnostics remain best-effort.
- Reject HTTP responses whose status token is not exactly three ASCII digits
  in `wait_for_http`, even when a custom `expected_status` would accept a
  loosely parsed short or long integer.
- Update the bundled ProcessKit-rs core to 3.3.4 so an unconfirmed timeout,
  cancellation, or pipeline teardown surfaces as `ProcessError` instead of a
  misleading terminal outcome; Windows ConPTY rejects unrepresentable sizes
  and rolls back failed startup, and Windows process-group enumeration errors
  no longer look like clean completion. This retains the restricted/legacy
  Linux cgroup thaw fix included since core 3.3.1.

## [1.5.0] - 2026-08-08

### Added
- Add cumulative whole-tree I/O counters (`ProcessGroupStats.io_read_bytes`
  and `io_write_bytes`) and the optional kernel high-water mark
  `ProcessGroupStats.peak_process_count`. Availability and units remain
  mechanism-dependent: Windows Job Objects report transfer bytes, Linux cgroup
  v2 may report block-layer bytes and task counts, and unsupported measurements
  are exposed as `None` rather than a synthetic zero.
- Add `ProcessGroup.adopt_external(pid)` to bring an already-running external
  process under group signalling and teardown when only its pid is available.
  Adoption captures process identity during the call, never reaps the process
  or exposes its exit status, and documents the Windows, Linux cgroup,
  POSIX-fallback, and BSD support boundaries.
- Add `Command.arg0()`/`configured_arg0`, `Command.merge_stderr_in_pipe()`,
  `Command.stdout_raw_tee()`/`stderr_raw_tee()`, and
  `RunningProcess.stdout_bytes_seen`/`stderr_bytes_seen` — the last remaining
  small binding gaps against the `processkit` core: a Unix-only `argv[0]`
  override (raising `Unsupported` off-Unix), a per-stage `2>&1 |`-equivalent
  pipeline marker, an undecoded byte-exact stdout/stderr tee alongside the
  existing decoded `stdout_tee()`/`stderr_tee()`, and raw pipe byte counters
  alongside the existing `stdout_line_count`/`stderr_line_count`.
- Add partial-tail readiness probes on `RunningProcess` —
  `wait_for_output()`/`await_for_output()` for stdout and
  `wait_for_stderr_output()`/`await_for_stderr_output()` for stderr — which
  match an *un-terminated* prompt (`Password: `, `(y/N) `, a REPL `>>> `) that
  the line-oriented probes can never see, so a PTY or CLI dialog can wait for a
  prompt and answer it over `take_stdin()`. Non-consuming and repeatable, they
  raise `WaitTimeout` on their own deadline without ever killing the child.
- Add `Command.sanitize_vt()`, `stdout_sanitize_vt()`, and
  `stderr_sanitize_vt()` for clean captured and streaming terminal text, plus
  `processkit run --sanitize-vt` for ANSI-free CLI relay output.
- Add a `processkit` console-script entry point
  (`processkit run -- pytest -x`, `processkit doctor`), alongside the
  still-supported `python -m processkit` form, sharing the identical
  exit-code contract.
- Add `ProcessGroup.update_limits(*, max_memory=None, max_processes=None,
  cpu_quota=None)` for full-replacement, synchronous, dynamic adjustment of a
  live group's resource limits without recreating the group.
- Add `Command.rlimit(resource, soft, hard)` for POSIX per-process
  `setrlimit(2)` limits (`RlimitResourceName`: `"cpu"`, `"core"`, `"data"`,
  `"file_size"`, `"no_file"`, `"stack"`), raising `Unsupported` off-POSIX.
- Add `RunningProcess.stdout_json_lines()` for built-in NDJSON line
  streaming — an async iterator that decodes each stdout line as a standalone
  JSON value, the streaming counterpart to `Command.run_json()`/`arun_json()`.
- Add nightly benchmark coverage for PTY relay, lifecycle events,
  completion-order batches, and live Supervisor restart sessions, with
  platform-specific PTY handling documented.
- Add `wait_for_named_pipe()` readiness probing for Windows services, including
  busy-server detection and symmetric `Unsupported` behavior elsewhere.
- Add Linux/Windows child CPU affinity through `Command.cpu_affinity(...)` and
  the `run`/`supervise` CLI `--cpu-affinity` flag.
- Add reuse-safe `process_info()` / `process_is_alive()` helpers for bare pids
  returned by detached launches, supervision, and process groups.
- Add spawn-free `host_containment()` capability reports, the current
  `ProcessGroup.soft_stop_scope` graceful-stop reach, and the same host details
  to human-readable and JSON `doctor` reports.
- Add deterministic cassette secret scrubbing through
  `RecordReplayRunner.record(..., scrub=)` / `replay(..., scrub=)` and the
  overridable `processkit_cassette_scrubber` pytest fixture, backed by
  ProcessKit-rs 3.1.0's symmetric scrub hook.
- Add `--pty` with optional `--pty-cols`/`--pty-rows` to
  `python -m processkit run`, exposing a merged pseudo-terminal output stream
  for tools that require a TTY.
- Add runnable examples for managed PTY sessions, lifecycle events,
  completion-order batches, intentionally detached helpers, shell-free
  pipelines, and hermetic runner/cassette testing seams.
- Expand `python -m processkit run` with fail-loud captured-output limits,
  direct stdout/stderr file redirects, abrupt-parent-death cleanup, and CPU/I/O
  priority controls.
- Expand `python -m processkit supervise` with per-incarnation timeouts and
  resource caps, headless Windows launches, and proactive TCP or HTTP health
  checks. `Supervisor` now accepts the matching `max_memory=`,
  `max_processes=`, and `cpu_quota=` constructor options.
- Add `RunningProcess.stderr_lines()` for stderr-only line streaming and direct
  use with readiness helpers such as `wait_for_line`.
- Add `Command.run_json()` / `arun_json()` with the same typed JSON decoding and
  `InvalidJson` diagnostics as `CliClient`.
- Add a **CLI Runner** link immediately after the Rust version in the Pages
  navigation.
- Add opt-in pseudo-terminal launches with `Command.pty(...)` and live terminal
  resizing through `RunningProcess.resize_pty(...)`. PTY output is a single
  merged stdout stream, and interactive stdin uses the existing writer API.
- Add live `Supervisor.start()` / `astart()` sessions with status snapshots,
  graceful stop, completion waits, and sync/async context management.
- Add `ProcessGroup.stop()` / `astop()` with a `ShutdownReport` describing the
  graceful signal, remaining members, elapsed time, and hard-kill escalation.
- Add `RunningProcess.lifecycle_events()` for one ordered stream containing the
  start pid, stdout/stderr lines, and final `Outcome`, while preserving the
  output-only `output_events()` contract.
- Add Linux disk-I/O scheduling controls through `Command.io_priority(...)`;
  launching a configured command on another platform raises `Unsupported`.
- Add the deliberately uncontained `Command.spawn_detached()` escape hatch and
  pid-only `DetachedChild` for helpers that must outlive their launcher.
- Add repeatable `--env-file PATH` support to the `run` and `supervise` CLI
  commands for docker-style `KEY=VALUE` files with deterministic overrides.
- Add a generated Release notes page to the documentation site, kept in sync
  with this changelog by local and CI drift checks.

### Changed
- Widen `InvalidJson.stdout` from `str` to `str | None`: it is `None` only when
  the exception comes from the new `RunningProcess.stdout_json_lines()`
  streaming iterator, which cannot buffer the full payload, while
  `run_json()`/`arun_json()` still always populate it. Typed consumers should
  narrow the type before use; the full diagnostic remains available through
  `str(exc)` regardless of the source.
- Bump the bundled ProcessKit-rs core to 3.3.0, preserving the existing Python
  API and feature set while bringing upstream fixes for merged-stderr pipe
  teardown, failed PTY-launch cleanup, pipeline pipefail attribution,
  process-identity-safe metrics, and cassette version validation. The upstream
  `ProcessGroupStats` statistics additions are exposed by the binding as
  documented under Added.
- Bump the bundled ProcessKit-rs core to 3.2.0, preserving the existing Python
  API and cancellation defaults while bringing upstream compatibility fixes for
  ConPTY, PTY EOF, readiness, pipelines, environment resolution, and supervision.
- Document and pin idle monitoring per iterator: `stdout_lines()` watches
  stdout activity, while merged-event and stderr-only streams count both pipes.
- Exercise Windows ARM64 in regular and nightly test matrices, and add a
  sharded nightly cargo-mutants signal for the Rust binding layer.

### Fixed
- Reject CR/LF, control, and whitespace characters in a `wait_for_http` host
  before HTTP serialization, preventing header injection.
- Reject CLI resource and restart limit values above their binding widths with
  an argparse usage error before constructing a `ProcessGroup` or `Supervisor`.
- CLI duration, CPU, backoff, and health-check numeric options now reject
  non-finite values before constructing a command or supervisor.
- Keep Nightly hardening actionable: its mutation sandbox now includes the
  changelog required by release-note drift tests, first-run benchmark history
  can initialize its branch without runner-global git identity, the detached
  helper example waits for its process to release Windows resources, and the
  PTY alias/status tests no longer race short-lived incarnations. Resource-capped
  supervision documentation now also reflects the observable contract:
  `status.pid` is unavailable, while `status.started_at` identifies the current
  capture-only incarnation.
- Python writer objects used by decoded and raw output tees now retry partial
  integer `write()` counts to completion without truncating mirrored output;
  `None` and other non-integer return values remain supported and mean the full
  buffer was accepted, while invalid integer counts are reported via
  `sys.unraisablehook`.
- Close the completion hub's socket at the OS level when Python-level cleanup
  raises, preventing pending anyio-on-asyncio reader tasks and socket-resource
  warnings after an awaited operation is cancelled during loop shutdown.
- Deliver the output `python -m processkit` relays itself line by line when its
  own stdout or stderr is a pipe rather than a terminal: the `run` modes that
  re-emit the child's output (`--idle-timeout`, `--output-limit`, `--pty`) and
  the live tee of `supervise`. A piped reader — `| grep`, a log collector, a CI
  step — previously got those lines in ~8 KiB blocks or in one dump when the run
  ended, unlike the inherited-stream default; both paths now match the live
  output `docs/cli.md` describes.
- Block every direct `Command` spawn path under pytest's `no_real_spawn`
  marker, including JSON, async JSON, and deliberately detached launches.
- Preserve completion-hub rearm errors while still attempting every pending
  awaiter cancellation when secondary cleanup fails.
- Let `python -m processkit supervise` run when the parent interpreter has no
  stdout or stderr stream by omitting the unavailable live-output tee.
- Reject an empty key passed through the CLI's `--env` flag with the same usage
  error used for `--env-file` entries.
- Treat every accepted spelling of piped stdout/stderr consistently when
  combining `Command.stdout()` or `stderr()` with PTY mode.
- Prevent a concurrent lifecycle-event finisher from making a still-reportable
  `RunningProcess` appear consumed or letting context-manager teardown become a
  silent no-op.
- Stop `Supervisor` immediately on the first failing `ScriptedRunner.when`
  predicate, including under an unbounded restart policy.
- Accept bracketed IPv6 literals in `wait_for_http` and keep scoped IPv6 hosts
  from being percent-encoded twice between socket and `Host` header forms.
- Prevent the command-line wrapper's own intermediate output (`doctor`, idle
  streaming, diagnostics, and `--profile`) from producing a traceback when a
  pipe closes or another output write fails. A vanished receiver stays silent;
  other write failures use exit code 119.
- Keep async batch result conversion and `CliClient.arun_json()` parsing on the
  Python event-loop thread, and make worker-side error conversion safe during
  interpreter finalization.
- Let `Outcome` and `Finished` pickle payloads be restored without entering the
  Tokio runtime, including from supervisor callbacks and post-fork children.

## [1.4.2] - 2026-07-26

### Added
- New `python -m processkit` exit code **119**, shared by `run`, `supervise`,
  and `doctor`: the command finished, but the wrapper could not deliver its own
  buffered output (a final flush that failed with e.g. `ENOSPC`/`EIO`, or on a
  stream closed underneath the process). It is reported *instead of* the code
  the run would otherwise have returned — including the child's own — because
  that code would claim a complete, faithfully relayed run. A receiver that
  simply went away (`BrokenPipeError`, e.g. `... | head`) is deliberately not
  this case and stays silent, as before. See "Exit codes" and "How the wrapper
  terminates" in `docs/cli.md`.

### Changed
- Migrate the Rust core to **processkit 3.0.0** (a breaking major release;
  `Cargo.toml` now requires `3`, resolved to 3.0.1). The **Python API is
  unchanged**: `OutputEvent`, `OutputEvents` and `RunningProcess.output_events()`
  keep their names, signatures and meaning — the core's rename of those types
  (`OutputEvent` → `ProcessEvent`, `OutputEvents` → `ProcessEvents`,
  `output_events()` → `events()`) stays an internal detail of the binding, and
  its `Error` → `Error`/`ErrorReason` split changes nothing about the exception
  classes or their structured fields. The enabled feature set is unchanged; 3.0's
  optional new surface (the PTY launch mode, Linux I/O priority, PTY window-size
  control, the capture-redaction hook, the flat error classifier) is **not**
  adopted here.

  Two user-visible consequences, both confined to `output_events()`:

  - The merged event stream became the child's whole **lifecycle** in the core,
    so it now also reports process start and exit. Those non-line events are
    **filtered out** rather than yielded as an `OutputEvent` with an empty
    `text` — which would be indistinguishable from a real blank line the child
    printed. `async for ev in proc.output_events()` therefore yields exactly what
    it always did: output lines. What the lifecycle events carry is already
    available: process start is `RunningProcess.pid`, and the exit is what the
    finisher you call afterwards returns.
  - The core now delivers that stream's terminal event only when the run is
    reaped, which means a consumer that drains the stream and *then* finishes
    would deadlock. The documented Python order — iterate fully, then
    `await proc.afinish()` (or `aoutcome()`) — is unaffected: the binding drives
    the run's completion itself once the child is observed to exit, so the
    iterator ends on its own and the finisher afterwards reports that same run.
    One deliberate narrowing comes with it — see the **BREAKING** entry below.
- **BREAKING** — `output()` / `output_bytes()` / `profile()` (and their
  `a`-twins) now raise a `ProcessError` naming `output_events()` once that stream
  has taken the run over, instead of returning the empty captures they used to:
  it consumed stdout, delivered stderr as events, and (since the 3.0 migration
  above) completed the run, so there is nothing left for them to capture or to
  sample. Use `finish()`/`afinish()` (outcome + stderr) or
  `outcome()`/`aoutcome()` instead — those report such a run either way. Code
  that called `output()` after `output_events()` and used the result got an empty
  `stdout`/`stderr` with a real outcome; it now has to read that outcome from a
  finisher.

  The stream takes the run over as soon as it observes the child exit. Iterating
  to the end always reaches that point, but an early `break` can too — out of a
  command that finished while you were reading it. Break out while the child is
  **still running** and nothing has been taken over: the old behaviour stands
  there (empty captures with a real outcome; `profile()` samples the rest of the
  run). Which side of that line a given `break` falls on is a matter of the
  child's timing, not of how the loop is written, so after streaming events reach
  for a finisher rather than a capture verb. See "Interleaved stdout and stderr"
  in `docs/streaming.md`.
- `output_limit(max_bytes=...)` under **`on_overflow="error"`** — and with it the
  `total_bytes` an `OutputTooLarge` reports — now counts the **raw bytes read
  from the child's output pipe** rather than the bytes of the decoded text,
  following the same change in the Rust core. Line terminators (`\n`, or both
  bytes of a CRLF) and bytes that are not valid UTF-8 are charged against the
  ceiling too, so a cap sized against decoded text raises marginally sooner: by
  one byte per line for ordinary UTF-8 output, and by more for CRLF or binary-ish
  output. The **drop modes are unaffected** — `drop_oldest` (the default) and
  `drop_newest` still bound the *retained* output by decoded line content, as
  does `Supervisor`'s `capture_max_bytes=`, whose `capture_on_overflow` defaults
  to `drop_oldest`. Raw stdout captured by `output_bytes()` is never decoded, so
  its cap is unchanged in every mode. No API change; re-check any
  `on_overflow="error"` threshold you sized against decoded text. See "What
  `max_bytes` actually counts" in `docs/commands.md`.
- `Ctrl+C` that interrupts `python -m processkit` outside `run`/`supervise`'s
  own guarded blocks — during startup, argument parsing, or `doctor` — now
  reports the documented `128 + SIGINT` (`130`) with the same one-line
  `processkit: interrupted` message those paths print, instead of ending
  through the interpreter's own unhandled-`KeyboardInterrupt` path. This makes
  the Ctrl+C contract uniform across the entry point and platforms; for
  `doctor` it also keeps an interrupted run
  distinguishable from its valid `1` verdict ("containment enforced, limits
  not").

### Fixed
- Fix an intermittent SIGSEGV at interpreter exit after a program's final
  processkit `await`. The async bridge no longer completes Python Futures from
  a detached tokio thread through `call_soon_threadsafe`; tokio stores the
  outcome and wakes one shared `loop.sock_recv` dispatcher per event loop, then
  the event-loop thread converts and resolves it. Repeated stream steps reuse
  that socket, and the dispatcher closes it after the loop becomes idle rather
  than leaving a pending receive behind at loop teardown. A short-lived script
  can now end immediately after any `a`-prefixed verb without racing
  `Py_FinalizeEx`. This also restores ordinary interpreter finalization for
  `python -m processkit` — including `atexit` hooks and finalizers — instead of
  the temporary `os._exit` workaround.

## [1.4.1] - 2026-07-24

### Added
- Add `CliClient.run_json(call)` / `arun_json(call)`: run a wrapped tool like
  `run` (requiring a zero exit) and return its stdout **parsed as JSON** — the
  `run(...)` + `json.loads(...)` + error-mapping boilerplate the many CLIs that
  emit machine JSON (`gh`, `kubectl`, `docker`, `az`, `jj`) otherwise force on
  every caller. Stdout that does not parse raises a new `InvalidJson` exception
  (a `ProcessError` carrying the client's `program` and a bounded stdout
  fragment, with the parser message in `str(exc)`) instead of a bare,
  unattributed `json.JSONDecodeError`; a non-zero exit still raises `NonZeroExit`
  as `run` does. Both verbs go through the same `default_env_fn`/`when`-capture
  pipeline and injectable `runner=` seam as the other `CliClient` verbs, so they
  are hermetically testable with a `ScriptedRunner` and no real process.
- Add `Command.idle_timeout(seconds)`, an inactivity timeout that tears the
  child down if it produces no stdout/stderr line for that long — for the
  "hung tool" case a wall-clock `timeout()` handles poorly, where a legitimately
  long job keeps printing progress. It fires as a new, distinct `IdleTimeout`
  exception (a `ProcessError` sibling of `Timeout`, carrying
  `idle_timeout_seconds`), deliberately **not** the wall-clock
  `timed_out`/`Timeout` signal, so the two timeout classes stay tellable apart
  and the existing captured `timed_out` contract is untouched. Enforced on the
  streaming/interactive surface (`start()`/`astart()` +
  `stdout_lines()`/`output_events()`), where the binding drives the per-line
  output channel; a redirected/inherited stdout is diagnosed by the existing
  "stdout is not piped" error rather than silently un-watched. **Scope note:**
  the one-shot capture verbs (`output`/`run`/`exit_code`/`probe` and their
  `a`-twins), `Pipeline`, and `Supervisor` do not enforce it — processkit
  2.3.x has no native idle-timeout to observe per-line activity mid-run through
  those paths, so honoring it there awaits upstream crate support; the setting
  is carried on the command regardless.
- Add `python -m processkit run --idle-timeout SECONDS`: kills the child and
  exits **123** (distinct from `--timeout`'s 124) if it produces no output line
  for that long. Because idle monitoring rides the per-line channel, this flag
  pipes and re-emits the child's stdout/stderr (decoded, one line at a time)
  instead of inheriting them raw, and is incompatible with `--profile`. The
  flag is also present on `supervise` for parity but is a usage error there
  until upstream `Supervisor` idle-timeout support lands (its incarnations run
  through one-shot verbs the idle watchdog cannot observe).

### Changed
-

### Fixed
- `wait_for_http` now forms a correct HTTP/1.1 request line for edge-case
  `host`/`path` values: an IPv6 literal `host` (e.g. `"::1"`) is bracketed in
  the `Host` header per RFC 9112/3986 (`Host: [::1]:8080`, not the previously
  ambiguous `Host: ::1:8080`), and a `path` containing whitespace, a control
  character (including CR/LF — previously a header-injection-shaped hazard),
  or a character outside latin-1 now raises `ValueError` up front, before any
  connection is attempted, instead of silently corrupting the request line or
  raising a raw `UnicodeEncodeError`.

## [1.4.0] - 2026-07-23

### Added
- Add an actionlint CI gate for semantic GitHub Actions and shell-script checks
- Add the `supervise` CLI subcommand with restart-policy and backoff flags.
- Add `wait_for_http(host, port, path="/", *, timeout, interval=0.05,
  expected_status=None)`, a readiness helper that polls an HTTP endpoint (a
  hand-rolled GET over asyncio streams, no new dependency) and succeeds only on
  an accepted status code (any 2xx by default; a set/range or a predicate
  overrides) — a stronger signal than `wait_for_port` for a server that accepts
  connections while still warming up
- Add `aoutput_as_completed`/`aoutput_as_completed_bytes`, the streaming
  counterpart to the `aoutput_all` family: an async iterator that yields each
  `(index, result)` pair as its command finishes rather than waiting for the
  whole batch, with the same hard concurrency cap and no-orphan teardown on
  cancellation or early exit
- Add `python -m processkit run --profile [FILE]`, emitting a one-line JSON
  resource profile (duration, CPU time, peak memory, average CPU cores,
  sample count, exit code/signal, timed-out flag) after the child exits — to
  stderr if `FILE` is omitted, or written to `FILE` otherwise
- Add `python -m processkit run --create-no-window`, applying
  `Command.create_no_window()` to the child so the wrapper does not create a
  console window on Windows — a no-op outside Windows (same as the
  underlying binding method)
- Add `Command.stdout_file()` / `stderr_file()`, spawn-time direct-redirect
  sinks that send a stream straight to a file with no parent-side pump or
  capture in between (`append=False`, the default, truncates the file on each
  spawn; `append=True` appends — e.g. a shared log across `Supervisor`
  incarnations or `retry()` attempts). A file-redirected stdout makes
  `output()` / `run()` / `output_bytes()` (and their async twins) raise the
  usual "not piped" `ProcessError`, but `exit_code()` / `probe()` still work
  since they never touch the stdout pipe; a file-redirected stderr leaves
  `output()` working, with `result.stderr` coming back empty
- Add `ProcessGroup.members_info()` / `MemberInfo`, an enriched process-tree
  snapshot alongside `members()`: each pid comes with best-effort
  `ppid`/`exe_name`/`start_time` metadata (`None` wherever the platform can't
  report it). `exe_name` is a short image name, not a path, and `start_time`
  is an opaque, platform-specific identity token, not wall-clock — its sole
  use is pairing with `pid` across two snapshots to tell a recycled pid apart
  from the original
- Add `Command.windows_graceful_ctrl_break()`, an opt-in Windows-only graceful
  shutdown: at a graceful timeout (`timeout_grace`) or a group shutdown it
  sends the direct console child a `CTRL_BREAK` before the hard
  `TerminateJobObject` fallback, giving a child that handles it a chance to
  exit cleanly first. Console-only (inert under `create_no_window` /
  detached) and a harmless no-op outside Windows
- Add opt-in `Supervisor` liveness health checks via three new keyword-only
  constructor parameters: `health_check` (a synchronous `() -> bool`
  callable), `health_check_interval` (required alongside it), and
  `health_check_failures`. After `health_check_failures` consecutive probe
  failures the supervisor force-restarts the run; each force-restart
  increments the new `SupervisionOutcome.liveness_kills` counter, and the
  final such stop under `restart="never"` reports `SupervisionOutcome.stopped
  == "unhealthy"`
- Add `Command.kill_on_parent_death_scope()`, a read-only capability query
  reporting the scope of parent-death cleanup the current platform actually
  achieves when the owner dies abruptly, as a string: `"whole_tree"` on Windows
  (the Job Object reaps the whole tree on owner death), `"direct_child_only"`
  on Linux (`PR_SET_PDEATHSIG` reaches only the direct child; grandchildren
  survive), or `"unsupported"` on macOS/BSD (no `pdeathsig` equivalent). A
  static query fixed at build time — read it off the class or any instance,
  with no prior `kill_on_parent_death()` call — so a caller can state the real
  reach of the best-effort hardening instead of overpromising a whole-tree
  guarantee the OS cannot keep

### Changed
- Refresh the GitHub Pages landing page from the README: its cover, status
  badges, no-orphan introduction, runnable example, and capability summary now
  appear before the guide index.
- Bump the processkit dependency to 2.3.1 (lockfile pinned via `cargo update -p
  processkit --precise 2.3.1`; the Cargo.toml requirement stays at the broad
  `2.3` range). 2.3.1 also added new upstream public surface (Command
  stdout/stderr file-redirect sinks, `windows_graceful_ctrl_break`,
  `ProcessGroup::members_info`/`MemberInfo`, `Supervisor` liveness health
  checks) that this binding has since adopted — see the `Added` entries above.
- Bump the processkit dependency to 2.3.2 (lockfile pinned via `cargo update -p
  processkit --precise 2.3.2`; the Cargo.toml requirement stays at the broad
  `2.3` range). 2.3.2 adds new upstream public surface
  (`Command::kill_on_parent_death_scope` and the `ParentDeathCleanup` enum it
  returns) that this binding adopts — see the `Added` entry above.

### Fixed
- Correct the pipeline documentation to describe per-stage kill-on-drop
  sub-groups, chain-wide teardown fan-out, and composite timeout attribution,
  matching the processkit 2.3.x core.
- Fix rendered mdBook links that pointed at the nonexistent `README.html`,
  correct the uvloop section anchor, and align contributor/release instructions
  with the current mdBook-to-GitHub-Pages workflow.
- Make the documented `just` recipes run on Windows by selecting PowerShell 7
  instead of relying on an unavailable `sh` executable.

## [1.3.0] - 2026-07-19

### Added
- Add `sample_stats(group, every)`, a pure-Python async generator for live
  `ProcessGroup` monitoring: a fused, periodic series of `ProcessGroupStats`
  snapshots built on top of `ProcessGroup.stats()`

## [1.2.4] - 2026-07-12

### Added
- Add Open Graph and Twitter Card metadata to the docs site
- Add real Rust crate and .NET documentation links
- Add table border, header fill, and row striping to match the reference site

### Changed
- Publish the documentation site to GitHub Pages on push to main
- Pin the GitHub Pages deploy actions to a commit SHA
- Reserve navigation placeholders for the Rust crate and .NET variant
- Restyle the docs site navigation and tables to match the ProcessKit look
- Move the Rust crate and .NET nav entries right after Home, then link them
  directly to their docs sites
- Match the reference site's pinned nav-group title styling, typography, CSS,
  and table borders/header fill/row striping/dark-theme colors (navy, not
  coal) more closely
- Move the implementation switcher above Home, then the Rust/Python/.NET
  version switcher above Overview, in the docs nav
- Rebuild the docs site with mdBook to match the ProcessKit family
- Render API-reference signatures as text and fix the generator's griffe types
- Give a clear diagnostic for `parse_signal` with out-of-range ints and
  floats, and align the property test with the corrected diagnostic
- Convert `Supervisor` to the frozen + `Mutex<Option<...>>` pattern
- Unify the named-preset parsers (and their property tests) on
  case-insensitive matching
- Bump the processkit dependency to 2.2.4

### Fixed
- Fix wide-table scrolling specificity and code word-breaking
- Fix doc comment list-bullet misparse and reformat long test line

### Removed
- Drop the external crates.io link from the Rust crate placeholder
- Remove stray trailing blank line from mkdocs.yml

## [1.2.3] - 2026-07-11

### Changed
- Bump the processkit dependency to 2.2.3

### Fixed
- Fix broken repo-relative README links for PyPI rendering

## [1.2.2] - 2026-07-10

### Changed
- `ProcessResult` and `SupervisionOutcome` are no longer picklable — pickling
  either now raises `TypeError` (they were advertised as picklable in 1.2.0).
  Their equality is the underlying `processkit` crate's own comparison, which
  also spans a command's configured `timeout` and accepted `success_codes` —
  two fields the crate exposes through no accessor. A pickle could not read them
  back to reconstruct them, so a result from a command that set `.timeout(...)`
  or `.success_codes(...)` unpickled **unequal** to its original (identical
  visible fields and `hash()`, but `!=`), silently breaking the round-trip
  invariant a picklable value type promises. Rather than hand back a
  subtly-wrong value, both refuse loudly, matching `BytesResult`/`RunProfile`.
  `Outcome` and `Finished` remain picklable and round-trip **exactly** (an
  `Outcome` is fully determined by its Python-visible `code`/`signal`/
  `timed_out`; a `Finished` adds only its `stderr`). To move a captured result
  across a process boundary — e.g. back from a
  `concurrent.futures.ProcessPoolExecutor` worker — pickle `result.outcome`
  (an `Outcome`), or persist `result.stdout`/`.stderr`/`.code` yourself.

### Fixed
- `CancellationToken`'s docstring (Rust doc comment and the `.pyi` stub) no
  longer claims that a `child_token()` shares the same cancellation state as
  its parent and siblings. The actual, already-tested behavior is
  parent-to-child only: a parent cancels its children, but cancelling a
  child never affects the parent or its other children.
- `processkit.__version__` now matches its own docstring: the first access
  computes it via `importlib.metadata.version()` and caches the result
  (including the source-tree `"unknown"` outcome) for every later access,
  instead of re-scanning package metadata on every read. The first access is
  single-flight even under concurrent readers on a free-threaded build.
- `CliClient` `default_env_fn` resolvers are now fail-closed: a resolver that
  raises or returns a non-`str` aborts the triggering `command()`/verb with that
  exception, *before* the runner is reached, so no process is spawned. Previously
  the failure was only reported via the unraisable hook and the resolved value
  fell back to an empty string — running the command with a silently-missing
  credential. Applies uniformly to `command()`, the sync verbs, and the async
  verbs; a resolver whose key is already set by an explicit per-command `env()`
  or a static `default_env` still never runs (and so cannot abort the call).

## [1.2.1] - 2026-07-09

### Added
- Add `Command.prefer_local`, exposing crate 2.2's bare-name resolution override
- Add a runnable `Command.prefer_local` usage example to `docs/commands.md`
- Add `ProcessStdin.send_control` for interactive control-byte delivery

### Changed
- Broaden the `Command.priority` docstring privilege caveat to cover
  `above_normal` and a niced-parent `normal`
- Bump the processkit dependency requirement and lockfile to 2.2.0
- Apply rustfmt to the `send_control` signature
- Bump the processkit dependency to 2.2.1

### Fixed
- Fix Windows-incompatible relative path-form assertion in the prefer_local example

## [1.2.0] - 2026-07-08

### Added
- `Command.stdout_tee` / `Command.stderr_tee` now accept a **Python writer**
  object (anything with a callable `write()` — `io.StringIO`, `sys.stderr`, a
  text-mode file, a logger wrapper) in addition to a file path, mirroring the
  child's output straight into your own console/buffer/logger while still
  capturing it. Each decoded line (plus a `"\n"`) is passed to `write()` as a
  `str` via an async-write bridge: every write is dispatched to the runtime's
  blocking pool (re-acquiring the GIL there) and awaited on the capture pump, so
  a slow — even sleeping — `write()` applies backpressure without blocking the
  event loop or deadlocking the runtime. The object is discriminated from a path
  by exposing `write` (neither `str` nor `pathlib.Path` does) and is never closed
  for you; `append=True` is meaningful only for a file path and raises
  `ValueError` if combined with a writer. A `write()` exception disables the tee
  for the rest of the run (a `tracing` warning under `enable_logging()`, the same
  isolation as the file tee) and is additionally reported via `sys.unraisablehook`
  — the run and its captured result are unaffected. The previous "a file path
  only, an arbitrary Python writer is deliberately not supported" restriction is
  lifted. See `docs/streaming.md#tee-output-to-a-file`.
- `Command.on_stdout_line(callback)` / `Command.on_stderr_line(callback)`: a
  `Callable[[str], None]` invoked with every decoded line as it is produced —
  the way to give the **synchronous** surface (`.output()`/`.run()`) live
  progress observation during an otherwise-blocking call, without losing the
  full capture. Also fires on the async verbs and on a streamed run
  (`start()`/`astart()` + `stdout_lines()`/`output_events()`); at most one
  handler per stream (a repeat call replaces the previous one); a raising
  callback is reported via `sys.unraisablehook` rather than propagated or
  breaking the run. Inert under `stdout("inherit")`/`stdout("null")` (resp.
  `stderr(...)`) and, for `on_stdout_line` only, under `output_bytes()` (which
  captures stdout raw, bypassing the line pump — stderr still goes through it,
  so `on_stderr_line` still fires there). See
  `docs/streaming.md#live-per-line-callbacks`.
- A `benchmarks/` suite (`pytest-benchmark`, new `bench` dependency-group)
  measuring spawn+capture overhead against `subprocess`/`asyncio.subprocess`,
  `ProcessGroup` start/exit, line-streaming throughput, and `output_all`
  concurrency scaling — dev tooling only, no public API change. Runs nightly
  via the `bench` job in `nightly-hardening.yml`, never in the PR gate; see
  `benchmarks/README.md`.
- `wait_for_path(path, *, timeout, interval=0.05)` — a new async readiness
  helper alongside `wait_until` / `wait_for_port` / `wait_for_line`, polling
  until a filesystem path appears (a unix socket, a pid file, or any other
  marker a daemon creates once ready). Same timeout/interval discipline as its
  siblings (NaN/negative `timeout` and non-positive `interval` raise
  `ValueError`; `timeout=0` still checks the path at least once) and raises
  `WaitTimeout` (also a `TimeoutError`) on expiry, now carrying a `path` field
  (`WaitTimeout.__init__` gained a `path: StrPath | None = None` parameter).
- `python -m processkit run -- <cmd> [args...]`: a CLI wrapper that runs a
  command inside a kill-on-exit `ProcessGroup` with inherited stdio, for
  shell scripts and CI steps with no Python to write. Supports `--timeout`,
  `--timeout-grace`, `--max-memory`, `--max-processes`, and `--cpu-quota`;
  the child's own exit code is passed through unchanged,
  and a timeout / missing program / rejected resource limit is reported as a
  one-line stderr message with a documented, GNU-`timeout`-style exit code
  instead of a traceback. See `docs/cli.md`.
- `Finished` gains `timed_out` and `signal` properties that delegate to the
  nested `outcome`, so it now mirrors `Outcome` fully — matching `code` and
  `exited_zero`, which were already exposed directly — instead of requiring
  `finished.outcome.timed_out` / `finished.outcome.signal`.
- `Command.stdin_file(path)` — feed the child's stdin from a file, streamed in
  chunks by the crate rather than read whole into a Python `bytes` object, for
  large inputs (a `psql` dump, a `tar` archive, a multi-gigabyte log). Like
  most other builder methods (`stdout_tee`/`stderr_tee` are the deliberate
  exception), it does not touch the filesystem at build time — the path is
  opened lazily at spawn, so a missing/unreadable file surfaces as the generic
  `ProcessError` from the run/output verb, not `FileNotFoundError`. Reusable
  across retries/re-runs, like `stdin_bytes`/`stdin_text`; the usual "last
  stdin method wins" rule applies alongside `stdin_bytes()`/`stdin_text()`/
  `keep_stdin_open()`.
- `ProcessResult` and `BytesResult` gain `diagnostic: str | None` (stderr if it
  carries text, otherwise stdout, otherwise `None` — the same preference order
  as `NonZeroExit`/`Timeout`/`Signalled.diagnostic` on the exceptions) and
  `outcome: Outcome` (the same value `RunProfile.outcome` and the checking-verb
  exceptions expose). A result held as data (`output()`/`output_bytes()`
  without `ensure_success()`) no longer requires re-deriving these by hand.
  (An `output_contains_any` convenience was considered alongside these and
  rejected: the underlying `processkit` crate has no such method, so it
  wouldn't be parity with the crate or the exceptions like `diagnostic`/
  `outcome` are — and it's a one-liner callers can already write themselves
  via `combined`, e.g. `any(s in result.combined for s in needles)`.)
- Value semantics for the result types: `ProcessResult`, `BytesResult`,
  `Outcome`, `Finished`, `RunProfile`, and `SupervisionOutcome` now define
  `__eq__` (comparing every field the underlying `processkit` crate's own
  `PartialEq` compares — not `object`'s previous identity comparison) and a
  consistent `__hash__` (none of their fields are stored floats, so hashing is
  sound), so two results can now be compared with `==` and used in a `set` or
  as a `dict` key without a manual field-by-field comparison.
  `ProcessResult`/`Outcome`/`Finished`/`SupervisionOutcome` are also picklable
  — e.g. to return a `ProcessResult` from a
  `concurrent.futures.ProcessPoolExecutor` worker. The underlying crate has no
  public constructor for any of these types, so unpickling reconstructs one via
  `processkit.testing.ScriptedRunner` (an in-memory, no-subprocess replay) —
  faithful for every field the Python binding exposes, but a command that
  customized `success_codes()`/`timeout()` is not guaranteed to compare `==`
  its original after a round trip (those two fields have no Python accessor to
  reconstruct exactly). `BytesResult` (raw stdout may not be valid UTF-8, and
  the only reconstruction channel available is text-only) and `RunProfile`
  (reports live OS resource-sampling telemetry with no synthesis path outside
  an actual monitored run) explicitly do **not** support pickling and raise a
  clear `TypeError` rather than failing silently or fabricating the missing
  data.

### Changed
- `CliClient(default_env_fn=...)` now validates that every value in the
  mapping is callable **at construction time**, raising `TypeError` (naming
  the offending key) immediately instead of silently accepting a non-callable
  value and only discovering the mistake later — once per built command, as
  an unraisable-hook warning plus an always-empty resolved env var. Valid
  callables behave exactly as before.

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
- Pipeline timeout results now retain best-effort partial stdout and stderr
  captured by the last stage before the deadline.
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

[Unreleased]: https://github.com/ZelAnton/processkit-py/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/ZelAnton/processkit-py/compare/v1.4.2...v1.5.0
[1.4.2]: https://github.com/ZelAnton/processkit-py/compare/v1.4.1...v1.4.2
[1.4.1]: https://github.com/ZelAnton/processkit-py/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/ZelAnton/processkit-py/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/ZelAnton/processkit-py/compare/v1.2.4...v1.3.0
[1.2.4]: https://github.com/ZelAnton/processkit-py/compare/v1.2.3...v1.2.4
[1.2.3]: https://github.com/ZelAnton/processkit-py/compare/v1.2.2...v1.2.3
[1.2.2]: https://github.com/ZelAnton/processkit-py/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/ZelAnton/processkit-py/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/ZelAnton/processkit-py/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/ZelAnton/processkit-py/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/ZelAnton/processkit-py/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ZelAnton/processkit-py/releases/tag/v1.0.0
