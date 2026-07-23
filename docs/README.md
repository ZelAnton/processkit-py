![processkit](https://raw.githubusercontent.com/ZelAnton/processkit-py/main/.github/cover.png)

[![CI](https://github.com/ZelAnton/processkit-py/actions/workflows/ci.yml/badge.svg)](https://github.com/ZelAnton/processkit-py/actions/workflows/ci.yml)
[![CodeQL](https://github.com/ZelAnton/processkit-py/actions/workflows/codeql.yml/badge.svg)](https://github.com/ZelAnton/processkit-py/actions/workflows/codeql.yml)
[![PyPI](https://img.shields.io/pypi/v/processkit-py.svg)](https://pypi.org/project/processkit-py/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://github.com/ZelAnton/processkit-py/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/ZelAnton/processkit-py/blob/main/LICENSE)

Async-and-sync child-process management for Python with a kernel-backed
**no-orphan guarantee**: every process you start — and everything *it* spawns —
lives in a kill-on-exit container (a **Windows Job Object**, a **Linux cgroup
v2**, or a POSIX process group). Subject to the documented POSIX escape caveats,
normal completion, errors, timeouts, cancellation, and context-manager exit reap
descendants as a unit. Abrupt owner-death coverage is platform-specific and
reported explicitly.

Beyond spawning a subprocess: run-and-capture, line streaming, interactive
stdin, shell-free pipelines, readiness probes, timeouts & cancellation,
supervision with restart/backoff, resource-limited sandboxes, and a mockable
runner seam for subprocess-free tests — each in a synchronous *and* an
asyncio-native form.

```python
from processkit import Command

# Require success and get trimmed stdout; a failure raises a typed exception.
version = Command("python", ["--version"]).run()
print(version)
```

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

> **Stable API.** The public API has been stable since 1.0 and follows
> [Semantic Versioning](https://semver.org/): breaking changes land only in a new
> major version, so `1.x` upgrades are backward-compatible. See
> [CHANGELOG.md](https://github.com/ZelAnton/processkit-py/blob/main/CHANGELOG.md), and
> [ROADMAP.md](https://github.com/ZelAnton/processkit-py/blob/main/ROADMAP.md) for how it was built.

## Guides

**New here?** Start with the [Cookbook](cookbook.md) — short task-to-snippet
recipes for everything the package does — then read [Running commands](commands.md)
end to end (it's the vocabulary every other guide builds on). Coming from the
standard library? [Coming from subprocess](migrating.md) maps your existing
`subprocess` / `asyncio.subprocess` patterns onto their processkit equivalents.
Reach for the rest as the need arises, and keep [Platform support](platforms.md)
handy before you ship: it collects every per-OS caveat in one place.

| Guide | Covers |
|---|---|
| [Cookbook](cookbook.md) | "I want to …" → working snippet, for every capability; the fastest way in |
| [Coming from subprocess](migrating.md) | Side-by-side translation of `subprocess` / `asyncio.subprocess` patterns, the exception mapping, and the whole-tree containment the stdlib can't give |
| [Running commands](commands.md) | The `Command` builder end to end — args, env/sandboxing, stdin, stdout/stderr redirection, encodings, output caps, timeouts, privileges — and every consuming verb (`output`, `run`, `probe`, …) with its error semantics |
| [Process groups](process-groups.md) | Kill-on-drop containment: creating groups, spawning, teardown, whole-tree signals, suspend/resume, member listing, resource limits, stats |
| [Sandboxing untrusted tools](sandboxing.md) | The agent/LLM-tool recipe: locked-down env → bounded output → group resource limits → timeout → teardown, a checklist, and an honest threat model (what this does and does not protect against) |
| [Streaming & interactive I/O](streaming.md) | `astart()` and the live `RunningProcess`: line streaming, interactive stdin, readiness probes (`wait_for_line` / `wait_for_port` / `wait_until`), per-run profiling |
| [Pipelines](pipelines.md) | Shell-free command pipelines — chain with `.pipe()` or the pipe operator: wiring, pipefail attribution, chain timeouts, binary tails |
| [Timeouts & cancellation](timeouts-and-cancellation.md) | How a deadline is *captured* vs when it raises, interrupting a blocked sync call (Ctrl+C), and asyncio cancellation that reaps the whole tree |
| [Supervision](supervision.md) | Keeping a child alive: restart policies, backoff & jitter, stop conditions, outcomes |
| [Testing your code](testing.md) | The `ProcessRunner` seam — `ScriptedRunner` (incl. scripted streaming `start()`), record/replay cassettes, the `RecordingRunner` spy, the `CliClient` wrapper, and the autoloaded **pytest plugin** (ready-made fixtures + a no-real-spawn guard) |
| [Command-line usage](cli.md) | `python -m processkit run -- ...`: containment and resource limits for a shell command with no Python to write, flags, exit codes |
| [Performance & overhead](performance.md) | Why the workload is syscall-bound, what each benchmark in `benchmarks/` measures, how to reproduce them locally, and qualitative throughput/scaling expectations |
| [Async runtimes & event loops](event-loops.md) | Which event loops the asyncio-native surface runs on — asyncio and uvloop (yes), anyio-on-asyncio (yes), native trio / anyio-on-trio / curio (no) — and why |
| [Platform support](platforms.md) | The containment mechanisms, every per-feature support matrix in one place, and the caveats worth knowing before you ship |
| [Troubleshooting](troubleshooting.md) | A symptom-to-guide map for resource-limit, signaling, event-loop, cassette, privilege-drop, and teardown errors |

## Packaging

Unlike the Rust crate's compile-time feature flags, the Python wheel ships **one
surface with everything enabled** — resource limits, signals/stats,
record/replay, and opt-in logging are all present in every published wheel.
There is nothing to opt into at install time:

```bash
pip install processkit-py   # import name: processkit
```

On a platform without a prebuilt wheel, build from source (`uv run maturin
develop`) — see the
[README](https://github.com/ZelAnton/processkit-py#building-from-source).

Distributed as **abi3 wheels for CPython 3.10+** (one wheel per OS/arch runs on
every supported minor version, 3.14 included), plus a **version-specific
free-threaded wheel** for CPython 3.14t (PEP 703). See
[Platform support](platforms.md) for the wheel matrix and the free-threaded note.

## The 60-second tour

```python
import asyncio
from processkit import Command, ProcessGroup

# One-shot, sync: capture everything. A non-zero exit is data, not an exception.
head = Command("git", ["rev-parse", "HEAD"]).output()
print("HEAD =", head.stdout.strip(), head.code)

# Success-checking: a non-zero exit / timeout / signal-kill becomes a typed exception.
version = Command("python", ["--version"]).run()

async def main():
    # Asyncio: the same verbs with an `a` prefix; cancelling reaps the whole tree.
    result = await Command("git", ["status", "--short"]).aoutput()

    # Stream a child's stdout; the context manager reaps the tree on exit.
    async with await Command("my-build", ["--watch"]).astart() as proc:
        async for line in proc.stdout_lines():
            print(line)

    # Containment: anything started in the group dies with it (grandchildren too).
    async with ProcessGroup() as group:
        await group.astart(Command("dev-server"))
    # async-with exit reaps the whole tree

asyncio.run(main())
```

## API reference

The [API reference](api-reference.md) is the complete, per-symbol index of the
public surface — every class, function, protocol, type alias, and exception,
plus the `processkit.testing` submodule. It is generated straight from the type
stubs and docstrings (the same source your IDE and `mypy` read), so it never
drifts from the real API. These guides are the narrative layer on top — they
explain how the pieces compose, with the platform fine print collected in
[Platform support](platforms.md). The underlying algorithms (the OS containment
mechanisms, race-free spawn) live in the
[`processkit`](https://docs.rs/processkit) Rust crate.
