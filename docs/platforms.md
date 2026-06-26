# Platform support & caveats

processkit's guarantee is strongest on Windows and weakest on macOS. This is
inherent to what each OS offers, and it is documented here rather than hidden.
`ProcessGroup.mechanism` tells you which mechanism is active at runtime:
`"job_object"`, `"cgroup_v2"`, or `"process_group"`.

## Teardown (the no-orphan guarantee)

| | Mechanism | When the `with` / `async with` block exits | If the Python process is hard-killed (`SIGKILL`, `os._exit`) |
|---|---|---|---|
| **Windows** | Job Object | Whole tree reaped (kernel-enforced) | **Still reaped** — `KILL_ON_JOB_CLOSE` fires when the last handle closes |
| **Linux** | cgroup v2 (else process group) | Whole tree reaped | **Best-effort** — teardown runs from the exit path, which a hard kill skips |
| **macOS / BSD** | process group | Tree reaped, *except* children that called `setsid()` | **Best-effort**, same caveat |

The takeaway: the `with` / `async with` exit path (and ordinary GC) reaps the
tree on every platform. Surviving a hard kill of the parent is a Windows-only
property. Lean on the context managers; don't rely on `__del__` or `atexit`,
which don't run on `SIGKILL` / `os._exit`.

Cancelling an awaited run (`task.cancel()`, `asyncio.wait_for`,
`asyncio.timeout`) reaps the run's tree on every platform — the dropped future
tears it down.

## Resource limits (`ProcessGroup(memory_max=…, max_processes=…, cpu_quota=…)`)

| | Support |
|---|---|
| **Windows** | Job Object enforces memory / active-process / CPU-rate caps |
| **Linux** | cgroup v2 — **only when this process runs at the cgroup-v2 root**. Under a container, a systemd session/scope/service, or any non-root cgroup, the kernel's "no internal processes" rule forbids it and `ResourceLimit` is raised |
| **macOS / BSD** | No whole-tree limit primitive — requesting any limit raises `ResourceLimit` (a fail-fast, never a silently-unbounded group) |

If you need limits inside a container, run the process at the container's cgroup
root (the create-leaf / migrate-self / enable-controllers dance), or use a
runtime that grants cgroup delegation.

## Signals, suspend/resume, stats

| | `signal()` / `suspend()` / `resume()` | `stats()` |
|---|---|---|
| **Windows** | Only `kill` is deliverable — it terminates the job; **every other name, including `term`, raises `Unsupported`**. suspend/resume freeze/thaw the job | Memory + process count via the OS process APIs |
| **Linux** | Real signals to the cgroup/process group; freeze via cgroup or `SIGSTOP`/`SIGCONT` | cgroup + `/proc` |
| **macOS / BSD** | Real signals to the process group | Process count only; CPU / peak-memory are `None` (no whole-tree kernel accounting) |

Operations a platform can't perform raise `Unsupported` — catch it if you target
multiple platforms.

## Python build

- Distributed as **abi3 wheels for CPython 3.10+** (one wheel per OS/arch runs on
  every supported minor version).
- **Free-threaded CPython (3.13+, PEP 703):** the published wheels target the
  standard (GIL) build. Free-threaded support tracks PyO3's no-GIL work and will
  arrive in a later release; until then, run processkit on a GIL build.

## Wheel availability

Prebuilt wheels are published for:

| Platform | Architectures |
|---|---|
| **Linux** (manylinux, glibc) | x86_64, aarch64 |
| **macOS** | x86_64 (Intel), arm64 (Apple Silicon) |
| **Windows** | x64 |

Not currently prebuilt: **musllinux** (Alpine), Windows on ARM, and 32-bit
targets. On those, `pip install processkit` builds from the sdist, which needs a
[Rust toolchain](https://rustup.rs/). An sdist is published alongside the wheels
for source builds anywhere.
