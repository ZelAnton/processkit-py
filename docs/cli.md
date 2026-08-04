# Command-line usage

[‹ docs index](./)

Most of this package's value lives behind Python code — but sometimes the
caller is a shell script or a CI step, not a Python program. `python -m
processkit run` is a thin CLI wrapper over `Command` / `ProcessGroup` for
exactly that case: kill-on-exit containment and resource limits for a single
shell command, with no Python to write. `python -m processkit supervise`
exposes restart-based keep-alive supervision (`Supervisor`) the same way, and
`python -m processkit doctor` is `run`'s read-only companion: a preflight
diagnosis of what this environment's kernel actually grants, without running
anything (see [below](#doctor-preflight-diagnose-the-environment)).

After `pip install processkit-py`, the same wrapper is also on `PATH` as the
short `processkit` command — `processkit run -- pytest -x` and `processkit
doctor` work exactly like their `python -m processkit ...` equivalents below,
sharing the identical flag set and exit-code contract (both forms delegate to
the same entry point). `python -m processkit` remains fully supported and is
what the rest of this page uses throughout — reach for it explicitly when
several interpreters are on the machine and the `processkit` command on
`PATH` might not be the one you mean.

- [Basic usage](#basic-usage)
- [Flags](#flags)
- [`--profile`: machine-readable resource usage](#--profile-machine-readable-resource-usage)
- [Exit codes](#exit-codes)
- [supervise](#supervise)
- [Resource limits: hard cap or best effort?](#resource-limits-hard-cap-or-best-effort)
- [`doctor`: preflight-diagnose the environment](#doctor-preflight-diagnose-the-environment)
- [What you don't get here](#what-you-dont-get-here)

## Basic usage

```bash
python -m processkit run -- pytest -x
# or, once installed, the shorter console script (identical behavior):
processkit run -- pytest -x
```

Everything after the **first** `--` is the child's own argv, untouched — a
second `--` in there belongs to the child, not to this wrapper:

```bash
python -m processkit run -- git log -- README.md
#                          ^ separator            ^ the child's own "--"
```

The child runs inside a `ProcessGroup`: even for one command, its whole
process tree — every grandchild it forks — is torn down when this wrapper
exits, and by default its stdin/stdout/stderr are inherited straight through
to your terminal: the child reads from the same stdin and its output is live,
not buffered up and dumped at the end. Output-control flags below deliberately
replace that default for the selected streams.

```bash
# Bound the whole run to 30 seconds.
python -m processkit run --timeout 30 -- pytest -x

# Cap memory and process count too (needs a real container — see below).
python -m processkit run --max-memory 536870912 --max-processes 64 -- ./build.sh
```

## Flags

| Flag | Maps to | Notes |
|---|---|---|
| `--timeout SECONDS` | `Command.timeout(seconds)` | Kills the whole tree once the deadline passes. |
| `--timeout-grace SECONDS` | `Command.timeout_grace(seconds)` | Signal first, hard-kill after `SECONDS`. Requires `--timeout`; a usage error otherwise. |
| `--idle-timeout SECONDS` | `Command.idle_timeout(seconds)` | Kill the child if it emits no output line for `SECONDS`. Exit `123` (distinct from `--timeout`'s `124`). Pipes and re-emits stdout/stderr line-by-line; incompatible with `--profile` and `--stdout-file`. See [below](#--idle-timeout-a-silence-watchdog). |
| `--max-memory BYTES` | `ProcessGroup(max_memory=...)` | Whole-tree memory cap. |
| `--max-processes N` | `ProcessGroup(max_processes=...)` | Fork-bomb ceiling for the tree. |
| `--cpu-quota FLOAT` | `ProcessGroup(cpu_quota=...)` | Fraction of a **single** core (`0.5` = half, `2.0` = two cores). |
| `--env-clear` | `Command.env_clear()` | Start the child with an empty environment. |
| `--inherit-env NAME` | `Command.inherit_env([...])` | Allow-list a parent variable through (implies `--env-clear`). Repeatable. |
| `--env-file PATH` | Repeated `Command.env(key, value)` | Load docker-style `KEY=VALUE` lines. Blank lines and lines beginning with `#` are ignored. Repeatable. |
| `--env KEY=VALUE` | `Command.env(key, value)` | Set/override a child environment variable. Repeatable. A value without `=` is a usage error. |
| `--cwd DIR` | `Command.cwd(dir)` | Run the child with `DIR` as its working directory. |
| `--profile [FILE]` | `RunningProcess.profile(...)` | After the child exits, emit a JSON resource profile — to stderr if `FILE` is omitted, or written to `FILE` otherwise. See [below](#--profile-machine-readable-resource-usage). |
| `--create-no-window` | `Command.create_no_window()` | Do not create a console window for the child. No-op outside Windows (same as the underlying binding method). |
| `--output-limit BYTES` | `Command.output_limit(max_bytes=..., on_overflow="error")` | Pipe and re-emit output line-by-line, failing with `125` if captured stdout/stderr exceeds the raw-byte ceiling. Incompatible with `--profile` and `--stdout-file`. |
| `--stdout-file PATH` | `Command.stdout_file(path)` | Redirect stdout directly to a newly created or truncated file. |
| `--stderr-file PATH` | `Command.stderr_file(path)` | Redirect stderr directly to a newly created or truncated file. |
| `--kill-on-parent-death` | `Command.kill_on_parent_death()` | Best-effort abrupt-owner-death cleanup; platform scope is unchanged from the API. |
| `--priority LEVEL` | `Command.priority(level)` | CPU priority: `idle`, `below_normal`, `normal`, `above_normal`, or `high`. |
| `--io-priority CLASS[:LEVEL]` | `Command.io_priority(...)` | Linux I/O priority: `idle`, `best_effort:0..7`, or `real_time:0..7`; unsupported elsewhere. |
| `--cpu-affinity CPU[,CPU...]` | `Command.cpu_affinity([...])` | Pin the child tree to logical CPUs on Linux/Windows; unsupported elsewhere. |
| `--pty` | `Command.pty(...)` | Allocate a pseudo-terminal and relay its one merged terminal stream on stdout. The child does not inherit the wrapper's stdin; use the Python API for an interactive writer. |
| `--pty-cols N` / `--pty-rows N` | `Command.pty(cols=..., rows=...)` | Initial terminal size. Requires `--pty`; provide both dimensions together. |

Every numeric flag rejects zero and negative values at the argument-parsing
stage (a usage error, not a traceback). See `docs/process-groups.md` and
`docs/commands.md` for what each underlying builder method does in full —
including how the environment builders (`env_clear` / `inherit_env` / `env`)
compose regardless of call order. CLI environment layers have a fixed
precedence: the inherited base (or `--env-clear`), then `--inherit-env`, then
`--env-file` values in file/argument order, then explicit `--env` flags. A later
entry in the same layer wins; explicit flags therefore override every file.
Files are UTF-8 (an optional BOM is accepted); values are literal and may contain
additional `=` characters. Missing/unreadable files and non-comment lines
without `=` are usage errors with the file and line number, never tracebacks.

### `--profile`: machine-readable resource usage

Without `--profile`, `run` only ever reports an exit code — the resource side
of the run (wall time, CPU time, peak memory) is invisible from the CLI, even
though the binding already tracks it end-to-end (`RunningProcess.profile()` /
`RunProfile`, see [Streaming & interactive
I/O](streaming.md#live-introspection-and-per-run-telemetry)). `--profile`
exposes exactly that, for a CI step that wants a machine-readable resource
accounting of a containerized run without writing any Python:

```bash
# Print the profile to stderr once the child exits.
python -m processkit run --profile -- pytest -x

# Or write it to a file instead.
python -m processkit run --profile /tmp/run-profile.json -- pytest -x
```

Either way, the child's own stdin/stdout/stderr are still inherited straight
through exactly as without the flag — the profile is only ever emitted
**after** the child has fully exited (the same point `outcome()` itself
returns at), so it never interleaves with the child's own output. It is one
line of JSON with these fields:

| Field | Type | Meaning |
|---|---|---|
| `duration_seconds` | `float` | Wall-clock time the run took. |
| `cpu_time_seconds` | `float \| null` | User + kernel CPU time consumed by the whole run. |
| `peak_memory_bytes` | `int \| null` | Peak memory observed during the run. |
| `avg_cpu_cores` | `float \| null` | `cpu_time_seconds / duration_seconds` — e.g. `1.7` means ~1.7 cores kept busy on average. |
| `samples` | `int` | How many resource samples were taken while the child ran. |
| `code` | `int \| null` | Same meaning as the process's own exit code (`null` if the run ended some other way). |
| `signal` | `int \| null` | Set if the child was killed by a signal (POSIX only). |
| `timed_out` | `bool` | Whether `--timeout` expired. |

The `cpu_time_seconds` / `peak_memory_bytes` / `avg_cpu_cores` fields need the
same kernel-level accounting `ProcessGroup`'s own resource limits do (a
Windows Job Object or a Linux cgroup-v2 root — see [Resource limits: hard cap
or best effort?](#resource-limits-hard-cap-or-best-effort) above); where the
environment doesn't grant that, they serialize as JSON `null` rather than
failing the run — `duration_seconds`/`samples`/`code`/`signal`/`timed_out` are
always available. `--profile`'s own exit-code contract is otherwise unchanged
from the table above — it never introduces a new exit code, and a failure
writing the profile to `FILE` (e.g. an unwritable path) surfaces as the
existing internal-failure code `125`, with a one-line message on stderr.

### `--idle-timeout`: a silence watchdog

`--idle-timeout SECONDS` maps to `Command.idle_timeout(seconds)` — it kills the
child if it produces no output line for that long, for a tool that hangs
silently while a healthy long job keeps printing. It exits **123**, deliberately
distinct from `--timeout`'s `124`, so the two timeout classes stay tellable
apart by exit code.

```bash
# Kill the build if it goes quiet for 30s, even though its total budget is high.
python -m processkit run --timeout 3600 --idle-timeout 30 -- ./flaky-build
```

Idle monitoring needs the per-line output channel, so with this flag `run`
**pipes** the child's stdout/stderr and re-emits each decoded line (one at a
time, with a trailing newline) instead of inheriting the raw streams. That is a
deliberate fidelity trade taken only when the flag is set: output is UTF-8
decoded and line-framed, and the child's streams are not a TTY. For the same
reason `--idle-timeout` is **incompatible with `--profile`** (they need
different consuming operations on the one handle) — combining them is a usage
error. It is also incompatible with `--stdout-file`, because streaming requires
a piped stdout; redirect stderr instead when stdout activity alone is a useful
silence signal.

`--output-limit` uses that same line pump without adding an idle deadline. Its
`on_overflow="error"` policy counts raw bytes read from both pipes, kills the
run when the cap is crossed, and reports the existing internal-failure exit
code `125`; output beyond the ceiling is never relayed. Direct `--stdout-file`
redirection has no stdout pipe to monitor, so combining it with
`--output-limit` is a usage error. `--stderr-file` remains compatible: stderr
goes directly to the file and the ceiling applies to the still-captured stdout.

`--pty` also uses the line pump, but the source is a real pseudo-terminal: tools
that require `isatty()` see a terminal and stdout/stderr arrive as one merged
stream on the wrapper's stdout. Optional dimensions must be supplied together.
PTY owns the child's stdio, so direct file redirects and `--profile` are usage
errors; `--output-limit`, idle/wall-clock timeouts, resource limits, and
`--create-no-window` keep their normal semantics. This CLI mode is intended for
non-interactive TTY-sensitive tools and does not forward the wrapper's stdin;
use `Command.pty().keep_stdin_open()` plus `take_stdin()` for interactive input.
If the platform cannot allocate a PTY, the request fails through the existing
`Unsupported`/internal-error path (`125`) rather than silently using pipes.

`--idle-timeout` is **not** available under `supervise`: each supervised
incarnation runs through `Supervisor`'s one-shot verbs, which processkit's core
gives no idle-timeout hook, so passing it there is a usage error until upstream
support lands. Use `run --idle-timeout` for a single command.

## Exit codes

This wrapper's own exit code mirrors the child's — plus a small set of
reserved codes for cases where there is no child exit code to report,
following the same convention GNU coreutils' `timeout` and POSIX shells use:

| Exit code | Meaning |
|---|---|
| *(the child's own code)* | Normal completion — passed through unchanged. |
| `119` | This wrapper could not deliver its own buffered output (see [How the wrapper terminates](#how-the-wrapper-terminates)). Shared by every subcommand. |
| `123` | `--idle-timeout` expired; the child produced no output line in time and was killed. Distinct from `124`. |
| `124` | `--timeout` expired; the tree was killed. |
| `125` | An internal / containment failure (see below). |
| `126` | The program was found but could not be executed. |
| `127` | The program could not be found. |
| `128 + N` | The child was killed by signal `N` (POSIX only). |
| `128 + SIGINT` (`130`) | `python -m processkit` itself was interrupted (Ctrl+C) — anywhere, including during startup, argument parsing, or `doctor`. |

None of these ever surface as a raw Python traceback — every documented
processkit exception (`Timeout`, `Signalled`, `ProcessNotFound`,
`PermissionDenied`, `ResourceLimit`, `Unsupported`) is caught and turned into
one of the codes above, with a one-line message on stderr. Ctrl+C is part of
that promise too: it always ends as `128 + SIGINT` with a single
`processkit: interrupted` line, never a `KeyboardInterrupt` traceback.

### How the wrapper terminates

`python -m processkit` flushes its own stdout/stderr, raises `SystemExit` with
the selected code, and then runs ordinary interpreter finalization (`atexit`
hooks, garbage-collected finalizers, and module teardown included).

`--idle-timeout` is the one path that drives the async surface. Its completion
handoff wakes the event loop through a socket and resolves the Future on the
loop thread, so no detached tokio thread remains inside Python after the await
resumes; normal finalization cannot race the bridge. See
[Async runtimes & event loops](event-loops.md#interpreter-shutdown-and-the-async-bridge).

Two exit duties remain explicit so their outcomes stay part of the CLI's
documented contract rather than depending on CPython's fallback behavior:

- **The final flush of its own stdout/stderr.** Redirected into a pipe,
  stdout is block-buffered, so this is what makes the last lines arrive at
  all. If that flush fails in a way that *loses* output — a full or failing
  disk, a stream closed underneath the process — the wrapper exits **119**
  with one line on stderr instead of the code it was about to report. That is
  deliberate: reporting the child's own code would claim a complete,
  faithfully relayed run. A receiver that simply went away
  (`BrokenPipeError`, e.g. `python -m processkit run ... | head`) is *not*
  that case and stays silent — no exit code can deliver output to a closed
  pipe.
- **Ctrl+C that lands outside `run`/`supervise`'s own guarded blocks** — during
  startup, argument parsing, or `doctor`. It exits `128 + SIGINT` (`130`) with
  the same one-line `processkit: interrupted` message the guarded paths print,
  on every platform. For `doctor` this matters beyond tidiness: `1` is a valid
  `doctor` verdict, so an interrupted probe must never be reported as one.

## supervise

**Basic usage:**

```bash
python -m processkit supervise [OPTIONS] -- PROGRAM [ARG ...]
```

`supervise` keeps a command alive by restarting it according to a selected
policy, with configurable exponential backoff. Its child's stdin is inherited
exactly as with `run` (`Command.inherit_stdin()`). Stdout/stderr are handled
differently than `run`, though: `Supervisor` requires a **piped** stdout to
capture each incarnation's result (to evaluate the restart policy and
populate `SupervisionOutcome.final_result`) — a non-piped stdout errors every
incarnation. To still stream live to this terminal, this wrapper pipes both
streams and tees every decoded line straight through to its own inherited
stdout/stderr (`Command.stdout_tee`/`stderr_tee`); output still appears live,
just line-buffered rather than a byte-for-byte fd passthrough.

| Flag | Description |
|---|---|
| `--restart {always,on_crash,never}` | Restart policy passed to `Supervisor`. |
| `--max-restarts N` | Stop after `N` restarts. `N` must be positive. |
| `--backoff-initial SECONDS` | Initial delay before a restart. Must be positive. |
| `--backoff-factor FLOAT` | Multiplier for successive restart delays. Must be at least `1`. |
| `--max-backoff SECONDS` | Upper bound for restart delay. Must be positive. |
| `--no-jitter` | Disable restart-delay jitter; jitter is enabled by default. |
| `--timeout SECONDS` | Apply `Command.timeout(seconds)` independently to every incarnation. A final timed-out incarnation exits `124`. |
| `--max-memory BYTES` | Cap every incarnation's whole process tree memory. |
| `--max-processes N` | Cap every incarnation's process-tree size. |
| `--cpu-quota FLOAT` | Cap every incarnation's CPU as a fraction of one core. |
| `--cpu-affinity CPU[,CPU...]` | Pin every incarnation to logical CPUs on Linux/Windows. |
| `--create-no-window` | Apply `Command.create_no_window()` to every incarnation. |
| `--health-port HOST:PORT` | Probe a TCP endpoint; bracket IPv6 literals, for example `[::1]:8080`. Mutually exclusive with `--health-http`. |
| `--health-http URL` | Probe an absolute HTTP(S) URL; any 2xx response is healthy. Mutually exclusive with `--health-port`. |
| `--health-interval SECONDS` | Probe cadence, default `5`; requires a health probe. |
| `--health-timeout SECONDS` | Per-probe network timeout, default `1`; requires a health probe. |
| `--env-clear` | Start the child with an empty environment. |
| `--inherit-env NAME` | Allow-list a parent variable (implies `--env-clear`). Repeatable. |
| `--env-file PATH` | Load docker-style `KEY=VALUE` lines. Repeatable; later files win and `--env` wins over files. |
| `--env KEY=VALUE` | Set or override a child variable. Repeatable. |
| `--cwd DIR` | Run the child with `DIR` as its working directory. |

```bash
python -m processkit supervise --restart always --max-restarts 5 -- some_command
```

Health checks are synchronous, bounded probes passed to `Supervisor`'s
`health_check=` hook. The first probe runs after one interval, giving the child
a startup grace period; three consecutive failures use the binding's default
threshold and force-kill the wedged incarnation. A restart policy then treats
that kill like any other crash. With `--restart never`, a POSIX signal kill
uses `128 + N`; on a platform that reports no signal it uses the existing
internal-failure code `120` with a health-check diagnostic.

| Exit code | Meaning |
|---|---|
| *(the final child result's code)* | Supervision stopped because the restart policy was satisfied. |
| `119` | This wrapper could not deliver its own buffered output — the entry-point-wide code from [How the wrapper terminates](#how-the-wrapper-terminates), not a `supervise` one. |
| `120` | An internal command/supervisor failure, including a missing or unexecutable program. |
| `121` | The restart policy required another attempt, but `--max-restarts` was exhausted. |
| `122` | Supervision gave up due to a `give_up_when` condition (reserved for API-driven outcomes). |
| `124` | The final incarnation hit its per-incarnation `--timeout`. |
| `128 + N` | The final incarnation was killed by signal `N` (POSIX only) — mirrors `run`'s own convention. |
| `128 + SIGINT` (`130`) | `python -m processkit` itself was interrupted with Ctrl+C. |

## Resource limits: hard cap or best effort?

The `run` and `supervise` forms of `--max-memory` / `--max-processes` /
`--cpu-quota` need a real container — a
Windows Job Object or a Linux **cgroup-v2 root** (see
[Process groups](process-groups.md#resource-limits-the-sandbox) and
[Platform support](platforms.md)). Inside an ordinary container, a systemd
user session, or on macOS, the kernel refuses these caps outright.

Rather than fail the operation over a cap the environment can't grant, this
CLI **degrades**: it prints a warning to stderr and runs (or supervises) the
child in a plain, uncapped `ProcessGroup` — "contained, but uncapped" — the same
fallback `examples/04_sandbox_resource_limits.py` uses. The no-orphan
containment guarantee still applies either way; only the specific numeric
caps are dropped. If your script depends on the cap actually being enforced,
check stderr for that warning rather than assuming it always held.

## `doctor`: preflight-diagnose the environment

`--max-memory`/`--max-processes`/`--cpu-quota` depend on kernel primitives
that are not guaranteed to be there (see above) — until now, the only way to
find out was to run `run` for real and read a warning on stderr, or catch
`ResourceLimit`/`Unsupported` from the Python API. `python -m processkit
doctor` answers the same question up front, without running anything:

```bash
python -m processkit doctor
```

```text
processkit doctor
  graceful-stop scope     : whole_tree
  parent-death cleanup    : whole_tree
  processkit-rs version   : 3.1.0
  containment mechanism : cgroup_v2
  resource limits        : available
  verdict: OK - containment and resource limits are both available (exit 0)
```

Degraded (containment holds, but the kernel refuses at least one resource
limit — the typical container / systemd user session / non-root cgroup /
macOS case; `--max-memory`, `--max-processes`, and `--cpu-quota` are probed
**independently**, since on Linux cgroup-v2 they are separate controllers
that can be unavailable one without the others):

```text
processkit doctor
  graceful-stop scope     : opt_in_members
  parent-death cleanup    : direct_child_only
  processkit-rs version   : 3.1.0
  containment mechanism : process_group
  resource limits        : unavailable --max-memory (ResourceLimit: cgroup v2 root required)
  note: --max-memory/--max-processes/--cpu-quota need a Windows Job Object or
  a Linux cgroup-v2 root; the kernel typically refuses them inside
  containers, systemd user sessions, and non-root cgroups, and always on
  macOS (docs/cli.md#resource-limits-hard-cap-or-best-effort).
  verdict: DEGRADED - containment is enforced, but resource limits are not (exit 1)
```

It never spawns a child process — only constructs (and immediately drops) a
few throwaway `ProcessGroup` instances to see what the kernel actually
grants (one for the containment mechanism, one per resource-limit
controller). `doctor` has its own exit-code namespace, deliberately disjoint
from `run`'s codes above (`124`/`125`/`126`/`127`/`128 + signal`) *and* from
argparse's own usage-error code `2` (the same code `run` itself uses for a
bad invocation) — `doctor` never returns `2` as a diagnostic verdict, so a
CI gate can always read `2` as "you called this wrong", unambiguous from any
of the codes below:

| Exit code | Meaning |
|---|---|
| `0` | Resource limits are available (containment *and* all three caps hold). |
| `1` | Containment is enforced, but at least one resource limit is not — the same "contained, but uncapped" gap `run` degrades around. |
| `2` | *(not returned by `doctor` itself)* — a usage error, e.g. an unknown flag or `doctor`'s disallowed trailing command; reserved to keep it unambiguous from a real diagnostic result. |
| `3` | Containment itself is unavailable (should not happen on any supported platform). |
| `4` | A probe raised an unexpected operational error (`OSError`/`PermissionError`, e.g. failing to read cgroup state) rather than a definitive result — the environment's actual availability could not be determined. |

The two entry-point-wide codes from
[How the wrapper terminates](#how-the-wrapper-terminates) — `119` (output the
wrapper could not deliver) and `128 + SIGINT` (`130`, interrupted) — are
disjoint from those verdicts by construction, so a CI gate reading `doctor`'s
code never has to disambiguate them from a diagnosis. In particular an
interrupted `doctor` reports `130`, never `1`.

For CI, `doctor --json` replaces that text report with one JSON object on
stdout while preserving the same exit code. Its stable base schema is:

```json
{
  "mechanism": "cgroup_v2",
  "host_containment": {
    "mechanism": "cgroup_v2",
    "soft_stop_scope": "whole_tree",
    "parent_death_cleanup": "whole_tree",
    "crate_version": "3.1.0"
  },
  "verdict": "OK",
  "exit_code": 0,
  "resource_limits": {
    "max_memory": true,
    "max_processes": true,
    "cpu_quota": true
  },
  "caveat": "--max-memory/--max-processes/--cpu-quota need a Windows Job Object or a Linux cgroup-v2 root; the kernel typically refuses them inside containers, systemd user sessions, and non-root cgroups, and always on macOS (docs/cli.md#resource-limits-hard-cap-or-best-effort)."
}
```

`mechanism`, `verdict`, and `caveat` are strings; `exit_code` is an integer;
all `host_containment` fields are strings; and all `resource_limits` fields are
booleans. `verdict` is one of `OK`,
`DEGRADED`, `UNAVAILABLE`, or `ERROR`, matching exit codes `0`, `1`, `3`, and
`4`. When an `OSError` prevents a definitive probe result, the payload also
contains `error_probe_failures`, a list of error strings.

`doctor` takes only `-h`/`--help` and `--json` — in particular, no trailing
`-- PROGRAM ...` (it is diagnostic-only and never runs a command).

## What you don't get here

This is a v1, deliberately minimal wrapper — reach for the Python API
directly for anything beyond it: piping several commands together
([Pipelines](pipelines.md)), advanced supervision callbacks such as `stop_when` and `give_up_when`
([Supervision](supervision.md)), line-by-line streaming ([Streaming &
interactive I/O](streaming.md)), or running a batch of commands concurrently
(`output_all` / `aoutput_all`). There is also no `--dry-run` mode yet — a
plausible follow-up, not implemented today.

---

Next: [Process groups](process-groups.md) ·
[Timeouts & cancellation](timeouts-and-cancellation.md) ·
[Cookbook](cookbook.md)
