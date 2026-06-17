# processkit-py — Project Roadmap

> Published as **`processkit`** on PyPI — brand-continuous with the
> [`processkit`](https://crates.io/crates/processkit) Rust crate. Repository:
> **`processkit-py`** (sibling to `ProcessKit-rs`). See *Naming & publishing*.

## Premise

Python bindings to the `processkit` Rust crate — **not** a reimplementation.
The crate already owns the hard, dangerous, per-platform code: Job Object
containment, cgroup v2 delegation, the race-free `CREATE_SUSPENDED → assign →
resume` spawn, POSIX process groups. Porting that FFI by hand into a second
language doubles the bug surface on exactly the code that must never be wrong.
The binding stays thin; the Rust crate stays the single source of truth.

What survives the trip to Python:

- The **kernel-backed no-orphan guarantee** for process trees.
- An **asyncio-native** surface.
- **Honest results** — a non-zero exit is data, a timeout is captured, a
  cancellation is an error.

What does **not** survive unchanged: Rust's `Drop`-driven automatic teardown.
Python has no deterministic destruction, so the guarantee is expressed through
explicit context managers plus a best-effort fallback. This asymmetry is
load-bearing for several decisions below — and it is documented, never hidden:

- **Windows** — `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` reaps the tree when the
  last job handle closes. The kernel enforces it; it survives even a hard kill
  of the Python parent. This part is as strong as the Rust original.
- **Linux / macOS / BSD** — cgroup / process-group teardown requires an active
  kill from the parent. In Python that runs on the `with` / `async with` exit
  path; on `SIGKILL` / `os._exit` of the parent it does not fire. Strictly
  best-effort, and weaker than the Rust version, which dispatches teardown
  reliably from `Drop` on the normal-exit and panic paths.

## Target niche

Process containment for Python tooling that spawns subprocesses and leaks them:
agent / LLM frameworks, test runners, CI orchestration, sandboxed tool
execution. **Not** a general subprocess-convenience library — that space is
already served by `psutil`, `sh`, `plumbum`, `sarge`. The wedge is the
guarantee, and resource limits on untrusted child trees.

## Target API (illustrative)

```python
import asyncio
from processkit import Command, ProcessGroup

async def main():
	# Run-and-capture; a non-zero exit is data, not an exception.
	result = await Command("git", ["rev-parse", "HEAD"]).output()
	print(result.stdout.strip(), result.exit_code)

	# Kill-on-exit container for a whole tree.
	async with ProcessGroup() as group:
		server = await group.start(Command("my-server"))
		await server.wait_for_port(("127.0.0.1", 8080), timeout=10)
		# ... use the server ...
	# group exit reaps the whole tree, grandchildren included

asyncio.run(main())
```

## Architecture decisions

- **Binding layer:** PyO3 + maturin.
- **Async bridge:** `pyo3-async-runtimes` (tokio ↔ asyncio).
- **Distribution:** abi3 wheels (cp39+) to keep the build matrix flat;
  `cibuildwheel` across Windows x64, manylinux x86_64 / aarch64,
  macOS x86_64 / arm64.
- **Versioning:** the crate is pre-1.0. The binding pins an exact crate version
  and tracks API churn deliberately, not transitively.

## Naming & publishing

The project ships under the **same name as the Rust core** — for a thin binding,
discoverability beats an independent brand. Someone who knows the crate must be
able to guess `pip install processkit` and land exactly right.

- **PyPI distribution + import name:** `processkit`
  (`pip install processkit` → `import processkit`). The normalized name is
  verified free on PyPI. A dormant `process-kit` (hyphenated, a single 0.1.0
  release from 2014, project actually named `pkit`) is a *different* normalized
  name and does not block it — only a faint namesake.
- **crates.io:** the public Rust core stays `processkit` (already published).
- **GitHub repository:** `processkit-py`, sitting beside `ProcessKit-rs` — the
  `-rs` / `-py` suffix pair signals "Rust core / Python bindings" at a glance.
- **PyO3 binding crate:** *not* published to crates.io — compiled into the
  wheels only. Should it ever need a crates.io name, use `processkit-py`; the
  published Rust crate is always the `processkit` core, never the binding.
- **npm:** `processkit` is free there too — reserved as a courtesy only, no
  package planned.

---

## Phases

### Phase 0 — De-risk spikes  *(effort: S, blocking)*

Two unknowns can sink the project. Prove both with throwaway code before any
real commitment.

- **Async-bridge spike.** Expose a single `Command.run()` as a Python
  `async def`, await it under asyncio, and confirm cancelling the awaiting task
  tears the tree down. This is the single biggest technical risk.
- **Teardown spike.** Observe a held handle across: normal `with`-exit, GC of an
  unreferenced object, `KeyboardInterrupt` / SIGINT, and interpreter shutdown.
  Confirm Windows `KILL_ON_JOB_CLOSE` reaps on handle close; confirm Linux
  cgroup / pgroup teardown fires from the context-manager path.

**Exit criteria:** a script that spawns child → grandchild, awaits, and proves
the grandchild is dead after context exit, on both Windows and Linux.

### Phase 1 — Minimal viable core, sync surface  *(effort: M)*

Validate the FFI, packaging, and error mapping **without** the async-bridge risk.

- `Command` builder; `run()`, `output()`, `exit_code()`, `probe()`.
- `ProcessGroup` as a context manager (`with`) — the explicit-cleanup design
  made real.
- Containment verified from Python on all three mechanisms (the Rust side
  already does the work; this is exposure + tests).
- **Error mapping:** Rust `Error` enum → a Python exception hierarchy
  (`ProcessError` base; `Timeout`, `Cancelled`, `ResourceLimit`, `Unsupported`).
  Decide alias policy vs builtins / `asyncio` exceptions (see Open Decisions).
- Packaging: maturin build, abi3 wheel, `cibuildwheel` matrix green.

**Exit criteria:** `pip install` a wheel on Win + Linux + macOS, run a captured
command, get a typed `ProcessResult`; orphan-leak test passes on the `with`
path.

### Phase 2 — Async & streaming  *(effort: L)*

- `async` variants of `run` / `output` / `start`; `async with ProcessGroup`.
- `RunningProcess`: stdout line streaming as an async iterator
  (`async for line in proc.stdout_lines()`), interactive stdin,
  `finish_streamed`.
- **Cancellation:** map `asyncio.CancelledError` on an awaited run → tree kill.
  In async Python this is where the no-orphan promise naturally lives.
- **Timeouts:** captured-vs-raised semantics; define the interaction with
  `asyncio.wait_for` / `asyncio.timeout`.

**Exit criteria:** stream a long-running child line by line; cancel the task
mid-stream; prove the tree is reaped and the result reports `Cancelled`.

### Phase 3 — Higher-level features  *(effort: L, parity, demand-ordered)*

Prioritised by Python demand, not crate order.

- **Supervisor** — restart policies, backoff, stop conditions. High value for
  the agent / service niche.
- **Readiness probes** — `wait_for_line` / `wait_for_port` / `wait_for`. High:
  "start a server, then use it" is a constant Python pain point.
- **Resource limits** — `memory_max` / `max_processes` / `cpu_quota`. High: the
  real differentiator vs `psutil` for sandboxing untrusted / agent tool trees.
- **Pipelines** — shell-free `a | b | c`. Medium.
- **Signals / suspend / resume / members / stats** — lower; expose
  incrementally.

### Phase 4 — Testing seam, typing, docs  *(effort: M)*

- **Test seam — design fork.** The Rust `ProcessRunner` trait does not map
  cleanly to a Python-implemented double via PyO3. Favoured approach: a pytest
  plugin + record/replay cassettes driven from Python, plus
  `ScriptedRunner` / `RecordReplayRunner` configured from the Python side —
  rather than asking users to implement a Rust trait. Decide in this phase.
- **Type stubs** (`.pyi`) for full typing / IDE support — non-negotiable for
  Python adoption.
- **Docs** — mkdocs; cookbook mirroring the crate's "I want to … → snippet".

### Phase 5 — Hardening & 1.0  *(effort: M)*

- Platform-caveat matrix documented end to end (mirror the crate's honesty).
- Stress / leak tests: parent `SIGKILL`, panic paths, interpreter shutdown,
  `KeyboardInterrupt`, on every mechanism.
- **Free-threaded CPython (3.13+, PEP 703)** compatibility pass — track PyO3's
  no-GIL support.
- Performance sanity — syscall-bound work; just confirm the bridge adds no
  silly overhead.
- API-stability commitment + semver.

---

## Risk register

- **Async bridge (tokio ↔ asyncio).** Highest risk. Mitigation: Phase 0 spike;
  keep a sync surface as a fallback that does not depend on the bridge.
- **Teardown reliability from Python.** `__del__` is unreliable; `atexit` does
  not fire on `SIGKILL` / `os._exit`. Mitigation: lean on `with` / `async with`;
  lean on Windows `KILL_ON_JOB_CLOSE`; document Linux as best-effort, honestly.
- **Async ecosystem fragmentation.** asyncio-only leaves trio / anyio users out.
  Mitigation: scope to asyncio for v1; revisit anyio later (or never).
- **Binding tracks a pre-1.0 crate.** Mitigation: pin exact versions; keep the
  binding thin so churn is cheap to absorb.
- **Distribution.** cdylib + platform FFI across the wheel matrix is fiddly.
  Mitigation: abi3 to flatten the matrix; `cibuildwheel` from day one.
- **Test seam doesn't port.** See Phase 4 — resolved by a Python-native
  approach rather than a literal trait binding.

## Non-goals (deliberate scope cuts)

- Not a general subprocess-convenience library — cede that to `sh` / `plumbum` /
  `psutil`.
- No trio / curio support in v1.
- No pure-Python fallback — without the compiled extension there is no
  guarantee, so it is not a supported configuration.
- No Windows-pre-10, no cgroup v1.

## Open decisions

1. **Name — resolved.** Published as `processkit` (PyPI) / repo `processkit-py`.
   See *Naming & publishing*.
2. **Async-only vs anyio-backed** for future trio reach.
3. **Sync API as a first-class surface, or async-only?** (Leaning: keep sync as
   a legitimate secondary surface — not everyone is in asyncio.)
4. **abi3 vs version-specific wheels** (leaning abi3).
5. **Exception aliasing** — alias `asyncio.CancelledError` / builtin
   `TimeoutError`, or keep a fully independent hierarchy?
6. **Publish order** — publish the crate to crates.io first and pin, or vendor
   it as a git submodule during early development?
