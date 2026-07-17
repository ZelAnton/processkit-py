# Performance & overhead

**Short answer: the bridge adds no silly overhead.** Spawning a child process
is fundamentally *syscall-bound* — `fork`/`exec`/`posix_spawn` on POSIX,
`CreateProcess` plus Job Object setup on Windows — and that OS-side cost
dominates the total wall-clock time of a run by a wide margin. The PyO3 glue
between Python and the `processkit` Rust crate (argument marshaling, the
async-runtime hop for the asyncio surface, error mapping) adds a small,
constant-time cost on top of a syscall path that already dominates the total.
This page explains what "no silly overhead" means concretely, points at the
benchmark suite that backs the claim with a real number instead of a loose
pass/fail bound, and shows how to reproduce it yourself.

## Why the workload is syscall-bound

Every one-shot verb (`output()`, `run()`, …) and every `ProcessGroup.start()`
does the same thing under the hood: ask the kernel to create a process (and,
for a group, first create and enter its containment mechanism — a Windows Job
Object, a Linux cgroup v2, or a POSIX process group), wait for it to produce
output and/or exit, then tear the containment down. None of that work can be
made faster by changing what happens *above* the crate boundary — the crate
already does the minimum number of syscalls the OS requires, with no
busy-polling. See [Architecture](internals.md#two-layers-one-boundary) for
where the binding crate's thin glue ends and the `processkit` crate's platform
logic begins; the binding layer never reimplements any OS mechanism, so it
never becomes a bottleneck.

Because process creation is what dominates, the per-call overhead in the
Python↔Rust boundary is lost in the noise next to a kernel-side operation
costing orders of magnitude more — see [What each benchmark
measures](#what-each-benchmark-measures) below for the harness that turns
this into a reproducible number instead of a fixed figure here. That is the
whole argument behind "no silly overhead": not that the bridge is free, but
that its cost is negligible relative to the workload it wraps.

## What each benchmark measures

The [`benchmarks/`](https://github.com/ZelAnton/processkit-py/tree/main/benchmarks)
suite (`pytest-benchmark` based) turns that qualitative argument into
reproducible numbers, answering the question
[ROADMAP.md](https://github.com/ZelAnton/processkit-py/blob/main/ROADMAP.md)'s
Phase 5 asks with a real measurement instead of only the loose sanity bound in
`tests/test_hardening.py::test_no_silly_per_call_overhead`:

- **`test_spawn_capture.py`** — spawn + capture a single short-lived command:
  `processkit`'s `Command(...).output()` against the two stdlib "naive"
  equivalents, `subprocess.run(..., capture_output=True)` and
  `asyncio.create_subprocess_exec(...)` + `communicate()`. Same payload on all
  three, so the comparison isolates per-call overhead rather than a differing
  workload.
- **`test_process_group.py`** — `ProcessGroup` start/exit: creating the
  group's kernel container, entering it, starting one short-lived child, and
  tearing the whole tree down. This is the cost of containment itself, on top
  of a bare spawn.
- **`test_streaming_throughput.py`** — `RunningProcess.stdout_lines()` (see
  [Streaming & interactive I/O](streaming.md)) draining a known number of
  lines end to end, i.e. sustained line-streaming throughput rather than a
  single spawn/exit round trip.
- **`test_output_all.py`** — `output_all()` / `aoutput_all()` (see
  [Cookbook](cookbook.md)) at 1/10/50-way concurrency, i.e. how batched
  fan-out scales as concurrency grows.

## Reproducing locally

The suite is **not** part of the PR gate — it lives in its own `bench`
dependency-group and is excluded from `testpaths`, so an ordinary
`pytest`/`uv run pytest` never collects it. Install the group and run it
explicitly:

```console
uv sync --group bench
uv run pytest benchmarks/ --benchmark-only -p no:xdist -o addopts=""
```

`-p no:xdist -o addopts=""` disables `-n auto` (the repo's default
`addopts`) — `pytest-benchmark` needs to run in the main process, in a single
worker, to produce meaningful timings; under `pytest-xdist` it silently skips
measuring instead. See
[`benchmarks/README.md`](https://github.com/ZelAnton/processkit-py/blob/main/benchmarks/README.md)
for the full set of useful flags (`--benchmark-compare`,
`--benchmark-autosave`, `--benchmark-json`, …).

## Qualitative expectations

Rather than pin numbers here — which drift with hardware, OS, and Python
version, and would go stale the moment they were written down — this section
sets expectations you can sanity-check against your own run of the harness
above:

- **Single-call overhead is small relative to spawn cost.** The gap between
  `processkit`'s `output()` and the stdlib equivalents in
  `test_spawn_capture.py` should be a small fraction of the total per-call
  time, not a multiple of it — the bulk of the time in every one of the three
  compared approaches is the OS spawning and reaping the child.
- **Containment adds a bounded, one-time setup/teardown cost per group**, not
  a per-member one — creating and entering a Job Object / cgroup / process
  group happens once in `ProcessGroup.start()`/`__aenter__`, so starting many
  members into an already-open group is cheap relative to opening the group
  itself.
- **Line-streaming throughput scales with the amount of output**, not with a
  fixed per-line Python↔Rust round trip — `stdout_lines()` batches reads on
  the Rust side, so throughput should stay close to linear as line count
  grows.
- **`output_all()`/`aoutput_all()` scale sub-linearly with concurrency** up to
  the point where the workload becomes bound by the number of OS threads/CPUs
  available to run children concurrently, not by anything in the binding
  layer.

## Continuous tracking

The `bench` job in
[`nightly-hardening.yml`](https://github.com/ZelAnton/processkit-py/blob/main/.github/workflows/nightly-hardening.yml)
runs this suite on the same `schedule`/`workflow_dispatch` triggers as the
`stress` job — never on `push`/`pull_request` — and publishes the results as a
table in the job summary, so a regression shows up as a trend across nights
rather than only when someone happens to run the harness locally.
