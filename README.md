# processkit

Async-and-sync child-process management for Python with a kernel-backed
**no-orphan guarantee**: every process you start — and everything *it* spawns —
lives in a kill-on-exit container (a **Windows Job Object**, a **Linux cgroup
v2**, or a POSIX process group), so no descendant ever outlives your program.

Beyond spawning a subprocess: run-and-capture, line streaming, interactive
stdin, shell-free pipelines, readiness probes, timeouts & cancellation,
supervision with restart/backoff, resource-limited sandboxes, and a mockable
runner seam for subprocess-free tests — each in a synchronous *and* an
asyncio-native form.

[![CI](https://github.com/ZelAnton/processkit-py/actions/workflows/ci.yml/badge.svg)](https://github.com/ZelAnton/processkit-py/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ZelAnton/processkit-py/actions/workflows/codeql.yml/badge.svg)](https://github.com/ZelAnton/processkit-py/actions/workflows/codeql.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
<!-- Once published, add: [![PyPI](https://img.shields.io/pypi/v/processkit.svg)](https://pypi.org/project/processkit/) -->

```python
from processkit import Command

# Require success and get trimmed stdout; a failure raises a typed exception.
version = Command("python", ["--version"]).run()
print(version)
```

![Cover](https://raw.githubusercontent.com/ZelAnton/processkit-py/main/cover.png)

## Why processkit?

`subprocess` and `asyncio.subprocess` reach (at most) the direct child. The
processes *it* spawned — a build tool's compiler children, the real payload
behind a wrapper (`cmd /c …`, `sh -c …`), a test's helper servers — survive a
timeout, an exception, or a cancelled task, and keep running as orphans.

`processkit` spawns every child into the operating system's own containment
primitive — a **Job Object** on Windows, a **cgroup v2** on Linux (with a
process-group fallback), a POSIX **process group** on macOS/BSD — so teardown is
a kernel operation over the whole tree, not a best-effort signal to one pid:

- **Nothing escapes silently.** Exiting a `with` / `async with` block reaps every
  descendant, grandchildren included. Where a mechanism has a genuine weakness (a
  `setsid` child can escape a POSIX process group), `ProcessGroup.mechanism`
  reports the active backend instead of pretending — never a silent downgrade.
- **Sync *and* async, first-class.** The run-&-capture verbs, pipelines, and
  supervision each exist as a plain synchronous call *and* an `a`-prefixed asyncio
  coroutine, sharing one set of types. The inherently-streaming surfaces — live
  line streaming, interactive stdin, readiness probes — are asyncio-native
  (awaited on a started process), not duplicated as blocking calls.
- **Honest results.** A non-zero exit is data (`ProcessResult`) until you ask for
  success; a timeout is *captured* in the result; a cancellation is always an
  error; every platform divergence raises `Unsupported` or is documented. Raised
  exceptions carry structured fields and alias the stdlib's (`Timeout` is a
  `TimeoutError`, `ProcessNotFound` a `FileNotFoundError`, `PermissionDenied` a
  `PermissionError`).
- **Testable.** One runner seam swaps the real spawner for scripted doubles or
  record/replay cassettes — no subprocess in your tests.

### How it compares

| | whole-tree kill-on-exit | async | sync | limits / stats | streaming · pipelines · supervision |
|---|:---:|:---:|:---:|:---:|:---:|
| `subprocess` | — | — | ✓ | — | — |
| `asyncio.subprocess` | — | ✓ | — | — | — |
| **`processkit`** | **✓** | **✓** | **✓** | **✓** | **✓** |

The first column is the differentiator: a child's *descendants* are contained and
reaped as a unit (Job Object / cgroup v2 / process group), not just the direct
child.

> **Status: 1.0 — API frozen.** The public API follows
> [Semantic Versioning](https://semver.org/): breaking changes land only in a new
> major version, so `1.x` upgrades are backward-compatible. See
> [CHANGELOG.md](CHANGELOG.md), and [ROADMAP.md](ROADMAP.md) for how it was built.

This is a thin [PyO3](https://pyo3.rs/) binding to the published
[`processkit`](https://crates.io/crates/processkit) Rust crate — **not** a
reimplementation. All the hard platform code (Job Object containment, cgroup v2,
race-free spawn, POSIX process groups) lives in the crate; the Python layer
exposes a typed, asyncio-native surface with context-manager teardown.

## Install

```bash
pip install processkit
```

Distributed as **abi3 wheels for CPython 3.10+** (one wheel per OS/arch runs on
every supported minor version, 3.14 included), plus a **version-specific
free-threaded wheel** for CPython 3.14t ([PEP 703](https://peps.python.org/pep-0703/)
— importing the extension does not re-enable the GIL). (Until the first PyPI
release lands, build from source — see [below](#building-from-source).)

## Picking a verb

Every run starts with the same `Command` builder; the verb you finish with
decides what you get back. Each has an `a`-prefixed asyncio twin
(`run`/`arun`, …):

| You want | Call | You get |
|---|---|---|
| stdout, success required | `.run()` | trimmed `str`; non-zero exit / timeout / kill → typed exception |
| the full outcome, exit code as data | `.output()` / `.output_bytes()` | `ProcessResult` / `BytesResult` — code, stdout, stderr, `timed_out`; never raises on a non-zero exit |
| just the exit code | `.exit_code()` | `int` (a timed-out / killed run raises instead of inventing `-1`) |
| a yes/no answer | `.probe()` | `bool` — exit 0 → `True`, 1 → `False`, anything else raises |
| a live handle — streaming, stdin, probes | `.astart()` | `RunningProcess` |

The same vocabulary repeats on every layer (`Runner`, `CliClient`).
*Deeper: [Running commands](docs/commands.md).*

## Quick start

```python
from processkit import Command, ProcessGroup

# Capture output; a non-zero exit does not raise on its own.
result = Command("git", ["rev-parse", "HEAD"]).output()
print("HEAD is", result.stdout.strip(), "·", result.code)

# Require success and get trimmed stdout directly.
version = Command("python", ["--version"]).run()

# Feed stdin.
sorted_out = Command("sort").stdin_text("banana\napple\n").run()

# Share one kill-on-exit group across several children; the block exit reaps the
# whole tree, grandchildren included.
with ProcessGroup() as group:
    group.start(Command("dev-server"))
    # ... work ...
# graceful teardown on exit
```

The asyncio surface mirrors it with the `a` prefix and adds streaming:

```python
import asyncio
from processkit import Command, ProcessGroup

async def main():
    result = await Command("git", ["rev-parse", "HEAD"]).aoutput()

    # Stream a child's stdout; the context manager reaps the tree on exit.
    async with await Command("my-build", ["--watch"]).astart() as proc:
        async for line in proc.stdout_lines():
            print(line)

    async with ProcessGroup() as group:
        await group.astart(Command("dev-server"))

asyncio.run(main())
```

## Documentation

This README is the quick tour. The **[`docs/` guide set](docs/README.md)** goes
deeper on every capability, with more examples and the platform fine print in one
place. New here? Skim the [Cookbook](docs/cookbook.md) first — it maps "I want
to …" tasks to working snippets — then read
[Running commands](docs/commands.md) end to end:

| Guide | Covers |
|---|---|
| [Cookbook](docs/cookbook.md) | Task → snippet recipes for everything below; the fastest way in |
| [Running commands](docs/commands.md) | The full `Command` builder and every consuming verb, with error semantics |
| [Process groups](docs/process-groups.md) | Containment, teardown, signals, suspend/resume, members, limits, stats |
| [Streaming & interactive I/O](docs/streaming.md) | Line streaming, conversational stdin, readiness probes, per-run profiling |
| [Pipelines](docs/pipelines.md) | Shell-free `a \| b \| c`, pipefail attribution, chain timeouts |
| [Timeouts & cancellation](docs/timeouts-and-cancellation.md) | Captured vs raised deadlines, Ctrl+C, asyncio cancellation |
| [Supervision](docs/supervision.md) | Restart policies, backoff & jitter, stop conditions, outcomes |
| [Testing your code](docs/testing.md) | The runner seam, scripted/record-replay doubles, `CliClient` |
| [Platform support](docs/platforms.md) | Mechanisms, all capability matrices, every caveat |

## A tour of the capabilities

Each section below is a taste with a pointer to its full guide.

### Containing a process tree

Everything started in a `ProcessGroup` — and everything those processes spawn —
is reaped when the block exits:

```python
from processkit import Command, ProcessGroup

with ProcessGroup() as group:
    group.start(Command("dev-server"))
    group.start(Command("worker"))
    print(group.mechanism)        # "job_object" | "cgroup_v2" | "process_group"
    print(group.members())        # live member pids
# the whole tree, grandchildren included, is gone here
```

The `with` / `async with` exit (and ordinary GC) reaps the tree on every
platform; surviving a hard kill of the Python process itself is a Windows-only
property. Lean on the context managers, not `__del__` / `atexit`.
*Deeper: [Process groups](docs/process-groups.md) ·
[Platform support](docs/platforms.md).*

### Sandboxing with resource limits

Bound a whole tree's memory, process count, and CPU at creation, so a runaway or
untrusted child tree can't exhaust the host:

```python
from processkit import Command, ProcessGroup

tool = (
    Command("untrusted-tool")
    .env_clear().inherit_env(["PATH"])     # locked-down environment
    .output_limit(max_bytes=8 * 1024 * 1024)
)
with ProcessGroup(max_memory=512 * 1024 * 1024, max_processes=64, cpu_quota=1.0) as group:
    group.start(tool)
    print(group.stats().active_process_count)
```

Limits need a **Windows Job Object** or a **Linux cgroup-v2 root**; under a
container, systemd session, or other non-root cgroup the kernel forbids them and
`ResourceLimit` is raised — never a silently-unbounded group.
*Deeper: [Process groups → resource limits](docs/process-groups.md).*

### Signalling and pausing the whole tree

```python
with ProcessGroup() as group:
    group.start(Command("my-server"))
    group.signal("hup")        # term | kill | int | hup | quit | usr1 | usr2
    group.suspend()            # freeze the whole tree…
    group.resume()             # …and let it run again
```

Signals are POSIX-real; on Windows only `kill` is deliverable (it maps to the
Job Object terminate) and every other name — including `term` — raises
`Unsupported`. *Deeper: [Process groups](docs/process-groups.md).*

### Running many at once

`output_all` runs a whole batch with a **concurrency cap**, so fanning out
hundreds of commands can't exhaust file descriptors or the process table:

```python
from processkit import Command, ProcessResult, output_all

cmds = [Command("convert", [f"{i}.png", f"{i}.jpg"]) for i in range(200)]
results = output_all(cmds, concurrency=8)            # never >8 alive at once
failed = sum(not (isinstance(r, ProcessResult) and r.is_success) for r in results)
```

It is **collect-all**: each slot is one command's `ProcessResult`, or a
`ProcessError` for a spawn/I/O failure — a non-zero exit never short-circuits the
batch. `aoutput_all` / `output_all_bytes` / `aoutput_all_bytes` round out the
set. *Deeper: [Cookbook → run many at once](docs/cookbook.md).*

### Supervising a long-lived child

A `Supervisor` keeps a child **alive**: it restarts the command per policy
whenever it exits, with bounded restarts and exponential, jittered backoff:

```python
from processkit import Command, Supervisor

outcome = Supervisor(
    Command("my-server", ["--port", "8080"]),
    restart="on_crash",           # always | on_crash | never
    max_restarts=5,
    backoff_initial=0.2, backoff_factor=2.0, max_backoff=30.0,
    stop_when=lambda r: r.code == 0,   # a clean exit ends supervision
).run()                                # or: await ....arun()
print(outcome.restarts, outcome.stopped)
```

*Deeper: [Supervision](docs/supervision.md).*

### Waiting for a child to be ready

"Start a server, then use it" needs the server to be *ready*, not merely
started. Three async probes replace the arbitrary sleep:

```python
from processkit import Command, wait_for, wait_for_port, wait_for_line

proc = await Command("my-server").astart()
lines = proc.stdout_lines()
await wait_for_line(lines, lambda l: "listening on" in l, timeout=10)   # a log line
await wait_for_port("127.0.0.1", 8080, timeout=10)                      # a TCP port
await wait_for(lambda: health_check(), timeout=10, interval=0.1)        # any condition
```

A probe that doesn't pass in time raises `TimeoutError` and **does not kill the
child** — you decide what happens next.
*Deeper: [Streaming → readiness probes](docs/streaming.md).*

### Pipelines without a shell

`a | b | c` without a shell string — stages connected in-process (a relay, not a
shell), so no quoting or injection surface, and every stage lives in one shared
kill-on-exit group:

```python
authors = (
    Command("git", ["log", "--format=%an"])
    | Command("sort")
    | Command("uniq", ["-c"])
).run()
```

The outcome is **pipefail**: stdout is the last stage's, while the exit code,
stderr, and reported program come from the first stage that didn't exit cleanly.
`.timeout(d)` bounds the whole chain. *Deeper: [Pipelines](docs/pipelines.md).*

### Environment and privileges

```python
Command("worker").inherit_env(["PATH", "HOME", "LANG"]).run()        # allow-list on a cleared env
Command("worker").gid(1000).groups([1000]).uid(1000).setsid().run()  # POSIX: drop privileges, new session
Command("helper").create_no_window().run()                           # Windows: no console window
Command("daemonish").kill_on_parent_death().astart()                 # die with a hard-killed parent
```

`uid`/`gid`/`groups`/`setsid` are POSIX-only — on Windows the run raises
`Unsupported` rather than silently skipping a privilege drop. When dropping
privileges, set **all three** of `gid`/`groups`/`uid` — `uid` alone leaves the
child holding the parent's (often root's) supplementary groups.
*Deeper: [Running commands → privileges](docs/commands.md).*

### Cancelling a run

A blocked **sync** call honors `Ctrl+C` (raises `KeyboardInterrupt` and reaps the
tree). Cancelling an awaited **async** run — directly, or via `asyncio.wait_for`
/ `asyncio.timeout` — tears down the whole tree and raises
`asyncio.CancelledError`:

```python
import asyncio

task = asyncio.ensure_future(Command("long-job").aoutput())
task.cancel()        # the process tree is reaped; CancelledError propagates
```

Unlike a timeout — whose expiry is *captured* in the result as `timed_out` —
cancellation is always terminal.
*Deeper: [Timeouts & cancellation](docs/timeouts-and-cancellation.md).*

### Async streaming and interactive stdin

The one-shot verbs buffer the whole output. For long-running or conversational
children, `astart()` returns a live `RunningProcess`:

```python
# Conversational stdin: write a request, read the response.
proc = await Command("bc").keep_stdin_open().astart()
stdin = proc.take_stdin()
await stdin.write_line("2 + 2")
print(await anext(proc.stdout_lines()))   # 4
await stdin.close()
```

*Deeper: [Streaming & interactive I/O](docs/streaming.md).*

### Wrapping a CLI tool

`CliClient` binds a program to default timeout/env, so repeated calls pass only
their args:

```python
from processkit import CliClient

git = CliClient("git", default_timeout=30.0)
head = git.run(["rev-parse", "HEAD"])     # or: await git.arun([...])
clean = git.probe(["diff", "--quiet"])
```

For testable code, inject a `Runner` / `ScriptedRunner` at the `Command` level
instead — `CliClient` always uses the real runner.
*Deeper: [Testing your code](docs/testing.md).*

### Testing without spawning processes

Write your code against a runner, then inject a `ScriptedRunner` in tests:

```python
from processkit import Command, Reply, ScriptedRunner

scripted = ScriptedRunner()
scripted.on(["git", "rev-parse"], Reply.ok("deadbeef"))
assert scripted.run(Command("git", ["rev-parse", "HEAD"])) == "deadbeef"
```

`RecordReplayRunner` captures real tool output once and replays it offline.
*Deeper: [Testing your code](docs/testing.md).*

## Stability

processkit follows [Semantic Versioning](https://semver.org/). As of **1.0** the
public API — everything re-exported from `import processkit` and declared in the
type stubs — is stable: breaking changes land only in a new major version, so
`1.x` upgrades are backward-compatible. Anything underscore-prefixed is internal.

## Requirements

- Python 3.10 or later (abi3 wheel), including CPython 3.14 and the **free-threaded**
  (PEP 703) build 3.14t.
- See [platform support & caveats](docs/platforms.md) for per-OS behaviour and
  the wheel/architecture matrix.

## Building from source

The first release to PyPI is pending (`pip install processkit` is the supported
path once published). Until then — or on a platform without a prebuilt wheel
(musllinux, Windows on ARM, 32-bit) — build from source, which needs a
[Rust toolchain](https://rustup.rs/):

```bash
git clone https://github.com/ZelAnton/processkit-py
cd processkit-py
uv run maturin develop
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for build/test instructions and
conventions. To report a security issue, follow [SECURITY.md](SECURITY.md).

## License

This project is licensed under the [MIT License](LICENSE).
