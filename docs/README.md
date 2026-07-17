# processkit — documentation

`processkit` is a child-process toolkit for Python — the asyncio-native,
kernel-backed, no-orphan binding to the [`processkit`](https://crates.io/crates/processkit)
Rust crate. It is organized in two layers:

```text
┌─────────────────────────────────────────────────────────────────┐
│  Runner layer (sync + asyncio)                                  │
│  Command · RunningProcess · Pipeline · Supervisor · CliClient   │
│  capture / streaming / interactive stdin / readiness probes     │
│  testing seam: Runner / Scripted / RecordReplay / Recording     │
├─────────────────────────────────────────────────────────────────┤
│  Group layer (kill-on-exit containment)                         │
│  ProcessGroup: start / signal / suspend / members /             │
│  stats / limits / shutdown                                      │
├─────────────────────────────────────────────────────────────────┤
│  OS mechanisms (in the Rust crate)                              │
│  Windows Job Object · Linux cgroup v2 · POSIX process group     │
└─────────────────────────────────────────────────────────────────┘
```

Every `Command` run gets containment for free: the one-shot verbs spawn into a
fresh private group that dies with the run, so a returning, raising, or cancelled
caller never leaks a process tree. The layers are also usable independently — a
raw `ProcessGroup` contains children you start into it, and the testing doubles
never touch the OS at all.

Both surfaces are first-class: a **synchronous** one (plain method names) and an
**asyncio** one (the same names with an `a` prefix). They share the same types
and the same no-orphan guarantee.

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
